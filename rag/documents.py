"""추출 JSONL을 문서 단위로 읽고 구조(unit)를 인식한다.

문서 종류별 구조 단위
  - 용어집(glossary)      : 용어 + 정의. 근거 ID는 끝 페이지 출처 목록의 dicId로 만든다.
  - 표준약관(standard_terms): 조항(제N조). 근거 ID는 출처 목록 URL의 seq·historySeq와 조 번호로 만든다.
  - 가이드·추가 PDF        : 소제목 + 문단(title 블록 기준). 근거 ID는 페이지 번호로 만든다.

문서마다 본문을 하나의 문자열(Document.text)로 이어 붙이고, 페이지·구조 단위의 위치를
문자 offset으로 기록한다. 청크의 페이지와 근거 ID는 이 offset으로 계산한다.
"""
from __future__ import annotations

import json
import re
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field

from . import config

_PRIVATE_USE = re.compile(r"[-]")
_TERMS_LIST_ARTICLE = re.compile(r"/\s*제(\d+)조(?:의(\d+))?\s*\(")
_TERMS_URL = re.compile(r"seq=(\d+)&historySeq=(\d+)")
_GLOSSARY_SEP = " / 용어 설명 / "


@dataclass
class Unit:
    unit_id: str | None      # 약관·용어집은 근거 ID, 가이드는 None(페이지로 계산)
    title: str
    start: int
    end: int
    kind: str = "section"    # article / entry / section


@dataclass
class Document:
    file_name: str
    doc_group: str
    doc_key: str
    doc_title: str
    text: str
    page_spans: list[tuple[int, int, int]]          # (start, end, page_no)
    units: list[Unit]
    block_spans: list[tuple[int, int, str]] = field(default_factory=list)  # (start, end, type)
    excluded_pages: list[tuple[int, str]] = field(default_factory=list)    # (page_no, reason)
    warnings: list[str] = field(default_factory=list)

    @property
    def id_by_page(self) -> bool:
        return self.doc_group in ("life_guide", "additional")

    def pages_in(self, start: int, end: int) -> list[int]:
        return sorted({p for s, e, p in self.page_spans if s < max(end, start + 1) and e > start})

    def types_in(self, start: int, end: int) -> set[str]:
        return {t for s, e, t in self.block_spans if s < max(end, start + 1) and e > start}

    def source_ids(self, start: int, end: int) -> list[str]:
        if self.id_by_page:
            return [f"{self.doc_key}-pdf-{p}" for p in self.pages_in(start, end)]
        return [
            u.unit_id for u in self.units
            if u.unit_id and u.start < max(end, start + 1) and u.end > start
        ]


# ------------------------------------------------------------------ 읽기
def load_pages(path=config.EXTRACTED_PATH) -> dict[str, list[dict]]:
    by_file: dict[str, list[dict]] = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for line in f:
            page = json.loads(line)
            by_file[page["file_name"]].append(page)
    for pages in by_file.values():
        pages.sort(key=lambda p: p["page_no"])
    return by_file


