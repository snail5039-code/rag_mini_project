"""C-2, C-3: LLM 호출 없이 저장된 결과만으로 다시 집계한다.
C-2: 답할 수 없는 질문(보류·거절·되묻기·정정 외 비답변 문항)을 인용·문맥 지표에서 제외
C-3: 응답 유형을 엄격 / 완화 / answer·correct 통합으로 함께 보고
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_rag import OUT_DIR, allowed_types, load_cases  # noqa: E402

RUNS = {"기본 RAG": "20261021_115125__basic_rag__both_golden", "Multi-Agent": "20261021_120715__multi_agent__both_golden"}
ANS = ("answer", "correct", "ignore_injection_and_answer", "ignore_injection_and_correct")


def jl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines()]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def main():
    cases = {(c["golden"], c["case_id"]): c for c in load_cases(["base", "negative", "life", "add"], ["provided", "team"])}
    out = {}
    for label, run in RUNS.items():
        recs = jl(OUT_DIR / f"{run}.jsonl")
        res = {}
        for grp in ("all", "provided", "team"):
            rs = [r for r in recs if grp == "all" or r["golden"] == grp]
            answerable = [r for r in rs if cases[(r["golden"], r["case_id"])]["expected_behavior"].startswith(ANS)]
            merged_ok = []
            for r in rs:
                allowed = allowed_types(cases[(r["golden"], r["case_id"])]["expected_behavior"])
                is_ans = cases[(r["golden"], r["case_id"])]["expected_behavior"].startswith(ANS)
                merged_ok.append(r["response_type"] in allowed if not is_ans else r["response_type"] in ("answer", "correct"))
            res[grp] = {
                "n": len(rs), "n_answerable": len(answerable), "n_non_answer": len(rs) - len(answerable),
                "citation_hit_all": mean([r["checks"].get("citation_hit") for r in rs]),
                "citation_hit_answerable": mean([r["checks"].get("citation_hit") for r in answerable]),
                "citation_recall_all": mean([r["checks"].get("citation_recall") for r in rs]),
                "citation_recall_answerable": mean([r["checks"].get("citation_recall") for r in answerable]),
                "context_recall_all": mean([r["checks"].get("context_recall") for r in rs]),
                "context_recall_answerable": mean([r["checks"].get("context_recall") for r in answerable]),
                "behavior_strict": mean([r["checks"]["behavior_strict"] for r in rs]),
                "behavior_lenient": mean([r["checks"]["behavior_lenient"] for r in rs]),
                "behavior_merged": mean(merged_ok),
            }
        out[label] = res
    (OUT_DIR / "rescore_nonllm.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for label, res in out.items():
        for grp, v in res.items():
            print(label, grp, v)


if __name__ == "__main__":
    main()
