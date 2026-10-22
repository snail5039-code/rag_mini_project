"""(eval/1021-baseline 브랜치의 팀 스크립트를 가져와 이 브랜치의 실행 기록 형식에 맞춘 것. 루브릭은 같다.)

A. 커스텀 LLM Judge: 실행 기록(run_rag.py 결과)의 답변을 골든셋 기준으로 채점한다.

문항당 Judge 호출 1회. 답변 모델(gemini-3.6-flash)과 다른 모델로 채점해 자기 채점 편향을 줄인다.
결과: 06_results/eval/<run_id>__judge.jsonl (문항별), <run_id>__judge.summary.json (집계)

사용:
    python scripts/eval_judge.py --run 20261021_120715__multi_agent__both_golden
    python scripts/eval_judge.py --run <run_id> --cases POS091 NEG041 --no-save
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag import config, llm  # noqa: E402
from rag.basic_rag import doc_base_date  # noqa: E402
from scripts.run_rag import load_cases  # noqa: E402

JUDGE_MODEL = "gemini-3.8-flash"
RUBRIC_VERSION = "judge_v1"
RUN_DIR = config.ROOT / "06_results" / "rag"
OUT_DIR = config.ROOT / "06_results" / "eval"


class ItemCheck(BaseModel):
    item: str = Field(description="must_include 항목 원문")
    met: bool = Field(description="답변이 이 항목을 의미상 충족하면 true")


class Verdict(BaseModel):
    correctness: int = Field(description="0/1/2. 기준 답안·기대 행동의 핵심과 일치하면 2, 일부 누락·부정확이면 1, 틀리면 0")
    must_include: list[ItemCheck] = Field(description="must_include 항목별 충족 여부 (항목이 없으면 빈 목록)")
    must_not_violation: bool = Field(description="must_not_include에 해당하는 내용을 답변이 말하면 true")
    must_not_evidence: str = Field(description="위반이라면 해당 문장, 아니면 빈 문자열")
    faithfulness: int = Field(description="0/1/2. 답변의 사실·수치·조건이 모두 제공된 문맥에 있으면 2, 일부만 없으면 1, 핵심 수치·조건을 지어냈으면 0")
    citation_support: int = Field(description="0/1/2. 인용한 문서가 답변 문장을 실제로 뒷받침하면 2, 일부만이면 1, 아니면 0. 인용이 필요 없는 응답이면 2")
    behavior_appropriate: bool = Field(description="보류·거절·되묻기·정정 문항에서 이유와 확인할 곳을 적절히 안내했으면 true. 일반 답변 문항이면 true")
    reason: str = Field(description="점수의 핵심 이유 2~3문장")


SYSTEM = """당신은 금융 RAG 시스템의 답변을 채점하는 엄격한 평가자입니다.
주어진 질문, 기대 행동, 기준 답안, must_include/must_not_include, 시스템이 받은 문맥, 시스템의 최종 응답을 보고 항목별로 채점하세요.

채점 원칙:
- 기준 답안은 유일한 정답 문장이 아닙니다. 같은 의미면 표현이 달라도 충족으로 봅니다.
- 기대 행동이 보류(abstain)·거절(refuse)·되묻기(clarify)·정정(correct)이면, 그 행동을 하고 이유와 확인할 곳을 안내했는지를 correctness와 behavior_appropriate의 기준으로 봅니다. 문서에 없다고 밝힌 뒤 지어낸 수치를 덧붙이면 감점합니다.
- faithfulness는 제공된 '문맥'만 기준입니다. 문맥에 없는 수치·조건·조항 번호를 말하면 감점합니다. 계산 결과는 문맥의 수치에서 정확히 계산했다면 충실한 것으로 봅니다.
- must_not_include는 답변이 그 내용을 사실로 주장할 때만 위반입니다. 그 내용이 틀렸다고 정정하는 문장은 위반이 아닙니다.
- 인용 번호([문서 N])와 문맥 번호가 일치하는지 보고 citation_support를 채점하세요."""


# 완화 기준 (judge_v2): 질문이 직접 묻는 핵심만 정확성에 반영한다. judge_v1과 나란히 보고하며 대체하지 않는다.
SYSTEM_V2_RULES = """

