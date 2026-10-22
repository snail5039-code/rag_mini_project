"""B: 같은 코드·설정으로 반복 실행한 결과의 변동 폭. 사용: python scripts/analysis/variance.py (실행 ID는 아래 RUNS)"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.common import jl  # noqa: E402
from scripts.run_rag import OUT_DIR, load_cases  # noqa: E402

EVAL = OUT_DIR.parent / "eval"
RUNS = ["20261021_120715", "20261021_165034", "20261021_165515"]
SUF = "__multi_agent__both_golden"


def main():
    cls = json.loads((EVAL / "must_include_core.json").read_text(encoding="utf-8"))["items"]
    cases = {(c["golden"], c["case_id"]): c for c in load_cases(["base", "negative", "life", "add"], ["provided", "team"])}
    per, recs, judges = {}, {}, {}
    for r in RUNS:
        rr = {(x["golden"], x["case_id"]): x for x in jl(OUT_DIR / f"{r}{SUF}.jsonl")}
        jj = {(x["golden"], x["case_id"]): x for x in jl(EVAL / f"{r}{SUF}__judge.jsonl")}
        recs[r], judges[r] = rr, jj
        def adj(k):
            j = jj[k]
            lv = {i["item"]: i["level"] for i in cls.get(f"{k[0]}:{k[1]}", [])}
            core = [i for i in j["must_include_items"] if lv.get(i["item"], "core") == "core"]
            return j["correctness"] == 2 or (j["correctness"] == 1 and bool(core) and all(i["met"] for i in core) and not j["must_not_violation"])
        def m(f, ks): return sum(f(k) for k in ks) / len(ks)
        out = {}
        for g, ks in (("all", list(rr)), ("provided", [k for k in rr if k[0] == "provided"]), ("team", [k for k in rr if k[0] == "team"])):
            out[g] = {
                "behavior_strict": m(lambda k: rr[k]["checks"]["behavior_strict"], ks),
                "behavior_lenient": m(lambda k: rr[k]["checks"]["behavior_lenient"], ks),
                "judge_correctness": m(lambda k: jj[k]["correctness"] / 2, ks),
                "judge_full": m(lambda k: jj[k]["correctness"] == 2, ks),
                "judge_full_core_adjusted": m(adj, ks),
                "must_include_coverage": sum(jj[k]["must_include_coverage"] or 0 for k in ks) / len(ks),
                "must_not_violation": m(lambda k: jj[k]["must_not_violation"], ks),
                "faithfulness": m(lambda k: jj[k]["faithfulness"] / 2, ks),
                "citation_support": m(lambda k: jj[k]["citation_support"] / 2, ks),
                "avg_tokens": sum(rr[k]["usage"]["input_tokens"] + rr[k]["usage"]["output_tokens"] for k in ks) / len(ks),
                "re_search_rate": m(lambda k: rr[k]["search_rounds"] > 1, ks),
            }
        per[r] = out
    stats = {}
    for g in ("all", "provided", "team"):
        stats[g] = {}
        for k in per[RUNS[0]][g]:
            xs = [per[r][g][k] for r in RUNS]
            stats[g][k] = {"runs": [round(x, 4) for x in xs], "mean": round(st.mean(xs), 4), "min": round(min(xs), 4),
                           "max": round(max(xs), 4), "range": round(max(xs) - min(xs), 4), "sd": round(st.stdev(xs), 4)}
    keys = list(recs[RUNS[0]])
    types = {k: [recs[r][k]["response_type"] for r in RUNS] for k in keys}
    judge_c = {k: [judges[r][k]["correctness"] for r in RUNS] for k in keys}
    unstable_type = [k for k in keys if len(set(types[k])) > 1]
    label_only = [k for k in unstable_type if set(types[k]) <= {"answer", "correct"}]
    behavior_unstable = [k for k in unstable_type if k not in label_only]
    corr_unstable = [k for k in keys if len(set(judge_c[k])) > 1]
    lenient_unstable = [k for k in keys if len({recs[r][k]["checks"]["behavior_lenient"] for r in RUNS}) > 1]
    summary = {
        "runs": RUNS, "stats": stats,
        "case_stability": {
            "n": len(keys), "response_type_identical": len(keys) - len(unstable_type), "type_unstable": len(unstable_type),
            "label_only_answer_correct": len(label_only), "behavior_unstable": len(behavior_unstable),
            "judge_correctness_unstable": len(corr_unstable), "lenient_pass_unstable": len(lenient_unstable)},
        "behavior_unstable_cases": [f"{k[1]}:{'/'.join(types[k])}" for k in behavior_unstable],
    }
    (EVAL / "variance_baseline.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for g in ("all", "provided", "team"):
        print(f"[{g}]")
        for k, v in stats[g].items():
            print(f"  {k:26s} {v['runs']}  mean {v['mean']}  range {v['range']}  sd {v['sd']}")
    print(summary["case_stability"])
    print(summary["behavior_unstable_cases"])


if __name__ == "__main__":
    main()
