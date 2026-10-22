"""G2 저하 모드 25문항을 같은 문항의 기본 RAG, 정상 Multi-Agent(기준선 3회 평균)와 비교한다. LLM 호출 없음.

    python scripts/analysis/compare_degraded.py --run <run_id>
degraded 응답은 run_rag.check에서 실패로 집계되므로, 여기서는 응답 유형으로 행동 점수를 다시 계산한다.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.analysis.compare_runs import EVAL, RAG, jl  # noqa: E402
import scripts.run_rag as rr  # noqa: E402

BASIC = "20261021_115125__basic_rag__both_golden"
MA = ["20261021_120715__multi_agent__both_golden", "20261021_165034__multi_agent__both_golden",
      "20261021_165515__multi_agent__both_golden"]


def mean(xs):
    xs = list(xs)
    return round(sum(xs) / len(xs), 3) if xs else None


def load(run):
    recs = {(r["golden"], r["case_id"]): r for r in jl(RAG / f"{run}.jsonl")}
    jp = EVAL / f"{run}__judge.jsonl"
    judge = {(j["golden"], j["case_id"]): j for j in jl(jp)} if jp.exists() else {}
    return recs, judge


def behavior(recs, keys, cases):
    """응답 유형만으로 엄격/완화 점수를 계산(degraded 플래그 무시)."""
    s = l = 0
    for k in keys:
        allowed = rr.allowed_types(cases[k]["expected_behavior"])
        s += recs[k]["response_type"] == allowed[0]
        l += recs[k]["response_type"] in allowed
    return round(s / len(keys), 3), round(l / len(keys), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    deg, dj = load(args.run)
    keys = sorted(deg)
    cases = {(c["golden"], c["case_id"]): c for c in rr.load_cases(list(rr.FILES), ["provided", "team"])}
    basic, bj = load(BASIC)
    mas = [load(r) for r in MA]

    out = {"run": args.run, "n": len(keys), "degraded_records": sum(bool(deg[k].get("degraded")) for k in keys)}
    rows = {}
    ds, dl = behavior(deg, keys, cases)
    rows["저하 모드(평가 강제 실패)"] = {"strict": ds, "lenient": dl,
                                  "judge": mean(dj[k]["correctness"] / 2 for k in keys),
                                  "full": mean(dj[k]["correctness"] == 2 for k in keys),
                                  "tokens": round(sum(deg[k]["usage"]["input_tokens"] + deg[k]["usage"]["output_tokens"] for k in keys) / len(keys)),
                                  "faith": mean(dj[k]["faithfulness"] / 2 for k in keys)}
    bs, bl = behavior(basic, keys, cases)
    rows["기본 RAG"] = {"strict": bs, "lenient": bl, "judge": mean(bj[k]["correctness"] / 2 for k in keys),
                      "full": mean(bj[k]["correctness"] == 2 for k in keys),
                      "tokens": round(sum(basic[k]["usage"]["input_tokens"] + basic[k]["usage"]["output_tokens"] for k in keys) / len(keys)),
                      "faith": mean(bj[k]["faithfulness"] / 2 for k in keys)}
    ms = [behavior(r, keys, cases) for r, _ in mas]
    rows["정상 Multi-Agent(3회 평균)"] = {
        "strict": mean(m[0] for m in ms), "lenient": mean(m[1] for m in ms),
        "judge": mean(j[k]["correctness"] / 2 for _, j in mas for k in keys),
        "full": mean(j[k]["correctness"] == 2 for _, j in mas for k in keys),
        "tokens": round(sum(r[k]["usage"]["input_tokens"] + r[k]["usage"]["output_tokens"] for r, _ in mas for k in keys) / (len(keys) * 3)),
        "faith": mean(j[k]["faithfulness"] / 2 for _, j in mas for k in keys)}
    out["rows"] = rows
    out["response_types"] = {name: {t: sum(r[k]["response_type"] == t for k in keys) for t in ("answer", "correct", "clarify", "abstain", "refuse")}
                             for name, r in (("저하", deg), ("기본", basic), ("정상MA(120715)", mas[0][0]))}
    (EVAL / "g2_degraded_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
