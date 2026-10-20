"""05_chunks/*.jsonl -> 임베딩 -> PostgreSQL(pgvector) 적재.

  python scripts/load_chunks.py --method parent_child_300_60 --dry-run        # 호출 없이 개수·길이만 확인
  python scripts/load_chunks.py --method parent_child_300_60 --limit 50       # 일부만 적재(동작 확인용)
  python scripts/load_chunks.py --method parent_child_300_60 --experiment slice_test --files 04_신용거래약관 glossary
  python scripts/load_chunks.py --method parent_child_300_60                  # 전체 적재

experiment_id의 기본값은 "<method>__<임베딩 모델>_<차원>"이다. 이미 저장된 chunk_id는 다시 임베딩하지 않는다.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import config
from rag.embedding import embed_text


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", required=True, help="예: parent_child_300_60, recursive_500_60")
    ap.add_argument("--experiment")
    ap.add_argument("--files", nargs="+", help="file_name에 이 문자열이 들어간 문서만 (예: 04_신용거래약관 glossary)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    experiment_id = args.experiment or f"{args.method}__{config.EMBEDDING_MODEL}_{config.EMBEDDING_DIM}"
    chunks = read_jsonl(config.CHUNK_DIR / f"{args.method}.jsonl")
    parents_path = config.CHUNK_DIR / f"{args.method}.parents.jsonl"
    parents = read_jsonl(parents_path) if parents_path.exists() else []
    if args.files:
        match = lambda row: any(f in row["file_name"] for f in args.files)
        chunks = [c for c in chunks if match(c)]
        parents = [p for p in parents if match(p)]
    if args.limit:
        chunks = chunks[: args.limit]
        keep = {c["parent_id"] for c in chunks}
        parents = [p for p in parents if p["parent_id"] in keep]

    texts = [embed_text(c["section_title"], c["content"]) for c in chunks]
    chars = sum(map(len, texts))
    print(f"experiment_id={experiment_id}\nchild/청크 {len(chunks)}개, parent {len(parents)}개, 임베딩 입력 {chars:,}자")
    if args.dry_run:
        return

    from rag import db
    from rag.embedding import GeminiEmbedder

    conn = db.connect()
    db.init_schema(conn)
    done = db.existing_chunk_ids(conn, experiment_id)
    pending = [(c, t) for c, t in zip(chunks, texts) if c["chunk_id"] not in done]
    print(f"이미 저장 {len(chunks) - len(pending)}개, 새로 임베딩 {len(pending)}개")

    db.insert_parents(conn, experiment_id, parents)
    embedder = GeminiEmbedder()
    step = 128
    for i in range(0, len(pending), step):
        part = pending[i:i + step]
        vectors = embedder.embed_documents([t for _, t in part])
        db.insert_chunks(conn, experiment_id, [c for c, _ in part], vectors)
        print(f"  {min(i + step, len(pending))}/{len(pending)}")
    bad = db.check_integrity(conn, experiment_id)
    print("정합성 검사: parent_id가 없는 child", bad, "개")


if __name__ == "__main__":
    main()
