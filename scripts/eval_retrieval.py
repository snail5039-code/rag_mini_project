"""검색 평가: 제공 positive 140문항으로 experiment x 검색기 조합을 같은 조건에서 비교한다.

  python scripts/eval_retrieval.py                                   # 적재된 모든 experiment x 4개 검색기
  python scripts/eval_retrieval.py --experiments parent_child_300_60 --retrievers vector hybrid
  python scripts/eval_retrieval.py --no-save                         # DB·파일에 저장하지 않음

지표는 child 단계(검색기가 근거를 찾았나)와 parent 단계(답변 Agent가 받는 문맥에 근거가 있나)로 나눈다.
결과는 PostgreSQL(retrieval_eval_runs/cases)과 06_results/*.json에 저장한다.
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg.types.json import Jsonb

from rag import config, db
from rag.embedding import CachedQueryEmbedder
from rag.metrics import mean_metrics, ranking_metrics
from rag.retrieval import fetch_parents, make_retriever

FILES = {"base": "positive_cases.jsonl", "life": "positive_life_guide_cases.jsonl", "add": "additional_cases.jsonl"}
CHILD_KS = (1, 3, 5, 8, 10)
PARENT_KS = (1, 3, 5)
RESULT_DIR = config.ROOT / "06_results"


def load_cases() -> list[dict]:
    cases = []
    for qset, name in FILES.items():
        for line in (config.ANSWERS_DIR / name).read_text(encoding="utf-8").splitlines():
            c = json.loads(line)
            if c.get("expected_source_ids"):
                cases.append({**c, "question_set": qset})
    return cases


def evaluate(conn, embedder, experiment: str, retriever_name: str, cases, child_k: int, max_parents: int):
    retriever = make_retriever(retriever_name, conn, experiment)
    has_parents = experiment.startswith("parent_child")
    rows, started = [], time.perf_counter()
    for c in cases:
        qvec = embedder.embed_query(c["question"])
        children = retriever.search(c["question"], qvec, k=max(CHILD_KS))
        gold = set(c["expected_source_ids"])
        m = {f"child_{k}": v for k, v in ranking_metrics([d["source_ids"] for d in children], gold, CHILD_KS).items()}
        parents = []
        if has_parents:
            parents = fetch_parents(conn, experiment, children[:child_k], max_parents)
            m |= {f"parent_{k}": v for k, v in
                  ranking_metrics([p["source_ids"] for p in parents], gold, PARENT_KS).items()}
            m["parent_chars"] = float(sum(len(p["content"]) for p in parents))
        rows.append({"case": c, "children": children, "parents": parents, "metrics": m})
    latency = (time.perf_counter() - started) * 1000 / len(cases)
    return rows, latency


def summarize(rows) -> dict:
    out = {"all": mean_metrics([r["metrics"] for r in rows])}
    groups = defaultdict(list)
    for r in rows:
        c = r["case"]
        groups[f"set:{c['question_set']}"].append(r["metrics"])
        groups[f"difficulty:{c.get('difficulty')}"].append(r["metrics"])
        groups["gold:" + ("multi" if len(c["expected_source_ids"]) > 1 else "single")].append(r["metrics"])
    out |= {g: mean_metrics(ms) | {"n": len(ms)} for g, ms in sorted(groups.items())}
    return out


def save(conn, run_id, experiment, retriever, params, summary, rows) -> None:
    conn.execute("""INSERT INTO retrieval_eval_runs (run_id, experiment_id, retriever, params, metrics)
                    VALUES (%s, %s, %s, %s, %s)""",
                 (run_id, experiment, retriever, Jsonb(params), Jsonb(summary)))
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO retrieval_eval_cases (run_id, case_id, question_set, difficulty, gold,
                   child_ranked, parent_ranked, metrics) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            [(run_id, r["case"]["case_id"], r["case"]["question_set"], r["case"].get("difficulty"),
              r["case"]["expected_source_ids"],
              Jsonb([{"chunk_id": d["chunk_id"], "source_ids": d["source_ids"]} for d in r["children"]]),
              Jsonb([{"parent_id": p["parent_id"], "source_ids": p["source_ids"]} for p in r["parents"]]) if r["parents"] else None,
              Jsonb(r["metrics"])) for r in rows],
        )
    RESULT_DIR.mkdir(exist_ok=True)
    (RESULT_DIR / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "experiment_id": experiment, "retriever": retriever,
                    "params": params, "summary": summary}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiments", nargs="+", help="chunk_method 접두어 (예: parent_child_300_60)")
    ap.add_argument("--retrievers", nargs="+", default=["vector", "bm25", "hybrid", "mmr"])
    ap.add_argument("--child-k", type=int, default=8, help="parent 조회에 쓰는 상위 child 수")
    ap.add_argument("--max-parents", type=int, default=5)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    conn = db.connect()
    db.init_schema(conn)
    embedder = CachedQueryEmbedder()
    experiments = [r[0] for r in conn.execute(
        "SELECT DISTINCT experiment_id FROM chunks ORDER BY 1").fetchall()]
    if args.experiments:
        experiments = [e for e in experiments if e.split("__")[0] in args.experiments]
    cases = load_cases()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"문항 {len(cases)}개, experiment {len(experiments)}개, 검색기 {args.retrievers}\n")
    head = f"{'experiment':22}{'retriever':9}" + "".join(f"{h:>9}" for h in
        ("Hit@1", "Hit@5", "Rec@5", "Rec@10", "nDCG@5", "MRR", "P.Hit@5", "P.Rec@5", "P.chars", "ms/q"))
    print(head)
    for exp in experiments:
        for name in args.retrievers:
            rows, latency = evaluate(conn, embedder, exp, name, cases, args.child_k, args.max_parents)
            summary = summarize(rows)
            a = summary["all"]
            short = exp.split("__")[0]
            cells = [a["child_hit@1"], a["child_hit@5"], a["child_recall@5"], a["child_recall@10"],
                     a["child_ndcg@5"], a["child_mrr"]]
            line = f"{short:22}{name:9}" + "".join(f"{v:9.3f}" for v in cells)
            if "parent_hit@5" in a:
                line += f"{a['parent_hit@5']:9.3f}{a['parent_recall@5']:9.3f}{a['parent_chars']:9.0f}"
            else:
                line += f"{'-':>9}{'-':>9}{'-':>9}"
            print(line + f"{latency:9.0f}")
            if not args.no_save:
                params = {"child_ks": CHILD_KS, "child_k": args.child_k, "max_parents": args.max_parents,
                          "embedding_model": config.EMBEDDING_MODEL, "embedding_dim": config.EMBEDDING_DIM,
                          "cases": len(cases)}
                save(conn, f"{stamp}__{short}__{name}", exp, name, params, summary, rows)
    if not args.no_save:
        print(f"\n저장: PostgreSQL retrieval_eval_runs/cases, {RESULT_DIR}")


if __name__ == "__main__":
    main()
