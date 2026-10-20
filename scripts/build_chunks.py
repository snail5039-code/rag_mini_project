"""extracted_pages.jsonl -> 05_chunks/*.jsonl

  python scripts/build_chunks.py              # 전체 (Recursive 4종 + Parent-Child)
  python scripts/build_chunks.py --stats      # 파일을 쓰지 않고 통계만 출력
"""
import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import config
from rag.chunking import parent_child_chunks, recursive_chunks
from rag.documents import load_documents


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def describe(name: str, rows: list[dict]) -> None:
    sizes = [len(r["content"]) for r in rows]
    by_group = Counter(r["doc_group"] for r in rows)
    no_ids = sum(1 for r in rows if not r["source_ids"])
    print(f"{name:28} n={len(rows):5} len(avg/med/max)={statistics.mean(sizes):6.0f}/"
          f"{statistics.median(sizes):5.0f}/{max(sizes):5}  source_ids 없음={no_ids}  {dict(by_group)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    docs = load_documents()
    for d in docs:
        for w in d.warnings:
            print(f"[경고] {d.file_name}: {w}")

    outputs: dict[str, list[dict]] = {}
    for size in config.RECURSIVE_SIZES:
        rows = [c for d in docs for c in recursive_chunks(d, size)]
        outputs[f"recursive_{size}_{config.RECURSIVE_OVERLAP}"] = rows
    parents, children = [], []
    for d in docs:
        p, c = parent_child_chunks(d)
        parents += p
        children += c
    method = f"parent_child_{config.CHILD_SIZE}_{config.RECURSIVE_OVERLAP}"
    outputs[method] = children

    for name, rows in outputs.items():
        describe(name, rows)
    describe(f"{method} (parent)", parents)

    if not args.stats:
        for name, rows in outputs.items():
            write_jsonl(config.CHUNK_DIR / f"{name}.jsonl", rows)
        write_jsonl(config.CHUNK_DIR / f"{method}.parents.jsonl", parents)
        print(f"저장: {config.CHUNK_DIR}")


if __name__ == "__main__":
    main()
