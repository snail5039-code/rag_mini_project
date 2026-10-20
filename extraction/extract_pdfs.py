"""PDF 추출: 01_data/ PDF -> 04_extracted/extracted_pages.jsonl (페이지 1개 = 1줄)

처리 흐름 (기획서 3장)
  - 약관·용어집(1단 텍스트 문서): pdfplumber 페이지 전체 추출
  - 가이드북·추가 PDF: RapidLayout(PP-DocLayoutV3)로 영역 탐지 -> 영역별 추출
      text/title  : pdfplumber 영역 텍스트, 텍스트 레이어가 없으면 RapidOCR(한국어)
      table       : pdfplumber 표 -> 품질 검사 실패 시 RapidTable -> 실패 시 Gemini Vision 대기
      chart/image : 영역 텍스트(OCR 포함) 저장 + 이미지 crop 저장 -> Gemini Vision 대기
  - 레이아웃 영역 밖에 남은 글자는 누락 방지를 위해 leftover 블록으로 추가

page_no 는 PDF 실제 쪽 순서(1부터)이며 03_answers 의 source_pages 와 같은 기준이다.
bbox 는 PDF 포인트 단위 [x0, top, x1, bottom] (좌상단 원점, pdfplumber 좌표계).

사용법
  python extraction/extract_pdfs.py                 # 전체
  python extraction/extract_pdfs.py --files additional/self_employed_debt_2025.pdf
"""

import argparse
import html.parser
import json
import logging
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pdfplumber
import pdfplumber.utils as pdf_utils
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "01_data"
OUT_DIR = ROOT / "04_extracted"
PAGES_DIR = OUT_DIR / "pages"
CROPS_DIR = OUT_DIR / "crops"
LOG_PATH = ROOT / "logs" / "app.log"

RENDER_SCALE = 2.0
LAYOUT_CONF = 0.5  # 텍스트·제목 영역 채택 기준
LAYOUT_CONF_VISUAL = 0.25  # 표·차트·그림 채택 기준 (놓치면 Vision 으로도 못 넘어가므로 낮게)
LOW_TEXT_CHARS = 30  # 이보다 글자가 적으면 텍스트 레이어 없음(스캔·이미지 페이지)으로 본다
MIN_VISION_AREA = 0.03  # 페이지 면적 대비 이 비율보다 작은 이미지는 아이콘·로고로 보고 Vision 생략
CHAR_PAD = 4.0  # 글자 배정 시 영역 확장 폭(pt)
NEAR_GAP = 12.0  # 영역 밖 글자를 위아래로 이 거리(pt) 안의 텍스트 영역에 붙인다
SEGMENT_GAP = 1.5  # 같은 줄 글자 사이 간격이 글자 크기의 이 배수를 넘으면 다른 줄 조각(단 구분)
OCR_TO_VISION_MIN = 4  # OCR 로 읽은 텍스트가 이 글자 수 이상이면 Gemini 로 다시 옮겨 적는다(띄어쓰기·오인식 보정)

LABEL_TO_TYPE = {
    "doc_title": "title", "paragraph_title": "title",
    "figure_title": "caption",
    "table": "table",
    "chart": "chart",
    "image": "image", "seal": "image",
    "header": None, "footer": None, "number": None,
    "header_image": None, "footer_image": None,
}  # 그 외 라벨(text, abstract, content, footnote 등)은 text

log = logging.getLogger("extract")


# ---------------------------------------------------------------- 문서 분류

def doc_group(rel: str) -> str:
    if rel.startswith("standard_terms/"):
        return "standard_terms"
    if rel.startswith("additional/"):
        return "additional"
    if rel == "financial_glossary_readable.pdf":
        return "glossary"
    if rel == "financial_life_guide.pdf":
        return "life_guide"
    return "other"


def use_layout(group: str) -> bool:
    # 약관·용어집은 1단 텍스트이고 표·이미지가 없어 페이지 전체 추출이 더 정확하다
    return group in ("life_guide", "additional", "other")


# ---------------------------------------------------------------- 좌표 유틸

