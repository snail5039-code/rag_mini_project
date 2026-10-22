"""A~D 수정 전후 비교: 여러 실행의 지표 평균·범위와 문항별 변화.

    python scripts/compare_fixes.py --before 20261021_120715__multi_agent__both_golden ... \
                                    --after <run_id> ... [--label multi]
결과: 06_results/eval/agent_fixes_1022__<label>.json
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_rag import OUT_DIR  # noqa: E402

EVAL = OUT_DIR.parent / "eval"


def jl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines()]


def metrics(run_id: str, cls: dict) -> tuple[dict, dict, dict]:
    rr = {(x["golden"], x["case_id"]): x for x in jl(OUT_DIR / f"{run_id}.jsonl")}
    jj = {(x["golden"], x["case_id"]): x for x in jl(EVAL / f"{run_id}__judge.jsonl")}

    def adj(k):   # 핵심 항목 기준 보정 만점 (variance.py와 같은 정의)
        j = jj[k]
        lv = {i["item"]: i["level"] for i in cls.get(f"{k[0]}:{k[1]}", [])}
        core = [i for i in j["must_include_items"] if lv.get(i["item"], "core") == "core"]
        return j["correctness"] == 2 or (j["correctness"] == 1 and bool(core) and all(i["met"] for i in core)
                                         and not j["must_not_violation"])

    def m(f, ks):
        return sum(f(k) for k in ks) / len(ks)

    out = {}
    for g, ks in (("all", list(rr)), ("provided", [k for k in rr if k[0] == "provided"]),
                  ("team", [k for k in rr if k[0] == "team"])):
        out[g] = {
            "behavior_strict": m(lambda k: rr[k]["checks"]["behavior_strict"], ks),
            "behavior_lenient": m(lambda k: rr[k]["checks"]["behavior_lenient"], ks),
            "judge_correctness": m(lambda k: jj[k]["correctness"] / 2, ks),
            "judge_full": m(lambda k: jj[k]["correctness"] == 2, ks),
            "judge_full_core_adjusted": m(adj, ks),
            "must_include_coverage": sum(jj[k]["must_include_coverage"] or 0 for k in ks) / len(ks),
            "must_not_violation": m(lambda k: jj[k]["must_not_violation"], ks),
            "faithfulness": m(lambda k: jj[k]["faithfulness"] / 2, ks),
            "context_recall": m(lambda k: rr[k]["checks"].get("context_recall") or 0, ks),
            "avg_tokens": m(lambda k: rr[k]["usage"]["input_tokens"] + rr[k]["usage"]["output_tokens"], ks),
            "avg_seconds": m(lambda k: rr[k]["usage"]["elapsed_ms"] / 1000, ks),
            "re_search_rate": m(lambda k: rr[k].get("search_rounds", 1) > 1, ks),
            "errors": sum(1 for k in ks if rr[k].get("error")),
        }
    return out, rr, jj


def agg(per: list[dict]) -> dict:
    res = {}
    for g in per[0]:
        res[g] = {}
        for k in per[0][g]:
            xs = [p[g][k] for p in per]
            res[g][k] = {"runs": [round(x, 4) for x in xs], "mean": round(st.mean(xs), 4),
                         "range": round(max(xs) - min(xs), 4)}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", nargs="+", required=True)
    ap.add_argument("--after", nargs="+", required=True)
    ap.add_argument("--label", default="multi")
    args = ap.parse_args()
    cls = json.loads((EVAL / "must_include_core.json").read_text(encoding="utf-8"))["items"]
    before = [metrics(r, cls) for r in args.before]
    after = [metrics(r, cls) for r in args.after]
    b, a = agg([x[0] for x in before]), agg([x[0] for x in after])

    # 문항별: 실행 과반에서 통과(엄격·Judge 만점)했는지로 안정적 변화만 센다
    def major(runs, f, k):
        return sum(f(rr, jj, k) for _, rr, jj in runs) * 2 > len(runs)
    strict = lambda rr, jj, k: rr[k]["checks"]["behavior_strict"]   # noqa: E731
    full = lambda rr, jj, k: jj[k]["correctness"] == 2   # noqa: E731
    keys = list(before[0][1])
    flips = {}
    for name, f in (("behavior_strict", strict), ("judge_full", full)):
        fixed = [k[1] for k in keys if not major(before, f, k) and major(after, f, k)]
        broke = [k[1] for k in keys if major(before, f, k) and not major(after, f, k)]
        flips[name] = {"fixed": fixed, "broken": broke}

    summary = {"before": args.before, "after": args.after, "before_stats": b, "after_stats": a, "case_flips": flips}
    (EVAL / f"agent_fixes_1022__{args.label}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                                              encoding="utf-8")
    for g in ("all", "provided", "team"):
        print(f"[{g}]  지표: 수정 전 평균(범위) -> 수정 후 평균(범위)")
        for k in b[g]:
            print(f"  {k:26s} {b[g][k]['mean']:>10} ({b[g][k]['range']}) -> {a[g][k]['mean']:>10} ({a[g][k]['range']})")
    for name, v in flips.items():
        print(f"{name}: 고침 {len(v['fixed'])} {v['fixed']}\n{' ' * len(name)}  나빠짐 {len(v['broken'])} {v['broken']}")


if __name__ == "__main__":
    main()
