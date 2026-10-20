"""청킹: Recursive(페이지 단위)와 Parent-Child(구조 단위 parent + 작은 child).

모든 청크는 같은 메타데이터를 가진다.
  chunk_id, parent_id, chunk_method, file_name, doc_group, page_no, page_end,
  section_title, content_type, source_ids, content
평가는 chunk의 source_ids(기준 답안의 expected_source_ids와 같은 형식)로 한다.
"""
from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from . import config
from .documents import Document


def _splitter(size: int, overlap: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=size, chunk_overlap=overlap,
        separators=config.SEPARATORS, add_start_index=True,
    )


def _content_type(doc: Document, start: int, end: int) -> str:
    types = doc.types_in(start, end)
    for kind in ("table", "chart"):
        if kind in types:
            return kind
    return "text"


def _pieces(splitter, text: str, base: int):
    """(abs_start, abs_end, text) 목록. base는 text가 문서 본문에서 시작하는 위치."""
    for d in splitter.create_documents([text]):
        s = d.metadata["start_index"]
        yield base + s, base + s + len(d.page_content), d.page_content


def recursive_chunks(doc: Document, size: int, overlap: int = config.RECURSIVE_OVERLAP) -> list[dict]:
    """페이지마다 따로 나눈다(청크가 페이지를 넘지 않는다)."""
    method = f"recursive_{size}_{overlap}"
    splitter = _splitter(size, overlap)
    chunks = []
    for start, end, page in doc.page_spans:
        j = 0
        for s, e, content in _pieces(splitter, doc.text[start:end], start):
            if not content.strip():
                continue
            unit = next((u for u in doc.units if u.start < e and u.end > s), None)
            chunks.append({
                "chunk_id": f"{method}:{doc.doc_key}:p{page:03d}:c{j:02d}",
                "parent_id": None,
                "chunk_method": method,
                "file_name": doc.file_name,
                "doc_group": doc.doc_group,
                "page_no": page,
                "page_end": page,
                "section_title": unit.title if unit else doc.doc_title,
                "content_type": _content_type(doc, s, e),
                "source_ids": doc.source_ids(s, e),
                "content": content,
            })
            j += 1
    return chunks


def parent_child_chunks(doc: Document, child_size: int = config.CHILD_SIZE,
                        overlap: int = config.RECURSIVE_OVERLAP) -> tuple[list[dict], list[dict]]:
    """구조 단위(unit)를 parent로, 그 안을 작은 child로 나눈다. (parents, children)를 돌려준다."""
    method = f"parent_child_{child_size}_{overlap}"
    splitter = _splitter(child_size, overlap)
    parents, children = [], []
    for idx, unit in enumerate(doc.units):
        text = doc.text[unit.start:unit.end]
        if not text.strip():
            continue
        pages = doc.pages_in(unit.start, unit.end)
        parent_id = f"{method}:{doc.doc_key}:p{idx:04d}"
        parents.append({
            "parent_id": parent_id,
            "chunk_method": method,
            "file_name": doc.file_name,
            "doc_group": doc.doc_group,
            "page_no": pages[0] if pages else 0,
            "page_end": pages[-1] if pages else 0,
            "section_title": unit.title,
            "content_type": _content_type(doc, unit.start, unit.end),
            "source_ids": doc.source_ids(unit.start, unit.end),
            "content": text,
        })
        j = 0
        for s, e, content in _pieces(splitter, text, unit.start):
            if not content.strip():
                continue
            cpages = doc.pages_in(s, e)
            children.append({
                "chunk_id": f"{parent_id}:c{j:02d}",
                "parent_id": parent_id,
                "chunk_method": method,
                "file_name": doc.file_name,
                "doc_group": doc.doc_group,
                "page_no": cpages[0] if cpages else 0,
                "page_end": cpages[-1] if cpages else 0,
                "section_title": unit.title,
                "content_type": _content_type(doc, s, e),
                "source_ids": doc.source_ids(s, e),
                "content": content,
            })
            j += 1
    return parents, children