[judge_v2 완화 기준 — correctness는 아래 기준으로만 매깁니다]
- 2점: 질문이 직접 묻는 핵심 요소에 모두 정확히 답했고, 기대 행동(답변·정정·보류·되묻기·거절)이 맞음.
  부가 설명, 확인 권고·주의 안내, 질문이 직접 묻지 않은 부수 수치·배경이 빠진 것은 감점하지 않습니다.
  must_include 항목 중 이런 부가 항목이 빠진 것은 must_include 충족 여부에는 그대로 표시하되 correctness는 깎지 않습니다.
- 1점: 질문이 직접 묻는 요소 중 일부가 빠졌거나 부정확함.
- 0점: 핵심 내용이 틀렸거나, 기대 행동이 틀렸거나(보류·되묻기해야 할 때 단정하는 등), must_not_include를 사실로 주장함."""

RUBRICS = {"judge_v1": "", "judge_v2": SYSTEM_V2_RULES}


def parent_store() -> dict[str, dict]:
    method = config.BASELINE_EXPERIMENT.split("__")[0]
    path = config.CHUNK_DIR / f"{method}.parents.jsonl"
    return {json.loads(l)["parent_id"]: json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()}


def build_user(case: dict, rec: dict, parents: dict) -> str:
    ctx = []
    for i, p in enumerate(rec["delivered_parents"], 1):
        pc = parents.get(p["parent_id"], {})
        # 시스템이 문서 기준일을 받은 실행(guards)이면 Judge에게도 같은 기준일을 보여 준다
        date = doc_base_date(pc.get("file_name", "")) if rec.get("_with_dates") else None
        date_txt = f" (문서 기준일: {date})" if date else ""
        ctx.append(f"[문서 {i}] {pc.get('file_name', '')} p.{pc.get('page_no', '')}{date_txt}\n{pc.get('content', '(원문 없음)')}")
    cites = [f"{c['file_name']} p.{c['page_no']}" for c in rec["citations"]]
    return (
        f"## 질문\n{case['question']}\n\n"
        f"## 기대 행동\n{case['expected_behavior']} (카테고리: {case['category']})\n\n"
        f"## 기준 답안\n{case['reference_answer']}\n\n"
        f"## must_include\n{json.dumps(case.get('must_include', []), ensure_ascii=False)}\n\n"
        f"## must_not_include\n{json.dumps(case.get('must_not_include', []), ensure_ascii=False)}\n\n"
        f"## 시스템이 받은 문맥\n" + ("\n\n".join(ctx) if ctx else "(없음)") + "\n\n"
        f"## 시스템의 최종 응답\n응답 유형: {rec['response_type']}\n{rec['answer']}\n\n"
        f"## 응답이 인용한 문서\n{json.dumps(cites, ensure_ascii=False)}"
    )


def judge_one(case: dict, rec: dict, parents: dict, rubric: str = "judge_v1") -> dict:
    t0 = time.time()
    verdict, usage = llm.generate_structured(SYSTEM + RUBRICS[rubric], build_user(case, rec, parents), Verdict,
                                             model=JUDGE_MODEL, temperature=0.0)
    items = verdict.must_include
    return {
        "run_id": rec["run_id"], "case_id": rec["case_id"], "golden": rec.get("golden", "provided"), "question_set": rec["question_set"],
        "category": case["category"], "expected_behavior": case["expected_behavior"], "set": case["set"],
        "response_type": rec["response_type"],
        "correctness": verdict.correctness,
        "must_include_coverage": (sum(i.met for i in items) / len(items)) if items else None,
        "must_include_items": [i.model_dump() for i in items],
        "must_not_violation": verdict.must_not_violation, "must_not_evidence": verdict.must_not_evidence,
        "faithfulness": verdict.faithfulness, "citation_support": verdict.citation_support,
        "behavior_appropriate": verdict.behavior_appropriate, "reason": verdict.reason,
        "usage": usage, "seconds": round(time.time() - t0, 1),
    }


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def summarize(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for r in rows:
        for key in ("all", f"golden:{r['golden']}", f"{r['golden']}:set:{r['set']}",
                    f"{r['golden']}:category:{r['category']}", f"{r['golden']}:qset:{r['question_set']}"):
            groups[key].append(r)
    out = {}
    for k, rs in groups.items():
        out[k] = {
            "n": len(rs),
            "correctness": mean([r["correctness"] / 2 for r in rs]),
            "correct_full": mean([r["correctness"] == 2 for r in rs]),
            "must_include_coverage": mean([r["must_include_coverage"] for r in rs]),
            "must_not_violation_rate": mean([r["must_not_violation"] for r in rs]),
            "faithfulness": mean([r["faithfulness"] / 2 for r in rs]),
            "citation_support": mean([r["citation_support"] / 2 for r in rs]),
            "behavior_appropriate": mean([r["behavior_appropriate"] for r in rs]),
            "avg_judge_input_tokens": mean([r["usage"]["input_tokens"] for r in rs]),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run_id (06_results/rag/<run_id>.jsonl)")
    ap.add_argument("--cases", nargs="+")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--rubric", choices=list(RUBRICS), default="judge_v1",
                    help="judge_v1(기준) / judge_v2(완화: 질문이 직접 묻는 핵심만 정확성에 반영)")
    ap.add_argument("--answers-dir", default=str(config.ANSWERS_DIR), help="기준 답안 폴더 (골든셋이면 team_golden_set/03_answers)")
    args = ap.parse_args()

    recs = [json.loads(l) for l in (RUN_DIR / f"{args.run}.jsonl").read_text(encoding="utf-8").splitlines()]
    run_params = json.loads((RUN_DIR / f"{args.run}.summary.json").read_text(encoding="utf-8")).get("params", {})
    for r in recs:
        r["_with_dates"] = bool(run_params.get("guards"))
    ap_dir = Path(args.answers_dir)
    cases = {c["case_id"]: c for c in load_cases(["base", "negative", "life", "add"], ap_dir)}
    recs = [r for r in recs if not args.cases or r["case_id"] in args.cases]
    parents = parent_store()
    rows, errors = [], []

    def work(rec):
        try:
            return judge_one(cases[rec["case_id"]], rec, parents, args.rubric)
        except Exception as e:  # noqa: BLE001
            errors.append((rec["case_id"], repr(e)[:200]))
            return None

    with ThreadPoolExecutor(args.workers) as ex:
        for i, r in enumerate(ex.map(work, recs), 1):
            if r:
                rows.append(r)
            if i % 20 == 0:
                print(f"  {i}/{len(recs)}", flush=True)
    if errors:
        print("오류:", errors[:5], f"(총 {len(errors)}건)")

    summary = summarize(rows)
    for k in ("all", "golden:provided", "golden:team"):
        if k in summary:
            print(k, summary[k])
    if args.no_save:
        for r in rows[:5]:
            print(json.dumps(r, ensure_ascii=False)[:600])
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "__judge" if args.rubric == "judge_v1" else f"__{args.rubric}"
    (OUT_DIR / f"{args.run}{suffix}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    tot_in = sum(r["usage"]["input_tokens"] for r in rows)
    tot_out = sum(r["usage"]["output_tokens"] for r in rows)
    (OUT_DIR / f"{args.run}{suffix}.summary.json").write_text(json.dumps({
        "run_id": args.run, "judge_model": JUDGE_MODEL, "rubric": args.rubric, "temperature": 0.0,
        "n": len(rows), "errors": errors, "total_input_tokens": tot_in, "total_output_tokens": tot_out,
        "summary": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {OUT_DIR / (args.run + suffix + '.jsonl')}  입력 {tot_in:,} / 출력 {tot_out:,} 토큰")


if __name__ == "__main__":
    main()
