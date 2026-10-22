"""수정 전후 비교 리포트. 기준 실행과 새 실행(둘 다 같은 270문항)을 문항 단위로 비교한다.

    python scripts/compare_runs.py --base <run_id> --new <run_id> --name p2 [--judge]
출력: 06_results/eval/<name>_compare.json (원자료), 화면에 표
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAG, EVAL = ROOT / "06_results" / "rag", ROOT / "06_results" / "eval"


def jl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines()]


def load(run):
    recs = {(r["golden"], r["case_id"]): r for r in jl(RAG / f"{run}.jsonl")}
    judge = {(j["golden"], j["case_id"]): j for j in jl(EVAL / f"{run}__judge.jsonl")} if (EVAL / f"{run}__judge.jsonl").exists() else {}
    return recs, judge


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def metrics(recs, judge, keys):
    rs = [recs[k] for k in keys]
    out = {
        "n": len(keys),
        "behavior_strict": mean([r["checks"]["behavior_strict"] for r in rs]),
        "behavior_lenient": mean([r["checks"]["behavior_lenient"] for r in rs]),
        "context_recall": mean([r["checks"].get("context_recall") for r in rs]),
        "citation_hit": mean([r["checks"].get("citation_hit") for r in rs]),
        "avg_tokens": round(sum(r["usage"]["input_tokens"] + r["usage"]["output_tokens"] for r in rs) / len(rs)),
        "total_tokens": sum(r["usage"]["input_tokens"] + r["usage"]["output_tokens"] for r in rs),
        "avg_ms": round(sum(r["usage"]["elapsed_ms"] for r in rs) / len(rs)),
        "avg_model_calls": round(sum(r["usage"]["model_calls"] for r in rs) / len(rs), 2),
        "re_search_rate": mean([r["search_rounds"] > 1 for r in rs]),
    }
    if judge:
        js = [judge[k] for k in keys if k in judge]
        out.update({
            "judge_correctness": mean([j["correctness"] / 2 for j in js]),
            "judge_correct_full": mean([j["correctness"] == 2 for j in js]),
            "must_include_coverage": mean([j["must_include_coverage"] for j in js]),
            "must_not_violation": mean([j["must_not_violation"] for j in js]),
            "faithfulness": mean([j["faithfulness"] / 2 for j in js]),
            "citation_support": mean([j["citation_support"] / 2 for j in js]),
            "behavior_appropriate": mean([j["behavior_appropriate"] for j in js]),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()
    b, bj = load(args.base)
    n, nj = load(args.new)
    keys = sorted(set(b) & set(n))
    groups = {"all": keys, "provided": [k for k in keys if k[0] == "provided"], "team": [k for k in keys if k[0] == "team"]}
    for g in ("provided", "team"):
        for qs in ("base", "negative", "life", "add"):
            groups[f"{g}:{qs}"] = [k for k in keys if k[0] == g and b[k]["question_set"] == qs]
    result = {"base": args.base, "new": args.new, "groups": {}, "flips": {}}
    for g, ks in groups.items():
        if ks:
            result["groups"][g] = {"base": metrics(b, bj, ks), "new": metrics(n, nj, ks)}

    flips = {"strict_gained": [], "strict_lost": [], "lenient_gained": [], "lenient_lost": [],
             "type_changed": [], "judge_up": [], "judge_down": [], "judge_same": 0}
    for k in keys:
        bc, nc = b[k]["checks"], n[k]["checks"]
        if nc["behavior_strict"] and not bc["behavior_strict"]:
            flips["strict_gained"].append(k[1])
        if bc["behavior_strict"] and not nc["behavior_strict"]:
            flips["strict_lost"].append(k[1])
        if nc["behavior_lenient"] and not bc["behavior_lenient"]:
            flips["lenient_gained"].append(k[1])
        if bc["behavior_lenient"] and not nc["behavior_lenient"]:
            flips["lenient_lost"].append(k[1])
        if b[k]["response_type"] != n[k]["response_type"]:
            flips["type_changed"].append({"case": k[1], "from": b[k]["response_type"], "to": n[k]["response_type"]})
        if k in bj and k in nj:
            d = nj[k]["correctness"] - bj[k]["correctness"]
            if d > 0:
                flips["judge_up"].append(k[1])
            elif d < 0:
                flips["judge_down"].append(k[1])
            if d == 0:
                flips["judge_same"] += 1
    result["flips"] = flips
    (EVAL / f"{args.name}_compare.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    cols = ["behavior_strict", "behavior_lenient", "judge_correctness", "judge_correct_full", "must_include_coverage",
            "must_not_violation", "faithfulness", "citation_support", "context_recall", "citation_hit", "avg_tokens", "avg_ms", "re_search_rate"]
    for g in ("all", "provided", "team"):
        print(f"\n[{g}] n={result['groups'][g]['base']['n']}")
        for c in cols:
            bv, nv = result["groups"][g]["base"].get(c), result["groups"][g]["new"].get(c)
            if bv is not None and nv is not None:
                print(f"  {c:24s} {bv:>10} -> {nv:>10}  ({nv - bv:+.3f})")
    print("\n문항 변화:", {k: (len(v) if isinstance(v, list) else v) for k, v in flips.items()})
    for k in ("strict_gained", "strict_lost", "lenient_lost", "type_changed"):
        print(" ", k, flips[k])


if __name__ == "__main__":
    main()
