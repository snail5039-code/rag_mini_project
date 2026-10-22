"""적재된 청킹 방식들을 같은 질문으로 가볍게 비교한다 (child 단계 Hit@k, MRR). 정식 평가 아님.

  python scripts/dev/compare_quick.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from rag import config, db
from rag.embedding import GeminiEmbedder
from rag.retrieval import fetch_parents, vector_search

FILES = ["positive_cases.jsonl", "positive_life_guide_cases.jsonl", "additional_cases.jsonl"]
KS = (1, 3, 5, 8)


def main() -> None:
    cases = [json.loads(l) for f in FILES for l in (config.ANSWERS_DIR / f).read_text(encoding="utf-8").splitlines()]
    conn, emb = db.connect(), GeminiEmbedder()
    experiments = [r[0] for r in conn.execute(
        "SELECT DISTINCT experiment_id FROM chunks WHERE experiment_id LIKE '%\\_\\_%' ORDER BY 1").fetchall()]
    queries = {c["case_id"]: emb.embed_query(c["question"]) for c in cases}
    print(f"질문 {len(cases)}개 (positive 140: 용어집·약관 60 + 가이드 20 + 추가 60), child_k={max(KS)}\n")

    header = f"{'experiment':46}" + "".join(f"Hit@{k:<3}" for k in KS) + "  MRR   parentHit(5)"
    print(header)
    for exp in experiments:
        hits, rr = defaultdict(int), 0.0
        by_group = defaultdict(lambda: [0, 0])
        parent_hit = 0
        for c in cases:
            kids = vector_search(conn, queries[c["case_id"]], exp, child_k=max(KS))
            exp_ids = set(c["expected_source_ids"])
            ranks = [r for r, k in enumerate(kids, 1) if exp_ids & set(k["source_ids"])]
            for k in KS:
                hits[k] += bool(ranks and ranks[0] <= k)
            rr += 1 / ranks[0] if ranks else 0
            group = c["case_id"].split("-")[0] if c["case_id"].startswith("ADD") else ("POS-life" if int(c["case_id"][3:]) > 60 else "POS-base")
            by_group[group][0] += bool(ranks and ranks[0] <= 5)
            by_group[group][1] += 1
            parents = fetch_parents(conn, exp, kids, 5)
            parent_hit += any(exp_ids & set(p["source_ids"]) for p in parents)
        n = len(cases)
        short = exp.split("__")[0]
        row = f"{short:46}" + "".join(f"{hits[k] / n:<7.3f}" for k in KS) + f"  {rr / n:.3f}  "
        row += f"{parent_hit / n:.3f}" if "parent_child" in exp else "  -"
        print(row)
        print("   Hit@5 세트별: " + "  ".join(f"{g} {a}/{b}" for g, (a, b) in sorted(by_group.items())))


if __name__ == "__main__":
    main()
