"""G2 대체 경로 테스트. 가짜 LLM·임베더를 쓰므로 API 비용이 없다(검색은 로컬 DB를 읽기만 한다).

    PYTHONIOENCODING=utf-8 python scripts/test_g2_fallback.py
(1) 임베딩 실패 -> BM25 대체  (2) evaluate 실패  (3) feedback 실패  (4) improve 실패  (5) answer 실패 -> 안전 응답
(6) FatalLLMError는 어느 노드에서든 그대로 전파  (7) 바로 답변 경로는 수정 전 코드(G2 이전 커밋 3b8bedc)와 응답·트레이스·호출 수가 같음

주의: 점수 집계(run_rag.check)는 degraded 응답을 실패로 세야 한다(안전 응답이 abstain 기대 문항을 우연히 통과해
점수가 부풀려지는 것을 막는다). 그 처리는 scripts/run_rag.py 쪽 변경이다.
"""
import copy
import subprocess
import sys
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google.genai import errors  # noqa: E402

from rag import config, db, multi_agent  # noqa: E402
from rag.llm import FatalLLMError  # noqa: E402
from rag.retrieval import BM25Retriever  # noqa: E402

QUESTION, QSET = "신용거래 청약철회 기간은 며칠인가요?", "base"
VEC = list(np.random.RandomState(0).rand(config.EMBEDDING_DIM))


class FakeEmbedder:
    def __init__(self, exc=None):
        self.exc, self.calls = exc, 0

    def embed_query(self, text):
        self.calls += 1
        if self.exc:
            raise self.exc
        return VEC


class FakeLLM:
    """스키마 이름별로 정해진 응답을 돌려준다. fail={'Evaluation': exc}면 그 노드에서 예외를 낸다.
    첫 Evaluation은 insufficient(재검색 경로를 태우기 위함), 이후는 sufficient."""

    def __init__(self, fail=None, first_eval="insufficient"):
        self.fail, self.first_eval, self.calls, self.evals = fail or {}, first_eval, [], 0

    def __call__(self, system, user, schema, *a, **k):
        name = schema.__name__
        self.calls.append(name)
        if name in self.fail:
            raise self.fail[name]
        usage = {"model_calls": 1, "input_tokens": 100, "output_tokens": 10}
        if name == "Evaluation":
            self.evals += 1
            decision = self.first_eval if self.evals == 1 else "sufficient"
            return schema(decision=decision, relevant_docs=[1], covered=["a"],
                          missing=["b"] if decision == "insufficient" else [], reason="r"), usage
        if name == "Decomposition":
            return schema(sub_queries=[]), usage
        if name == "Feedback":
            return schema(causes=["c"], targets=["t"]), usage
        if name == "Improvement":
            return schema(queries=["청약 철회 기간 약관"], retriever="vector"), usage
        if name == "FinalAnswer":
            return schema(question_parts=[], response_type="answer", answer="14일 이내입니다.", citations=[1],
                          core_answered=True, reason="r"), usage
        raise AssertionError(name)


