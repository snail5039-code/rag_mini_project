"""A~D 수정 테스트. 가짜 LLM·임베더를 쓰므로 API 비용이 없다(검색은 로컬 DB를 읽기만 한다).

    PYTHONIOENCODING=utf-8 python scripts/test_agent_fixes.py
(A) 범위를 좁힌 벡터 검색이 k개를 채워 돌려줌  (B) 재검색 전에 평가가 고른 문서만 남김
(C) 새 parent가 0개면 평가 없이 바로 답변  (D) 부적절·모호 판정의 응답 유형을 코드가 확정(core_answered는 기록만)
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag import config, db, multi_agent  # noqa: E402
from rag.basic_rag import scope_files  # noqa: E402
from rag.retrieval import BM25Retriever, vector_search  # noqa: E402

QUESTION, QSET = "신용거래 청약철회 기간은 며칠인가요?", "base"
VEC = list(np.random.RandomState(0).rand(config.EMBEDDING_DIM))


class FakeEmbedder:
    def embed_query(self, text):
        return VEC


class FakeLLM:
    """evals: 라운드별 평가 판정 목록. improve_queries: 개선 Agent가 낼 검색어."""

    def __init__(self, evals, improve_queries, final_type="answer", core=True, relevant=(1,), sub_queries=()):
        self.evals, self.improve_queries, self.sub_queries = list(evals), improve_queries, list(sub_queries)
        self.final_type, self.core, self.relevant, self.calls = final_type, core, list(relevant), []

    def __call__(self, system, user, schema, *a, **k):
        name = schema.__name__
        self.calls.append(name)
        usage = {"model_calls": 1, "input_tokens": 100, "output_tokens": 10}
        if name == "Evaluation":
            d = self.evals.pop(0) if self.evals else "sufficient"
            return schema(decision=d, relevant_docs=self.relevant, covered=["a"],
                          missing=["b"] if d == "insufficient" else [], reason="r"), usage
        if name == "Decomposition":
            return schema(sub_queries=self.sub_queries), usage
        if name == "Feedback":
            return schema(causes=["c"], targets=["t"]), usage
        if name == "Improvement":
            return schema(queries=self.improve_queries, retriever="vector"), usage
        if name == "FinalAnswer":
            return schema(question_parts=[], response_type=self.final_type, answer="답", citations=[1],
                          core_answered=self.core, reason="r"), usage
        raise AssertionError(name)


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def run(conn, bm25, llm):
    multi_agent.generate_structured = llm
    return multi_agent.MultiAgentRAG(conn, FakeEmbedder(), bm25).run(QUESTION, QSET)


def main():
    conn = db.connect()
    exp = config.BASELINE_EXPERIMENT
    bm25 = BM25Retriever(conn, exp)
    orig_gs = multi_agent.generate_structured
    try:
        # (A) 추가 PDF 범위(6개 파일)에서 무작위 청크 100개를 질의로 써도 항상 8개를 채운다
        rows = conn.execute("SELECT embedding FROM chunks WHERE experiment_id = %s ORDER BY random() LIMIT 100",
                            (exp,)).fetchall()
        files = scope_files(conn, exp, "add")
        counts = [len(vector_search(conn, r[0].to_numpy(), exp, 8, files)) for r in rows]
        check("A 범위 검색이 k개를 채움", min(counts) == 8, f"8개 미만 {sum(c < 8 for c in counts)}/100")
        check("A 세션의 인덱스 설정은 그대로", conn.execute("SHOW enable_indexscan").fetchone()[0] == "on")

        # (B) 재검색 전 relevant_docs=[1]만 남기고 새 문서를 받는다
        llm = FakeLLM(evals=["insufficient", "sufficient"], improve_queries=["청약 철회 약관 조항"])
        rec = run(conn, bm25, llm)
        s = [t for t in rec["trace"] if t["step"] == "search"]
        first = s[0]["context_parents"]
        check("B 재검색 전 문맥 정리", len(s) == 2 and s[1].get("pruned_parents") == first - 1
              and s[1]["context_parents"] == 1 + s[1]["new_parents"],
              f"1차 {first}개 -> 정리 {s[1].get('pruned_parents')}개, 2차 문맥 {s[1]['context_parents']}")
        check("B 버린 문서는 다시 들어오지 않음",
              len({p["parent_id"] for p in rec["delivered_parents"]}) == len(rec["delivered_parents"]))

        # (C) 개선 검색어가 이미 쓴 질문뿐이면 새 parent 0개 -> 평가 없이 답변
        llm = FakeLLM(evals=["insufficient"], improve_queries=[QUESTION])
        rec = run(conn, bm25, llm)
        check("C 새 근거 없으면 바로 답변", rec["stop_reason"] == "no_new_evidence"
              and llm.calls.count("Evaluation") == 1 and llm.calls[-1] == "FinalAnswer", f"calls={llm.calls}")

        # (개선 2) 하위 질문 검색어를 첫 검색에 함께 쓰고, 검색어별 결과를 번갈아 담는다
        long_q = QUESTION + " 그리고 중도에 해지하면 환급금은 어떻게 계산되고 예금자보호는 얼마까지 되는지, 해지 절차는 어떻게 되는지도 알려 주세요."
        llm = FakeLLM(evals=["sufficient"], improve_queries=[], sub_queries=["예금자보호 한도", long_q])
        multi_agent.generate_structured = llm
        rec = multi_agent.MultiAgentRAG(conn, FakeEmbedder(), bm25).run(long_q, QSET)
        s0 = [t for t in rec["trace"] if t["step"] == "search"][0]
        orch = rec["trace"][0]
        check("2 분해 검색어 사용(원 질문 중복 제외)", s0["queries"] == [long_q, "예금자보호 한도"]
              and orch.get("sub_queries") == ["예금자보호 한도"] and llm.calls[0] == "Decomposition", str(s0["queries"]))
        check("2 문맥 상한 유지", s0["context_parents"] <= multi_agent.MAX_CONTEXT_PARENTS, f"{s0['context_parents']}")
        llm = FakeLLM(evals=["sufficient"], improve_queries=[])
        llm.sub_queries = None   # 스키마 검증 실패 -> 원 질문만으로 검색
        multi_agent.generate_structured = llm
        rec = multi_agent.MultiAgentRAG(conn, FakeEmbedder(), bm25).run(long_q, QSET)
        check("2 분해 실패 시 원 질문만 검색", rec["trace"][0].get("decompose_failed")
              and [t for t in rec["trace"] if t["step"] == "search"][0]["queries"] == [long_q] and not rec["degraded"])
        llm = FakeLLM(evals=["sufficient"], improve_queries=[], sub_queries=["예금자보호 한도"])
        rec = run(conn, bm25, llm)   # 짧은 질문
        check("2 짧은 질문은 분해 호출 없음", rec["trace"][0].get("decompose_skipped") and "Decomposition" not in llm.calls,
              f"calls={llm.calls}")

        # (D) 응답 유형 확정
        cases = [
            ("out_of_scope", "answer", True, "answer"),
            ("out_of_scope", "answer", False, "answer"),
            ("inappropriate", "answer", True, "refuse"),
            ("ambiguous", "answer", True, "clarify"),
            ("sufficient", "answer", False, "answer"),
            ("insufficient", "correct", False, "correct"),
            ("sufficient", "answer", True, "answer"),
            ("sufficient", "clarify", False, "clarify"),
        ]
        for decision, typ, core, want in cases:
            got = multi_agent.MultiAgentRAG.decide_type({"decision": decision}, {"response_type": typ, "core_answered": core})
            check(f"D {decision}+{typ}(core={core}) -> {want}", got == want, f"got={got}")
        got = multi_agent.MultiAgentRAG.decide_type({"decision": "ambiguous", "degraded": True},
                                                    {"response_type": "answer", "core_answered": True})
        check("D 평가가 대체 경로(degraded)면 강제하지 않음", got == "answer")
        llm = FakeLLM(evals=["ambiguous"], improve_queries=[])
        rec = run(conn, bm25, llm)
        ans = [t for t in rec["trace"] if t["step"] == "answer"][0]
        check("D 그래프에서 유형 뒤집기 기록", rec["response_type"] == "clarify"
              and ans.get("type_override") == "answer->clarify", str(ans))
    finally:
        multi_agent.generate_structured = orig_gs
        conn.close()

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 통과" + (f", 실패: {failed}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