def _clean(text: str) -> str:
    text = _PRIVATE_USE.sub("", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _plain_lines(page: dict) -> list[tuple[int, str]]:
    """평문 문서 한 페이지를 (page_no, line) 목록으로 만든다. 끝의 쪽번호 줄은 버린다."""
    text = "\n".join(b["text"] for b in page["blocks"])
    lines = [ln.rstrip() for ln in text.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip() == str(page["page_no"]):
        lines.pop()
    return [(page["page_no"], ln) for ln in lines]


def _assemble(lines: list[tuple[int, str]]):
    """(page, line) 목록을 하나의 문자열로 잇고 줄·페이지 offset을 돌려준다."""
    starts, spans, pos = [], [], 0
    cur_page, page_start = None, 0
    for page, line in lines:
        if page != cur_page:
            if cur_page is not None:
                spans.append((page_start, pos - 1, cur_page))
            cur_page, page_start = page, pos
        starts.append(pos)
        pos += len(line) + 1
    if cur_page is not None:
        spans.append((page_start, max(pos - 1, page_start), cur_page))
    return "\n".join(line for _, line in lines), starts, spans


# ------------------------------------------------------------------ 표준약관
def parse_terms(file_name: str, pages: list[dict]) -> Document:
    all_lines = [pl for page in pages for pl in _plain_lines(page)]
    list_at = next(
        (i for i, (_, ln) in enumerate(all_lines) if "law.kofia.or.kr" in ln or re.search(r"/\s*https?://", ln)),
        len(all_lines),
    )
    body, listing = all_lines[:list_at], all_lines[list_at:]
    joined = "".join(ln for _, ln in listing)
    warnings: list[str] = []

    m = _TERMS_URL.search(joined)
    if not m:
        raise ValueError(f"{file_name}: 출처 목록에서 seq/historySeq를 찾지 못했습니다.")
    seq, hist = m.group(1), m.group(2)
    doc_key = f"kofia-terms-{seq}-{hist}"
    # 출처 목록의 순서가 곧 근거 ID의 마지막 번호다. 조의2처럼 조 번호가 아닌 항목도 한 칸을 차지한다.
    listed = [(int(n), int(m2) if m2 else None) for n, m2 in _TERMS_LIST_ARTICLE.findall(joined)]

    text, starts, spans = _assemble(body)
    heads, cursor = [], 0
    for k, (num, sub) in enumerate(listed, start=1):
        pattern = re.compile(rf"^제{num}조" + (rf"의{sub}" if sub else "") + r"\s*\(")
        found = next((i for i in range(cursor, len(body)) if pattern.match(body[i][1])), None)
        if found is None:
            warnings.append(f"출처 목록 {k}번째(제{num}조{'의' + str(sub) if sub else ''})를 본문에서 못 찾음")
            continue
        heads.append((found, k))
        cursor = found + 1

    units = []
    for n, (i, k) in enumerate(heads):
        end = starts[heads[n + 1][0]] - 1 if n + 1 < len(heads) else len(text)
        title = body[i][1].strip()
        if ")" not in title and i + 1 < len(body):
            title = title + body[i + 1][1].strip()
        units.append(Unit(f"{doc_key}-{k:03d}", title, starts[i], end, "article"))

    doc_title = body[0][1].strip() if body else file_name
    return Document(file_name, "standard_terms", doc_key, doc_title, text, spans, units, warnings=warnings)


# ------------------------------------------------------------------ 용어집
def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def parse_glossary(file_name: str, pages: list[dict]) -> Document:
    all_lines = [pl for page in pages for pl in _plain_lines(page)]
    list_at = next((i for i, (_, ln) in enumerate(all_lines) if _GLOSSARY_SEP in ln), len(all_lines))
    body, listing = all_lines[:list_at], all_lines[list_at:]
    warnings: list[str] = []

    # 출처 목록: "용어 / 용어 설명 / URL" (URL은 줄바꿈으로 끊길 수 있다)
    records: list[str] = []
    for _, ln in listing:
        if _GLOSSARY_SEP in ln:
            records.append(ln)
        elif records:
            records[-1] += ln
    terms: list[tuple[str, str]] = []
    for rec in records:
        name, url = rec.split(_GLOSSARY_SEP, 1)
        dm = re.search(r"dicId=(\d+)", url)
        if dm:
            terms.append((name.strip(), dm.group(1)))
        else:
            warnings.append(f"dicId를 못 읽음: {rec[:50]!r}")

    body = [(p, ln) for p, ln in body if ln.strip() and ln.strip() != "금융용어 모음"]
    text, starts, spans = _assemble(body)

    heads, ptr, i = [], 0, 0
    while i < len(body) and ptr < len(terms):
        one = _norm(body[i][1])
        two = _norm(body[i][1] + (body[i + 1][1] if i + 1 < len(body) else ""))
        target = _norm(terms[ptr][0])
        if one == target:
            heads.append((i, ptr)); ptr += 1
        elif two == target:
            heads.append((i, ptr)); ptr += 1; i += 1
        i += 1
    if ptr < len(terms):
        warnings.append(f"본문에서 찾지 못한 용어 {len(terms) - ptr}개 (첫 번째: {terms[ptr][0]!r})")

    units = []
    for k, (i, t) in enumerate(heads):
        end = starts[heads[k + 1][0]] - 1 if k + 1 < len(heads) else len(text)
        units.append(Unit(f"fsc-glossary-{terms[t][1]}", terms[t][0], starts[i], end, "entry"))
    return Document(file_name, "glossary", "fsc-glossary", "금융용어집", text, spans, units, warnings=warnings)


# ------------------------------------------------------------------ 가이드·추가 PDF
def _is_toc(page: dict) -> str | None:
    text = "\n".join(b["text"] for b in page["blocks"])
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    leaders = sum(bool(re.search(r"[·․…]{5,}\s*\d+\s*$", ln)) for ln in lines)
    if leaders >= 3:
        return "목차(점선 리더)"
    numbered = sum(bool(re.fullmatch(r"\d{1,2}", ln)) for ln in lines)
    trailing = sum(bool(re.search(r"\s\d{1,3}$", ln)) for ln in lines)
    if numbered >= 5 and trailing >= 5:
        return "목차(번호+쪽수)"
    return None


def _is_heading(block: dict) -> bool:
    raw = block["text"]
    text = _clean(raw)
    if block["type"] != "title" or not text or re.fullmatch(r"\d{1,3}", text):
        return False
    if _PRIVATE_USE.match(raw.lstrip()) or text.startswith(("-", "*")) or len(text) > 100:
        return False
    return True


def parse_guide(file_name: str, pages: list[dict], doc_group: str) -> Document:
    stem = file_name.rsplit("/", 1)[-1].removesuffix(".pdf")
    doc_key = config.LIFE_GUIDE_KEY if doc_group == "life_guide" else stem
    doc_title = config.DOC_TITLES.get(stem, stem)

    excluded, blocks = [], []   # blocks: (type, text, page, is_heading)
    for page in pages:
        reason = _is_toc(page)
        if reason:
            excluded.append((page["page_no"], reason))
            continue
        for b in page["blocks"]:
            text = _clean(b["text"])
            if not text or re.fullmatch(r"\d{1,3}", text):
                continue
            if b["type"] == "image" and len(text) < 15:
                continue
            blocks.append((b["type"], text, page["page_no"], _is_heading(b)))

    # 소제목(title 블록) 기준으로 section을 만든다. 짧으면 다음 소제목과 합치고, 길면 나눈다.
    sections, cur = [], None

    def flush():
        nonlocal cur
        if cur and cur["blocks"]:
            sections.append(cur)
        cur = None

    def start(titles):
        return {"titles": list(titles), "blocks": [], "body": 0}

    cur = start([doc_title])
    for btype, text, page, heading in blocks:
        if heading:
            if cur["body"] >= config.MIN_PARENT_CHARS:
                flush()
                cur = start([text])
            else:
                cur["titles"].append(text)
        elif cur["body"] + len(text) > config.MAX_PARENT_CHARS and cur["body"] >= config.MIN_PARENT_CHARS:
            titles = cur["titles"]
            flush()
            cur = start(titles)
        cur["blocks"].append((btype, text, page))
        if not heading:
            cur["body"] += len(text)
    flush()

    parts, spans, block_spans, units, pos = [], [], [], [], 0
    for sec in sections:
        sec_start = pos
        for btype, text, page in sec["blocks"]:
            if parts:
                pos += 2  # "\n\n"
            parts.append(text)
            spans.append((pos, pos + len(text), page))
            block_spans.append((pos, pos + len(text), btype))
            pos += len(text)
        titles = sec["titles"]
        label = titles[0] if len(titles) == 1 else f"{titles[0]} > {titles[-1]}"
        if titles[0] != doc_title:
            label = f"{doc_title} - {label}"
        units.append(Unit(None, re.sub(r"\s+", " ", label), sec_start, pos, "section"))
    # 쪽 단위 span 하나로 합친다.
    page_spans: list[tuple[int, int, int]] = []
    for s, e, p in spans:
        if page_spans and page_spans[-1][2] == p:
            page_spans[-1] = (page_spans[-1][0], e, p)
        else:
            page_spans.append((s, e, p))
    return Document(file_name, doc_group, doc_key, doc_title, _join(parts), page_spans, units,
                    block_spans, excluded)


def _join(parts: list[str]) -> str:
    # 섹션 경계와 블록 경계 모두 "\n\n"으로 잇는다(위 offset 계산과 같다).
    return "\n\n".join(parts)


# ------------------------------------------------------------------ 진입점
def load_documents(path=config.EXTRACTED_PATH) -> list[Document]:
    docs = []
    for file_name, pages in sorted(load_pages(path).items()):
        group = pages[0]["doc_group"]
        if group == "glossary":
            docs.append(parse_glossary(file_name, pages))
        elif group == "standard_terms":
            docs.append(parse_terms(file_name, pages))
        else:
            docs.append(parse_guide(file_name, pages, group))
    return docs
