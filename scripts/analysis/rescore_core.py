"""C-1 재채점: 저장된 Judge 결과의 항목별 충족 여부(must_include_items)를 핵심/부가 분류로 다시 집계한다. LLM 호출 없음.

    python scripts/analysis/rescore_core.py [--runs 라벨=run_id ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EVAL = ROOT / "06_results" / "eval"
RUNS = {"기본 RAG": "20261021_115125__basic_rag__both_golden", "Multi-Agent": "20261021_120715__multi_agent__both_golden"}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+")
    ap.add_argument("--out", default="rescore_core.json")
    args = ap.parse_args()
    runs = dict(a.split("=", 1) for a in args.runs) if args.runs else RUNS
    cls = json.loads((EVAL / "must_include_core.json").read_text(encoding="utf-8"))["items"]
    out = {}
    for label, run in runs.items():
        judge = [json.loads(l) for l in (EVAL / f"{run}__judge.jsonl").read_text(encoding="utf-8").splitlines()]
        rows = []
        for j in judge:
            level = {i["item"]: i["level"] for i in cls.get(f"{j['golden']}:{j['case_id']}", [])}
            core = [i for i in j["must_include_items"] if level.get(i["item"], "core") == "core"]
            extra = [i for i in j["must_include_items"] if level.get(i["item"], "core") == "extra"]
            core_all = all(i["met"] for i in core)
            rows.append({
                "golden": j["golden"], "set": j["set"], "correctness": j["correctness"],
                "all_met": all(i["met"] for i in j["must_include_items"]) if j["must_include_items"] else None,
                "core_all_met": core_all if core else None,
                "core_cov": mean([i["met"] for i in core]), "extra_cov": mean([i["met"] for i in extra]),
                "n_core": len(core), "n_extra": len(extra), "violation": j["must_not_violation"],
                "adj_full": j["correctness"] == 2 or (j["correctness"] == 1 and (core_all if core else False) and not j["must_not_violation"]),
            })
        res = {}
        for grp, rs in (("all", rows), ("provided", [r for r in rows if r["golden"] == "provided"]),
                        ("team", [r for r in rows if r["golden"] == "team"]),
                        ("positive", [r for r in rows if r["set"] == "positive"]),
                        ("negative", [r for r in rows if r["set"] == "negative"])):
            res[grp] = {
                "n": len(rs),
                "judge_full_original": mean([r["correctness"] == 2 for r in rs]),
                "judge_full_adjusted": mean([r["adj_full"] for r in rs]),
                "must_include_all_met": mean([r["all_met"] for r in rs]),
                "core_all_met": mean([r["core_all_met"] for r in rs]),
                "core_coverage": mean([r["core_cov"] for r in rs]),
                "extra_coverage": mean([r["extra_cov"] for r in rs]),
                "items_core": sum(r["n_core"] for r in rs), "items_extra": sum(r["n_extra"] for r in rs),
                "demoted_by_extra_only": sum(1 for r in rs if r["correctness"] < 2 and r["adj_full"]),
            }
        out[label] = res
    (EVAL / args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for label, res in out.items():
        for grp in ("all", "provided", "team"):
            print(label, grp, res[grp])


if __name__ == "__main__":
    main()
