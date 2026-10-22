"""구조 인식 결과가 기준 답안의 expected_source_ids와 맞는지 확인한다.

  1) 존재 확인: 모든 expected_source_ids가 우리가 만든 근거 ID 집합에 있는가
  2) 내용 확인: 그 ID의 본문에 must_include 항목이 들어 있는가 (공백 제거 후 부분 문자열 일치)

  python scripts/validate_ids.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import config
from rag.documents import load_documents

CASE_FILES = ["positive_cases.jsonl", "positive_life_guide_cases.jsonl", "additional_cases.jsonl", "negative_cases.jsonl"]


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def id_texts(docs):
    """근거 ID -> 그 ID에 해당하는 본문(공백 제거)."""
    texts, excluded = {}, set()
    for d in docs:
        if d.id_by_page:
            for s, e, p in d.page_spans:
                key = f"{d.doc_key}-pdf-{p}"
                texts[key] = texts.get(key, "") + norm(d.text[s:e])
            excluded |= {f"{d.doc_key}-pdf-{p}" for p, _ in d.excluded_pages}
        else:
            for u in d.units:
                texts[u.unit_id] = norm(d.text[u.start:u.end])
    return texts, excluded


def main() -> None:
    docs = load_documents()
    texts, excluded = id_texts(docs)
    total = missing = on_excluded = 0
    weak = []
    for name in CASE_FILES:
        path = config.ANSWERS_DIR / name
        for line in path.read_text(encoding="utf-8").splitlines():
            case = json.loads(line)
            ids = case.get("expected_source_ids", [])
            if not ids:
                continue
            total += len(ids)
            absent = [i for i in ids if i not in texts]
            gone = [i for i in ids if i in excluded]
            missing += len(absent)
            on_excluded += len(gone)
            if absent:
                print(f"[없음] {case['case_id']}: {absent}")
            if gone:
                print(f"[제외된 쪽] {case['case_id']}: {gone}")
            evidence = "".join(texts.get(i, "") for i in ids)
            must = case.get("must_include", [])
            if must:
                hit = sum(norm(m) in evidence for m in must)
                if hit / len(must) < 0.5:
                    weak.append((case["case_id"], hit, len(must), ids))
    print(f"\n근거 ID {total}개 중 없음 {missing}개, 제외된 쪽 {on_excluded}개")
    print(f"must_include 일치율 50% 미만 문항: {len(weak)}개 (표현이 다르게 쓰였을 수 있어 참고용)")
    for case_id, hit, n, ids in weak[:15]:
        print(f"  {case_id}: {hit}/{n}  {ids[:3]}")


if __name__ == "__main__":
    main()
