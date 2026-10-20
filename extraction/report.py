"""extracted_pages.jsonl 검수 요약 -> 04_extracted/extraction_report.json + 콘솔 출력

문서별 페이지 수, 블록 종류, 추출 도구, 빈 페이지, Vision 대기·완료, 표 품질 검사 실패 사유를 집계한다.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_pdfs as E  # noqa: E402


def main():
    src = E.OUT_DIR / "extracted_pages.jsonl"
    pages = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    per_doc = defaultdict(lambda: {"pages": 0, "chars": 0, "types": Counter(), "sources": Counter(),
                                   "empty_pages": [], "ocr_pages": [], "needs_vision": 0, "vision_done": 0,
                                   "vision_decorative": 0, "leftover_pages": 0})
    table_reasons = Counter()
    tokens = Counter()
    for p in pages:
        d = per_doc[p["file_name"]]
        d["pages"] += 1
        d["doc_group"] = p["doc_group"]
        if not p["blocks"]:
            d["empty_pages"].append(p["page_no"])
        if p["used_ocr"]:
            d["ocr_pages"].append(p["page_no"])
        if any(b["source"] == "pdfplumber_leftover" for b in p["blocks"]):
            d["leftover_pages"] += 1
        for b in p["blocks"]:
            d["types"][b["type"]] += 1
            d["sources"][b["source"]] += 1
            d["chars"] += len(b.get("text") or "")
            if b.get("needs_vision"):
                d["needs_vision"] += 1
            v = b.get("vision")
            if v:
                d["vision_done"] += v.get("result") == "ok"
                d["vision_decorative"] += v.get("result") == "decorative"
                tokens["input"] += v.get("input_tokens") or 0
                tokens["output"] += v.get("output_tokens") or 0
            for chk in b.get("table_checks", []):
                for r in chk.get("reasons", []):
                    table_reasons[f'{chk["tool"]}:{r}'] += 1

    report = {
        "total_pages": len(pages),
        "total_blocks": sum(len(p["blocks"]) for p in pages),
        "vision_tokens": dict(tokens),
        "table_check_failures": dict(table_reasons),
        "documents": {k: {**v, "types": dict(v["types"]), "sources": dict(v["sources"])} for k, v in per_doc.items()},
    }
    out = E.OUT_DIR / "extraction_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"pages={report['total_pages']} blocks={report['total_blocks']} vision_tokens={dict(tokens)}")
    print(f"{'file':58} {'pg':>4} {'text':>5} {'title':>5} {'table':>5} {'chart':>5} {'image':>5} "
          f"{'ocr':>4} {'left':>4} {'wait':>4} {'vis':>4} empty")
    for k, v in per_doc.items():
        t = v["types"]
        print(f"{k[:58]:58} {v['pages']:>4} {t.get('text', 0):>5} {t.get('title', 0):>5} {t.get('table', 0):>5} "
              f"{t.get('chart', 0):>5} {t.get('image', 0):>5} {len(v['ocr_pages']):>4} {v['leftover_pages']:>4} "
              f"{v['needs_vision']:>4} {v['vision_done']:>4} {v['empty_pages']}")
    print("table check failures:", dict(table_reasons))


if __name__ == "__main__":
    main()