def r1(v):
    return [round(float(x), 1) for x in v]


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter_ratio(inner, outer):
    """inner 면적 중 outer 와 겹치는 비율"""
    x0, y0 = max(inner[0], outer[0]), max(inner[1], outer[1])
    x1, y1 = min(inner[2], outer[2]), min(inner[3], outer[3])
    a = area(inner)
    return area([x0, y0, x1, y1]) / a if a else 0.0


def center_in(obj_bbox, region, pad=1.0):
    cx = (obj_bbox[0] + obj_bbox[2]) / 2
    cy = (obj_bbox[1] + obj_bbox[3]) / 2
    return region[0] - pad <= cx <= region[2] + pad and region[1] - pad <= cy <= region[3] + pad


def clip(b, w, h):
    return [max(0.0, b[0]), max(0.0, b[1]), min(w, b[2]), min(h, b[3])]


# ---------------------------------------------------------------- 표 변환·품질

def clean_cell(c):
    return "" if c is None else " ".join(str(c).split()).replace("|", "\\|")


def rows_to_markdown(rows):
    width = max(len(r) for r in rows)
    rows = [[clean_cell(c) for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def table_quality(rows, region_chars):
    """셀 누락·병합 셀·그래프 오인식 여부를 숫자로 기록하고 통과 여부를 판단"""
    n_rows = len(rows)
    n_cols = max((len(r) for r in rows), default=0)
    cells = [c for r in rows for c in r]
    empty = sum(1 for c in cells if c is None or not str(c).strip())
    empty_ratio = empty / len(cells) if cells else 1.0
    cell_chars = sum(len("".join(str(c).split())) for c in cells if c)
    coverage = cell_chars / region_chars if region_chars else 1.0
    reasons = []
    if n_rows < 2 or n_cols < 2:
        reasons.append("too_small")  # 1행·1열 표는 그래프·박스를 표로 오인식한 경우가 많다
    if empty_ratio > 0.6:
        reasons.append("many_empty_cells")
    if coverage < 0.8:
        reasons.append("missing_text")  # 영역 안 글자가 셀에 다 들어가지 않음 = 셀 누락
    max_cell = max((len("".join(str(c).split())) for c in cells if c), default=0)
    if len(cells) >= 4 and cell_chars and max_cell / cell_chars > 0.5:
        reasons.append("one_cell_dominant")  # 내용이 한 셀에 몰림 = 셀 경계 인식 실패
    return {
        "rows": n_rows, "cols": n_cols,
        "empty_ratio": round(empty_ratio, 3), "coverage": round(min(coverage, 9.99), 3),
        "ok": not reasons, "reasons": reasons,
    }


class _HTMLTable(html.parser.HTMLParser):
    """RapidTable HTML -> 2차원 셀 (rowspan/colspan 은 같은 값으로 채움)"""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell, self._span = [], None, None, (1, 1)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
            self._span = (int(a.get("rowspan", 1) or 1), int(a.get("colspan", 1) or 1))

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(("".join(self._cell).strip(), self._span))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def grid(self):
        grid, pending = [], {}  # pending[(r, c)] = rowspan 으로 내려온 값
        for r, row in enumerate(self.rows):
            out, c, it = [], 0, iter(row)
            while True:
                while (r, c) in pending:
                    out.append(pending.pop((r, c)))
                    c += 1
                nxt = next(it, None)
                if nxt is None:
                    break
                text, (rs, cs) = nxt
                for dc in range(cs):
                    out.append(text)
                    for dr in range(1, rs):
                        pending[(r + dr, c + dc)] = text
                c += cs
            grid.append(out)
        return grid


def html_to_rows(html_str):
    p = _HTMLTable()
    p.feed(html_str or "")
    return p.grid()


# ---------------------------------------------------------------- 엔진 (지연 로딩)

class Engines:
    def __init__(self):
        self._layout = self._ocr = self._table = None

    @property
    def layout(self):
        if self._layout is None:
            from rapid_layout import ModelType, RapidLayout, RapidLayoutInput
            self._layout = RapidLayout(cfg=RapidLayoutInput(
                model_type=ModelType.PP_DOC_LAYOUTV3, conf_thresh=LAYOUT_CONF_VISUAL))
        return self._layout

    @property
    def ocr(self):
        if self._ocr is None:
            from rapidocr import LangDet, LangRec, ModelType, OCRVersion, RapidOCR
            self._ocr = RapidOCR(params={
                "Global.use_cls": False,
                "Det.lang_type": LangDet.MULTI, "Det.ocr_version": OCRVersion.PPOCRV5,
                "Det.model_type": ModelType.MOBILE,
                "Rec.lang_type": LangRec.KOREAN, "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
            })
        return self._ocr

    @property
    def table(self):
        if self._table is None:
            from rapid_table import ModelType, RapidTable, RapidTableInput
            self._table = RapidTable(RapidTableInput(model_type=ModelType.SLANETPLUS, use_ocr=True))
        return self._table


# ---------------------------------------------------------------- 페이지 처리

class PageCtx:
    """한 페이지의 pdfplumber 객체, 렌더링 이미지, (필요 시) 전체 OCR 결과"""

    def __init__(self, pl_page, pdfium_page, engines):
        self.pl = pl_page
        self.w, self.h = float(pl_page.width), float(pl_page.height)
        self.img = pdfium_page.render(scale=RENDER_SCALE).to_pil().convert("RGB")
        self.sx = self.img.width / self.w
        self.sy = self.img.height / self.h
        self.engines = engines
        self.all_chars = list(pl_page.chars)  # 공백 포함: 텍스트 조립·영역 배정용
        self.chars = [c for c in self.all_chars if c["text"].strip()]  # 글자 수 계산용
        self._ocr_lines = None
        self.used_ocr = False

    def bgr(self, img=None):
        return np.ascontiguousarray(np.array(img or self.img)[:, :, ::-1])

    def to_px(self, b):
        return (int(b[0] * self.sx), int(b[1] * self.sy), int(np.ceil(b[2] * self.sx)), int(np.ceil(b[3] * self.sy)))

    def crop_img(self, b):
        return self.img.crop(self.to_px(b))

    def chars_in(self, b):
        return [c for c in self.chars if center_in((c["x0"], c["top"], c["x1"], c["bottom"]), b)]

    def assign_chars(self, boxes, pad=CHAR_PAD):
        """글자마다 가장 많이 겹치는 영역 1개에 배정 (중복·누락 방지).

        일부 PDF는 폰트 메트릭 때문에 pdfplumber 글자 bbox 가 실제 글자보다 아래로
        밀려 있어 '중심점 포함' 기준으로는 글자가 영역 밖으로 빠진다.
        반환: 영역별 글자 리스트, 어느 영역에도 겹치지 않은 글자 리스트
        """
        grown = [[b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad] for b in boxes]
        assigned = [[] for _ in boxes]
        left = []
        for c in self.all_chars:
            cb = (c["x0"], c["top"], c["x1"], c["bottom"])
            best, best_ov = None, 0.0
            for i, g in enumerate(grown):
                ov = inter_ratio(cb, g)
                # 겹침이 같으면 더 작은(구체적인) 영역 우선
                if ov > best_ov + 1e-6 or (best is not None and abs(ov - best_ov) <= 1e-6 and ov > 0
                                           and area(boxes[i]) < area(boxes[best])):
                    best, best_ov = i, ov
            (assigned[best] if best is not None else left).append(c)
        return assigned, left

    def line_segments(self):
        """같은 줄에서 글자 간격이 SEGMENT_GAP(글자 크기 배수) 이하로 이어진 글자 묶음.
        2단 편집의 왼쪽·오른쪽 단은 간격이 커서 다른 묶음이 된다."""
        segs = []
        for line in self.pl.extract_text_lines(return_chars=True, strip=False):
            chars = sorted(line["chars"], key=lambda c: c["x0"])
            cur = []
            for c in chars:
                if cur and c["x0"] - cur[-1]["x1"] > SEGMENT_GAP * max(c.get("size", 10), 1):
                    segs.append(cur)
                    cur = []
                cur.append(c)
            if cur:
                segs.append(cur)
        return segs

    def regroup_by_line(self, assigned, left):
        """줄 조각 단위 다수결로 재배정: 영역 경계에 걸친 제목·단어가 둘로 갈라지지 않게 한다."""
        owner = {id(c): i for i, cs in enumerate(assigned) for c in cs}
        for seg in self.line_segments():
            votes = Counter(owner.get(id(c)) for c in seg if c["text"].strip())
            votes.pop(None, None)
            if not votes:
                continue
            target = votes.most_common(1)[0][0]
            for c in seg:
                owner[id(c)] = target
        new_assigned = [[] for _ in assigned]
        new_left = []
        for c in self.all_chars:
            o = owner.get(id(c))
            (new_assigned[o] if o is not None else new_left).append(c)
        return new_assigned, new_left

    @staticmethod
    def chars_text(chars):
        return (pdf_utils.extract_text(chars, x_tolerance=3, y_tolerance=3) or "").strip() if chars else ""

    def ocr_lines(self):
        """페이지 전체 OCR (텍스트 레이어가 없는 영역이 처음 필요할 때 1회 실행)"""
        if self._ocr_lines is None:
            self.used_ocr = True
            res = self.engines.ocr(self.bgr())
            lines = []
            for box, txt, score in zip(res.boxes if res.boxes is not None else [], res.txts or (), res.scores or ()):
                xs, ys = [p[0] for p in box], [p[1] for p in box]
                lines.append({"bbox": [min(xs) / self.sx, min(ys) / self.sy, max(xs) / self.sx, max(ys) / self.sy],
                              "text": txt, "score": float(score)})
            self._ocr_lines = lines
        return self._ocr_lines

    def ocr_text_in(self, b):
        lines = [l for l in self.ocr_lines() if center_in(l["bbox"], b, pad=2)]
        lines.sort(key=lambda l: (round(l["bbox"][1] / 4), l["bbox"][0]))  # 위->아래, 왼->오
        return "\n".join(l["text"] for l in lines).strip()

    def region_text(self, b, chars):
        """영역 텍스트: 배정된 pdfplumber 글자 우선, 글자가 없으면 OCR"""
        t = self.chars_text(chars)
        if len("".join(t.split())) >= 2:
            return t, "pdfplumber"
        g = [b[0] - CHAR_PAD, b[1] - CHAR_PAD, b[2] + CHAR_PAD, b[3] + CHAR_PAD]
        if any(inter_ratio((c["x0"], c["top"], c["x1"], c["bottom"]), g) > 0 for c in self.chars):
            # 텍스트 레이어는 있는데 글자가 겹치는 다른 영역에 배정됨 -> OCR 하면 중복
            return t, ("pdfplumber" if t else "none")
        t = self.ocr_text_in(b)
        return t, ("rapidocr" if t else "none")

    def ocr_results_for_table(self, b):
        """RapidTable 입력용 (crop 이미지 픽셀 좌표의 4점 박스, 텍스트, 점수)"""
        x0, y0, _, _ = self.to_px(b)
        boxes, txts, scores = [], [], []
        g = [b[0] - CHAR_PAD, b[1] - CHAR_PAD, b[2] + CHAR_PAD, b[3] + CHAR_PAD]
        words = [w for w in self.pl.extract_words(keep_blank_chars=False)
                 if inter_ratio((w["x0"], w["top"], w["x1"], w["bottom"]), g) > 0.5]
        if words:
            items = [((w["x0"], w["top"], w["x1"], w["bottom"]), w["text"], 1.0) for w in words]
        else:
            items = [(l["bbox"], l["text"], l["score"]) for l in self.ocr_lines() if center_in(l["bbox"], b, pad=2)]
        for (a0, a1, a2, a3), t, s in items:
            px0, py0, px1, py1 = a0 * self.sx - x0, a1 * self.sy - y0, a2 * self.sx - x0, a3 * self.sy - y0
            boxes.append([[px0, py0], [px1, py0], [px1, py1], [px0, py1]])
            txts.append(t)
            scores.append(s)
        if not boxes:
            return None
        return [(np.array(boxes, dtype=np.float32), tuple(txts), tuple(scores))]


def save_crop(ctx, b, rel_dir, name):
    path = CROPS_DIR / rel_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    ctx.crop_img(b).save(path)
    return path.relative_to(OUT_DIR).as_posix()


def extract_table(ctx, b, chars, name):
    """pdfplumber -> RapidTable -> Gemini Vision 대기 순으로 표 추출"""
    region_chars = sum(len(c["text"].strip()) for c in chars)
    attempts = []

    # 1) pdfplumber: 레이아웃 영역 안에서 선 기반 표 탐지
    if region_chars:
        cropped = ctx.pl.crop(clip([b[0] - 2, b[1] - 2, b[2] + 2, b[3] + 2], ctx.w, ctx.h))
        tables = cropped.find_tables()
        if tables:
            t = max(tables, key=lambda t: area(t.bbox))
            rows = t.extract()
            if rows:
                q = table_quality(rows, region_chars)
                q["tool"] = "pdfplumber"
                attempts.append(q)
                if q["ok"]:
                    return rows_to_markdown(rows), "pdfplumber", attempts, False

    # 2) RapidTable: 이미지 기반 구조 인식 + pdfplumber 단어(또는 한국어 OCR)
    ocr_res = ctx.ocr_results_for_table(b)
    if ocr_res:
        try:
            out = ctx.engines.table(ctx.bgr(ctx.crop_img(b)), ocr_results=ocr_res)
            rows = html_to_rows(out.pred_htmls[0] if out.pred_htmls else "")
            if rows:
                ref_chars = region_chars or sum(len("".join(t.split())) for t in ocr_res[0][1])
                # rowspan/colspan 을 같은 값으로 채우므로 coverage 는 1 이상이 될 수 있다
                q = table_quality(rows, ref_chars)
                q["tool"] = "rapidtable"
                attempts.append(q)
                if q["ok"]:
                    # 이미지 기반 구조 인식은 셀 밀림을 검사로 잡기 어려워, 빈 칸이 많으면 Vision 으로도 확인
                    return rows_to_markdown(rows), "rapidtable", attempts, q["empty_ratio"] > 0.4
        except Exception as e:  # 모델 오류는 기록만 하고 Vision 으로 넘긴다
            log.warning("RapidTable 실패 %s: %s", name, e)
            attempts.append({"tool": "rapidtable", "ok": False, "reasons": [f"error: {e}"]})

    # 3) 구조가 깨진 표: 영역 텍스트를 임시로 넣고 Gemini Vision 대기
    text, _ = ctx.region_text(b, chars)
    return text, "fallback_text", attempts, True


def page_blocks_layout(ctx, rel_dir, page_no, warnings):
    res = ctx.engines.layout(ctx.bgr())
    regions = []
    for label, score, box in zip(res.class_names or (), res.scores or (), res.boxes if res.boxes is not None else []):
        b = clip([box[0] / ctx.sx, box[1] / ctx.sy, box[2] / ctx.sx, box[3] / ctx.sy], ctx.w, ctx.h)
        if area(b) <= 0:
            continue
        btype = LABEL_TO_TYPE.get(label, "text")
        if btype not in ("table", "chart", "image") and score < LAYOUT_CONF:
            continue
        if btype == "text" and (b[2] - b[0]) < 25 and (b[3] - b[1]) > 3 * (b[2] - b[0]):
            btype = None  # 페이지 가장자리 세로 쪽 탭(장 제목): 머리말처럼 버림
        regions.append({"label": label, "score": float(score), "bbox": b, "type": btype})

    # 표·차트·이미지 안에 들어간 text 영역은 컨테이너에서 함께 추출하므로 제외 (중복 방지)
    containers = [r for r in regions if r["type"] in ("table", "chart", "image")]
    kept = []
    for r in regions:
        if r["type"] is None:
            continue
        if r["type"] in ("text", "title", "caption") and any(
                inter_ratio(r["bbox"], c["bbox"]) > 0.7 for c in containers):
            continue
        if r["type"] in ("table", "chart", "image") and any(
                c is not r and area(c["bbox"]) > area(r["bbox"])
                and inter_ratio(r["bbox"], c["bbox"]) > 0.8 for c in containers):
            continue  # 더 큰 표·차트·그림 영역에 포함된 중복 탐지 (예: 차트 안 image)
        kept.append(r)

    # 글자 배정: 남긴 영역 + 머리말·꼬리말 영역(배정만 받고 버림 -> leftover 로 다시 나오지 않게)
    skipped = [r for r in regions if r["type"] is None]
    assigned, left = ctx.assign_chars([r["bbox"] for r in kept] + [r["bbox"] for r in skipped])

    # 레이아웃 박스가 문단 끝 줄을 살짝 놓친 경우: 가까운(NEAR_GAP 이내) 텍스트 영역에 붙인다
    text_idx = [i for i, r in enumerate(kept) if r["type"] in ("text", "title", "caption")]
    still_left = []
    for c in left:
        best, best_gap = None, NEAR_GAP
        for i in text_idx:
            b = kept[i]["bbox"]
            gx = max(b[0] - c["x1"], c["x0"] - b[2], 0)
            gy = max(b[1] - c["bottom"], c["top"] - b[3], 0)
            if gx <= 2 and gy <= best_gap:  # 가로로 겹치고 세로로 가까운 영역
                best, best_gap = i, gy
        (assigned[best] if best is not None else still_left).append(c)
    assigned, left = ctx.regroup_by_line(assigned, still_left)

    blocks = []
    page_area = ctx.w * ctx.h
    for r, chars in zip(kept, assigned):
        b, btype = r["bbox"], r["type"]
        idx = len(blocks) + 1
        blk = {"type": btype, "bbox": r1(b), "layout_label": r["label"], "layout_score": round(r["score"], 3)}
        if btype == "table":
            name = f"p{page_no:03d}_b{idx:02d}_table.png"
            text, source, attempts, needs = extract_table(ctx, b, chars, name)
            blk.update(text=text, source=source, table_checks=attempts, needs_vision=needs)
            if needs:
                blk["image_path"] = save_crop(ctx, b, rel_dir, name)
        elif btype in ("chart", "image"):
            text, source = ctx.region_text(b, chars)
            needs = btype == "chart" or area(b) / page_area >= MIN_VISION_AREA
            if not text and not needs:
                continue  # 글자 없는 작은 아이콘·로고
            blk.update(text=text, source=source, needs_vision=needs)
            if needs:
                blk["image_path"] = save_crop(ctx, b, rel_dir, f"p{page_no:03d}_b{idx:02d}_{btype}.png")
        else:
            text, source = ctx.region_text(b, chars)
            if not text:
                continue
            blk.update(text=text, source=source)
            if source == "rapidocr" and len("".join(text.split())) >= OCR_TO_VISION_MIN:
                # 한국어 OCR 은 띄어쓰기가 빠지고 로마숫자 등을 오인식하므로 Vision 으로 다시 옮겨 적는다
                blk["needs_vision"] = True
                blk["image_path"] = save_crop(ctx, b, rel_dir, f"p{page_no:03d}_b{idx:02d}_{btype}.png")
        blocks.append(blk)

    # 어떤 영역과도 겹치지 않은 글자는 누락 방지를 위해 추가
    if sum(1 for c in left if c["text"].strip()) >= 10:
        lb = [min(c["x0"] for c in left), min(c["top"] for c in left),
              max(c["x1"] for c in left), max(c["bottom"] for c in left)]
        text = ctx.chars_text(left)
        if text:
            blocks.append({"type": "text", "bbox": r1(lb), "text": text, "source": "pdfplumber_leftover"})
            warnings.append(f"leftover_chars={sum(1 for c in left if c['text'].strip())}")
    return blocks


def page_blocks_plain(ctx, warnings):
    """1단 텍스트 문서: 페이지 전체 텍스트 1블록 (+ 선 있는 표가 있으면 표 블록)"""
    blocks = []
    tables = ctx.pl.find_tables()
    table_boxes = [t.bbox for t in tables]
    if ctx.chars:
        def keep(obj):
            if obj.get("object_type") != "char":
                return True
            return not any(center_in((obj["x0"], obj["top"], obj["x1"], obj["bottom"]), tb) for tb in table_boxes)
        text = (ctx.pl.filter(keep).extract_text() or "").strip()
        bb = [min(c["x0"] for c in ctx.chars), min(c["top"] for c in ctx.chars),
              max(c["x1"] for c in ctx.chars), max(c["bottom"] for c in ctx.chars)]
        if text:
            blocks.append({"type": "text", "bbox": r1(bb), "text": text, "source": "pdfplumber"})
    for t in tables:
        rows = t.extract()
        if rows:
            q = table_quality(rows, sum(len(c["text"].strip()) for c in ctx.chars_in(t.bbox)))
            blocks.append({"type": "table", "bbox": r1(t.bbox), "text": rows_to_markdown(rows),
                           "source": "pdfplumber", "table_checks": [dict(q, tool="pdfplumber")],
                           "needs_vision": not q["ok"]})
    return blocks


def extract_pdf(path: Path, engines: Engines):
    rel = path.relative_to(DATA_DIR).as_posix()
    group = doc_group(rel)
    rel_dir = Path(rel).with_suffix("").as_posix()
    records = []
    pdf_doc = pdfium.PdfDocument(str(path))
    with pdfplumber.open(path) as pdf:
        for i, pl_page in enumerate(pdf.pages):
            page_no = i + 1
            t0 = time.perf_counter()
            warnings = []
            # dedupe_chars: 굵게 보이려고 같은 글자를 겹쳐 찍은 경우(예: '22002266') 1개만 남긴다
            ctx = PageCtx(pl_page.dedupe_chars(), pdf_doc[i], engines)
            low_text = len(ctx.chars) < LOW_TEXT_CHARS
            if low_text:
                warnings.append("low_text_layer")
            if use_layout(group):
                blocks = page_blocks_layout(ctx, rel_dir, page_no, warnings)
                method = "layout"
            else:
                blocks = page_blocks_plain(ctx, warnings)
                method = "plain"
            if low_text and not any(b.get("text") for b in blocks):
                # 레이아웃이 영역을 못 찾은 스캔·이미지 페이지: 페이지 전체 OCR
                text = ctx.ocr_text_in([0, 0, ctx.w, ctx.h])
                if text:
                    blocks.append({"type": "text", "bbox": r1([0, 0, ctx.w, ctx.h]), "text": text, "source": "rapidocr"})
            records.append({
                "file_name": rel,
                "doc_group": group,
                "page_no": page_no,
                "page_width": round(ctx.w, 1),
                "page_height": round(ctx.h, 1),
                "method": method,
                "used_ocr": ctx.used_ocr,
                "char_count": len(ctx.chars),
                "warnings": warnings,
                "elapsed_sec": round(time.perf_counter() - t0, 2),
                "blocks": blocks,
            })
            log.info("%s p%d blocks=%d %.1fs %s", rel, page_no, len(blocks), records[-1]["elapsed_sec"],
                     ",".join(warnings))
    pdf_doc.close()
    clean_noise(records)
    for r in records:
        if not r["blocks"]:
            r["warnings"].append("empty_page")
        for n, blk in enumerate(r["blocks"], 1):
            blk["block_id"] = f"{rel_dir}#p{r['page_no']}-b{n}"
            blk["order"] = n
    return records


PRINT_SLUG = re.compile(r"\.indd\b|^\s*\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*오[전후]\s*\d")  # 인쇄용 판 정보 줄


def clean_noise(records):
    """검색에 쓸모없는 반복 줄 제거 (Vision 결과 블록은 손대지 않음)

    - 문서의 절반 이상 페이지(최소 3페이지)에 똑같이 나오는 줄: 워터마크, 다운로드 기록, 머리말
    - 인쇄용 판 정보 줄(.indd 파일명·인쇄 시각)
    - 한 글자씩 세로로 쌓인 쪽 탭 (2글자 이하 줄이 4줄 이상 연속)
    """
    n_pages = len(records)
    line_pages = Counter()
    for r in records:
        seen = set()
        for b in r["blocks"]:
            if b.get("source") != "gemini_vision":
                seen.update(ln.strip() for ln in (b.get("text") or "").split("\n") if len(ln.strip()) >= 4)
        line_pages.update(seen)
    # 10페이지 미만 문서는 모든 페이지에 나오는 줄만 (자료 출처처럼 자주 나오는 본문 줄 보호)
    min_k = max(3, n_pages * 0.5) if n_pages >= 10 else n_pages
    repeated = {ln for ln, k in line_pages.items() if n_pages >= 3 and k >= min_k}

    removed = Counter()
    for r in records:
        kept_blocks = []
        for b in r["blocks"]:
            if b.get("source") == "gemini_vision" or b["type"] in ("table", "chart"):
                kept_blocks.append(b)
                continue
            lines = (b.get("text") or "").split("\n")
            keep = [not (ln.strip() in repeated or PRINT_SLUG.search(ln)) for ln in lines]
            i = 0
            while i < len(lines):  # 세로 쪽 탭
                j = i
                while j < len(lines) and 0 < len(lines[j].strip()) <= 2:
                    j += 1
                if j - i >= 4:
                    for k in range(i, j):
                        keep[k] = False
                i = max(j, i + 1)
            if not all(keep):
                removed[r["file_name"]] += keep.count(False)
                b["text"] = "\n".join(ln for ln, k in zip(lines, keep) if k).strip()
            if b["type"] == "image" and not b.get("needs_vision") and len("".join(b.get("text", "").split())) <= 2:
                continue  # '↓' 같은 화살표·기호 그림
            if b.get("text") or b.get("needs_vision") or (b["type"] == "image" and b.get("image_path")):
                kept_blocks.append(b)
        r["blocks"] = kept_blocks
    if removed:
        log.info("noise lines removed: %s / repeated=%s", dict(removed), sorted(repeated)[:10])


def write_jsonl(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def merge_all():
    """문서별 결과(pages/*.jsonl)를 01_data 파일 순서대로 합쳐 extracted_pages.jsonl 생성"""
    out = OUT_DIR / "extracted_pages.jsonl"
    n = 0
    with out.open("w", encoding="utf-8") as f:
        for pdf in sorted(DATA_DIR.rglob("*.pdf")):
            part = PAGES_DIR / Path(pdf.relative_to(DATA_DIR).as_posix()).with_suffix(".jsonl")
            if not part.exists():
                log.warning("결과 없음: %s", part)
                continue
            for line in part.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    f.write(line + "\n")
                    n += 1
    log.info("merged %d pages -> %s", n, out)
    return out, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", help="01_data 기준 상대경로 (생략 시 전체)")
    ap.add_argument("--skip-done", action="store_true", help="pages/ 에 결과가 있는 문서는 건너뜀")
    args = ap.parse_args()

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)])
    for noisy in ("rapid_layout", "rapidocr", "rapid_table", "pdfminer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    pdfs = [DATA_DIR / f for f in args.files] if args.files else sorted(DATA_DIR.rglob("*.pdf"))
    engines = Engines()
    t0 = time.perf_counter()
    for p in pdfs:
        part = PAGES_DIR / Path(p.relative_to(DATA_DIR).as_posix()).with_suffix(".jsonl")
        if args.skip_done and part.exists():
            log.info("skip %s", part)
            continue
        t1 = time.perf_counter()
        records = extract_pdf(p, engines)
        write_jsonl(part, records)
        log.info("DONE %s pages=%d %.1fs", p.name, len(records), time.perf_counter() - t1)
    merge_all()
    log.info("TOTAL %.1fs", time.perf_counter() - t0)


if __name__ == "__main__":
    main()
