"""오류로 실패한 문항만 다시 실행한 결과를 원래 실행 기록에 합친다 (같은 코드·설정으로 다시 돌린 것이어야 한다).

    python scripts/merge_retry.py --run <원래 run_id> --retry <재실행 run_id>
원래 run_id는 유지하고, 합치기 전 파일은 06_results/eval/<이름>_partial/ 에 보관한다.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_rag import OUT_DIR, load_cases, summarize  # noqa: E402


def jl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--retry", required=True)
    ap.add_argument("--keep-dir", required=True, help="합치기 전 파일을 보관할 폴더")
    args = ap.parse_args()
    main_path, retry_path = OUT_DIR / f"{args.run}.jsonl", OUT_DIR / f"{args.retry}.jsonl"
    rows = jl(main_path)
    retry = {(r["golden"], r["case_id"]): r for r in jl(retry_path) if not r.get("error")}
    keep = Path(args.keep_dir)
    keep.mkdir(parents=True, exist_ok=True)
    for p in (main_path, OUT_DIR / f"{args.run}.summary.json", retry_path, OUT_DIR / f"{args.retry}.summary.json"):
        shutil.copy(p, keep / p.name)
    replaced = 0
    for i, r in enumerate(rows):
        if r.get("error"):
            new = retry.get((r["golden"], r["case_id"]))
            if new:
                rows[i] = {**new, "run_id": args.run}
                replaced += 1
    cases = {(c["golden"], c["case_id"]): c for c in load_cases(["base", "negative", "life", "add"], ["provided", "team"])}
    results = []
    for r in rows:
        case = cases[(r["golden"], r["case_id"])]
        if r.get("error"):
            results.append({"case": case, "error": r["error"]})
        else:
            rec = {k: v for k, v in r.items() if k not in ("run_id", "case_id", "golden", "question_set", "question", "checks", "error")}
            results.append({"case": case, "record": rec, "checks": r["checks"]})
    summary = summarize(results)
    main_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    old = json.loads((OUT_DIR / f"{args.run}.summary.json").read_text(encoding="utf-8"))
    old["summary"] = summary
    old["merged_retry"] = {"retry_run_id": args.retry, "replaced": replaced}
    (OUT_DIR / f"{args.run}.summary.json").write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"교체 {replaced}건, 남은 오류 {summary['errors']}건")
    for g in ("all", "golden:provided", "golden:team"):
        s = summary[g]
        print(g, s["n"], round(s["behavior_strict"], 3), round(s["behavior_lenient"], 3), round(s["context_recall"], 3),
              round(s["citation_hit"], 3), round(s["avg_input_tokens"] + s["avg_output_tokens"]))


if __name__ == "__main__":
    main()
