"""적재한 experiment로 child 검색 -> parent 조회가 되는지 확인하는 간단한 Hit@k 점검 (정식 평가 아님).

  python scripts/check_retrieval.py --experiment slice_test --id-prefix fsc-glossary kofia-terms-123-1709
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import config, db
from rag.embedding import GeminiEmbedder
from rag.retrieval import fetch_parents, vector_search

FILES = ["positive_cases.jsonl", "positive_life_guide_cases.jsonl", "additional_cases.jsonl"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--id-prefix", nargs="+", required=True, help="근거 ID가 모두 이 접두어로 시작하는 문항만 점검")
    ap.add_argument("--child-k", type=int, default=8)
    ap.add_argument("--max-parents", type=int, default=5)
    args = ap.parse_args()

    cases = [json.loads(l) for f in FILES for l in (config.ANSWERS_DIR / f).read_text(encoding="utf-8").splitlines()]
    cases = [c for c in cases if c["expected_source_ids"]
             and all(i.startswith(tuple(args.id_prefix)) for i in c["expected_source_ids"])]
    print(f"점검 문항 {len(cases)}개 (child_k={args.child_k}, max_parents={args.max_parents})")

    conn, emb = db.connect(), GeminiEmbedder()
    child_hit = parent_hit = 0
    rr = 0.0
    misses = []
    for c in cases:
        kids = vector_search(conn, emb.embed_query(c["question"]), args.experiment, args.child_k)
        parents = fetch_parents(conn, args.experiment, kids, args.max_parents)
        exp = set(c["expected_source_ids"])
        ranks = [r for r, k in enumerate(kids, 1) if exp & set(k["source_ids"])]
        child_hit += bool(ranks)
        parent_hit += any(exp & set(p["source_ids"]) for p in parents)
        rr += 1 / ranks[0] if ranks else 0
        if not ranks or ranks[0] > 3:
            misses.append((c["case_id"], ranks[0] if ranks else None))
    n = len(cases)
    print(f"child Hit@{args.child_k} = {child_hit}/{n}   parent Hit = {parent_hit}/{n}   MRR(child) = {rr / n:.3f}")
    print("첫 정답이 4위 밖이거나 없는 문항:", misses)


if __name__ == "__main__":
    main()