def load_original():
    """G2 이전 커밋(3b8bedc)의 multi_agent.py를 임시 모듈로 불러온다(수정 전 코드와 비교용)."""
    src = subprocess.run(["git", "show", "3b8bedc:rag/multi_agent.py"], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    mod = types.ModuleType("rag.multi_agent_orig")
    mod.__package__ = "rag"
    sys.modules[mod.__name__] = mod   # pydantic이 `from __future__ import annotations`의 타입 이름을 찾으려면 필요
    exec(compile(src, "multi_agent_orig.py", "exec"), mod.__dict__)
    return mod


def build(module, conn, bm25, embedder, llm):
    module.generate_structured = llm
    return module.MultiAgentRAG(conn, embedder, bm25)


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def raises(exc_type, fn):
    try:
        fn()
    except exc_type as e:
        return e
    except Exception as e:  # noqa: BLE001
        return e
    return None


def main():
    conn = db.connect()
    bm25 = BM25Retriever(conn, config.BASELINE_EXPERIMENT)
    boom = RuntimeError("boom")
    parse_err = ValueError("구조화 출력 파싱 실패")
    orig_gs = multi_agent.generate_structured

    try:
        # (1) 임베딩 실패 -> BM25 대체
        rag = build(multi_agent, conn, bm25, FakeEmbedder(boom), FakeLLM(first_eval="sufficient"))
        rec = rag.run(QUESTION, QSET)
        step = [t for t in rec["trace"] if t["step"] == "search"][0]
        check("1a 임베딩 실패 -> BM25 대체로 응답", rec["response_type"] == "answer" and rec["degraded"]
              and step.get("fallback", {}).get("retriever") == "bm25" and rec["retrieved_children"],
              f"children={len(rec['retrieved_children'])} reasons={rec['degraded_reasons']}")
        rag = build(multi_agent, conn, None, FakeEmbedder(boom), FakeLLM())
        e = raises(Exception, lambda: rag.run(QUESTION, QSET))
        check("1b bm25가 없으면 임베딩 예외를 그대로 올림", isinstance(e, RuntimeError) and "boom" in str(e))
        rag = build(multi_agent, conn, bm25, FakeEmbedder(errors.ClientError(402, {"error": {"message": "credits"}})), FakeLLM())
        e = raises(Exception, lambda: rag.run(QUESTION, QSET))
        check("1c 임베딩 402는 BM25로 숨기지 않고 FatalLLMError", isinstance(e, FatalLLMError), repr(e)[:80])

        # (2) evaluate 실패
        llm = FakeLLM(fail={"Evaluation": parse_err})
        rec = build(multi_agent, conn, bm25, FakeEmbedder(), llm).run(QUESTION, QSET)
        check("2 evaluate 실패 -> 현재 문맥으로 답변, degraded", rec["response_type"] == "answer" and rec["degraded"]
              and rec["evaluation"].get("degraded") and rec["search_rounds"] == 1 and "Feedback" not in llm.calls,
              f"reasons={rec['degraded_reasons']}")

        # (3) feedback 실패
        llm = FakeLLM(fail={"Feedback": boom})
        rec = build(multi_agent, conn, bm25, FakeEmbedder(), llm).run(QUESTION, QSET)
        check("3 feedback 실패 -> 재검색 접고 답변", rec["response_type"] == "answer" and rec["degraded"]
              and rec["search_rounds"] == 1 and "Improvement" not in llm.calls and llm.calls[-1] == "FinalAnswer",
              f"calls={llm.calls}")

        # (4) improve 실패
        llm = FakeLLM(fail={"Improvement": boom})
        rec = build(multi_agent, conn, bm25, FakeEmbedder(), llm).run(QUESTION, QSET)
        check("4 improve 실패 -> 재검색 접고 답변", rec["response_type"] == "answer" and rec["degraded"]
              and rec["search_rounds"] == 1 and llm.calls[-1] == "FinalAnswer", f"calls={llm.calls}")

        # (5) answer 실패 -> 안전 응답
        rec = build(multi_agent, conn, bm25, FakeEmbedder(), FakeLLM(fail={"FinalAnswer": parse_err}, first_eval="sufficient")).run(QUESTION, QSET)
        check("5 answer 실패 -> 안전 응답", rec["response_type"] == "abstain" and rec["degraded"] and rec["citations"] == []
              and multi_agent.SAFE_ANSWER in rec["answer"] and "검색된 문서" in rec["answer"], rec["answer"][:70].replace("\n", " "))

        # (6) FatalLLMError는 어느 노드에서든 그대로 전파
        fatal = FatalLLMError("402: credits")
        for node in ("Evaluation", "Feedback", "Improvement", "FinalAnswer"):
            rag = build(multi_agent, conn, bm25, FakeEmbedder(), FakeLLM(fail={node: fatal}))
            e = raises(Exception, lambda: rag.run(QUESTION, QSET))
            check(f"6 {node}의 FatalLLMError 전파", isinstance(e, FatalLLMError), repr(e)[:60])
        rag = build(multi_agent, conn, bm25, FakeEmbedder(fatal), FakeLLM())
        e = raises(Exception, lambda: rag.run(QUESTION, QSET))
        check("6 임베더의 FatalLLMError 전파(BM25로 숨기지 않음)", isinstance(e, FatalLLMError))

        # (7) 정상 경로: 수정 전 코드(G2 이전 커밋 3b8bedc)와 같은 응답·트레이스·호출 수
        orig = load_original()
        # 재검색 경로는 B(문맥 정리)·C(새 근거 없으면 종료)로 의도적으로 달라졌으므로 바로 답변 경로만 비교한다.
        for label, first_eval in (("바로 답변 경로", "sufficient"),):
            llm_new, llm_old = FakeLLM(first_eval=first_eval), FakeLLM(first_eval=first_eval)
            new = build(multi_agent, conn, bm25, FakeEmbedder(), llm_new).run(QUESTION, QSET)
            old = build(orig, conn, bm25, FakeEmbedder(), llm_old).run(QUESTION, QSET)
            new_c, old_c = copy.deepcopy(new), copy.deepcopy(old)
            flags = (new_c.pop("degraded"), new_c.pop("degraded_reasons"))
            gflags = new_c.pop("guardrail_flags")   # GR3이 더한 키(기록만)
            for r in (new_c, old_c):
                r["usage"].pop("elapsed_ms")
            for t in new_c["trace"]:
                t.pop("core_answered", None)   # D가 더한 키(기록용)
                t.pop("sub_queries", None)     # 개선 2(질문 분해)가 더한 키
                t.pop("question_parts", None)  # 개선 3(질문 요소 점검표)이 더한 키
            for r in (new_c, old_c):           # 개선 2의 분해 호출 1회만큼 사용량이 다르다
                r.pop("usage")
            calls_new = [c for c in llm_new.calls if c != "Decomposition"]
            check(f"7 정상 경로 불변 ({label})", new_c == old_c and flags == (False, []) and gflags == [] and calls_new == llm_old.calls,
                  f"calls={llm_new.calls}")
    finally:
        multi_agent.generate_structured = orig_gs
        conn.close()

    # 8. run_rag.check: degraded 응답은 기대 행동과 같아도 실패로 집계한다
    import scripts.run_rag as rr
    case = {"expected_behavior": "abstain_and_redirect", "set": "negative", "expected_source_ids": []}
    rec = {"response_type": "abstain", "citations": [], "delivered_parents": [], "invalid_citations": [], "answer": "x"}
    normal = rr.check(case, dict(rec))
    degraded = rr.check(case, {**rec, "degraded": True})
    check("8 degraded는 점수에서 실패, 정상은 그대로",
          normal["behavior_strict"] and normal["behavior_lenient"] and "degraded" not in normal
          and not degraded["behavior_strict"] and not degraded["behavior_lenient"] and degraded["degraded"])

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 통과" + (f", 실패: {failed}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
