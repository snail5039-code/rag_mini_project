"""부분 집합(subset150.json)에서 기준선 3회 평균과 새 실행을 비교한다. LLM 호출 없음.

    python scripts/analysis/compare_subset.py --new <run_id> --name p3
출력: 06_results/eval/<name>_subset150_compare.json, 화면에 표
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.analysis.compare_runs import EVAL, load, mean, metrics  # noqa: E402

BASE_RUNS = ["20261021_120715__multi_agent__both_golden", "20261021_165034__multi_agent__both_golden",
             "20261021_165515__multi_agent__both_golden"]
COLS = ["behavior_strict", "behavior_lenient", "judge_correctness", "judge_correct_full", "must_include_coverage",
        "must_not_violation", "faithfulness", "citation_support", "context_recall", "citation_hit", "avg_tokens",
        "avg_ms", "re_search_rate"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()
    sub = json.loads((EVAL / "subset150.json").read_text(encoding="utf-8"))
    ids = set(sub["case_ids"])
    base = [load(r) for r in BASE_RUNS]
    new, newj = load(args.new)
    keys = sorted(k for k in new if k[1] in ids and all(k in b[0] for b in base))
    groups = {"all": keys, "provided": [k for k in keys if k[0] == "provided"], "team": [k for k in keys if k[0] == "team"]}

    result = {"new": args.new, "base_runs": BASE_RUNS, "n": len(keys), "groups": {}}
    for g, ks in groups.items():
        per_run = [metrics(b[0], b[1], ks) for b in base]
        new_m = metrics(new, newj, ks)
        stat = {}
        for c in COLS:
            vals = [m[c] for m in per_run if m.get(c) is not None]
            if vals:
                stat[c] = {"base_mean": round(sum(vals) / len(vals), 4), "base_min": min(vals), "base_max": max(vals),
                           "new": new_m.get(c)}
        result["groups"][g] = {"n": len(ks), "stats": stat, "base_runs": per_run, "new": new_m}

    # 문항 단위: 기준선 3회 중 과반이 실패였는데 새 실행에서 통과(얻음) / 그 반대(잃음)
    flips = {"lenient_gained": [], "lenient_lost": [], "strict_gained": [], "strict_lost": [], "judge_up": [], "judge_down": []}
    for k in keys:
        lb = sum(bool(b[0][k]["checks"]["behavior_lenient"]) for b in base)
        sb = sum(bool(b[0][k]["checks"]["behavior_strict"]) for b in base)
        ln, sn = bool(new[k]["checks"]["behavior_lenient"]), bool(new[k]["checks"]["behavior_strict"])
        if ln and lb <= 1:
            flips["lenient_gained"].append(k[1])
        if not ln and lb >= 2:
            flips["lenient_lost"].append(k[1])
        if sn and sb <= 1:
            flips["strict_gained"].append(k[1])
        if not sn and sb >= 2:
            flips["strict_lost"].append(k[1])
        jb = mean([b[1][k]["correctness"] for b in base if k in b[1]])
        if k in newj and jb is not None:
            if newj[k]["correctness"] > jb + 0.5:
                flips["judge_up"].append(k[1])
            elif newj[k]["correctness"] < jb - 0.5:
                flips["judge_down"].append(k[1])
    result["flips"] = flips

    # 평가 판정: 답할 수 있는 문항(answer/correct 기대)에서 out_of_scope·insufficient 판정 횟수
    fa = {r["case_id"]: r["expected_behavior"]
          for r in json.loads((EVAL / "failure_analysis.json").read_text(encoding="utf-8"))["Multi-Agent"]}

    def exp_answerable(r):
        return fa[r["case_id"]].startswith(("answer", "correct"))

    result["decisions"] = {}
    for label, recs_list in (("base_mean", [b[0] for b in base]), ("new", [new])):
        oos = []
        for recs in recs_list:
            oos.append(sum(1 for k in keys if exp_answerable(recs[k]) and recs[k]["evaluation"]["decision"] == "out_of_scope"))
        result["decisions"][label] = {"answerable_judged_out_of_scope": oos, "n_answerable": sum(1 for k in keys if exp_answerable(new[k]))}

    (EVAL / f"{args.name}_subset150_compare.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    for g in ("all", "provided", "team"):
        print(f"\n[{g}] n={result['groups'][g]['n']}   (기준선 3회 평균 [최소~최대] -> 새 실행)")
        for c, s in result["groups"][g]["stats"].items():
            if s["new"] is not None:
                print(f"  {c:22s} {s['base_mean']:>9} [{s['base_min']}~{s['base_max']}] -> {s['new']:>9}  ({s['new'] - s['base_mean']:+.3f})")
    print("\n문항 변화:", {k: len(v) for k, v in flips.items()})
    for k, v in flips.items():
        print(" ", k, v)
    print("\n판정:", json.dumps(result["decisions"], ensure_ascii=False))


if __name__ == "__main__":
    main()
