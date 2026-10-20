"""extracted_pages.jsonl -> 사람이 읽기 좋은 Markdown (문서별 1파일 + 목차)

  04_extracted/md/README.md                       목차 (문서별 페이지 수·블록 수)
  04_extracted/md/<01_data 기준 경로>.md          문서별 추출 결과

페이지마다 '## p.N' 제목을 달고, 블록은 순서대로 종류별 형식으로 쓴다.
블록 끝의 `[type · source]` 표시로 어떤 도구로 추출했는지 확인할 수 있다.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_pdfs as E  # noqa: E402

MD_DIR = E.OUT_DIR / "md"
TYPE_LABEL = {"table": "표", "chart": "차트", "image": "그림"}


def block_md(b):
    text = (b.get("text") or "").strip()
    tag = f"<sub>`[{b['type']} · {b['source']}]`</sub>"
    if b["type"] == "title":
        return f"### {' '.join(text.split())}"
    if b["type"] == "caption":
        return f"*{' '.join(text.split())}*  {tag}"
    if b["type"] in TYPE_LABEL:
        body = text if text else "(내용 없음)"
        if b["source"] != "gemini_vision" and not text.lstrip().startswith("|"):
            # 표 형식이 아닌 영역 텍스트(차트 속 글자 등)는 인용 블록으로 줄바꿈 유지
            body = "\n".join(f"> {ln}  " if ln.strip() else ">" for ln in body.splitlines())
        return f"**[{TYPE_LABEL[b['type']]}]** {tag}\n\n{body}"
    # text: 줄바꿈을 유지하려고 줄 끝에 공백 2칸
    return "  \n".join(ln.rstrip() for ln in text.splitlines()) + f"  {tag}"


def main():
    src = E.OUT_DIR / "extracted_pages.jsonl"
    docs = defaultdict(list)
    for line in src.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            docs[r["file_name"]].append(r)

    index = ["# 추출 결과 (Markdown 보기)", "",
             "`extracted_pages.jsonl` 을 문서별로 읽기 좋게 옮긴 것이다. 원본 데이터는 JSONL 이며 이 파일들은 확인용이다.", "",
             "| 문서 | 그룹 | 페이지 | 블록 | 빈 페이지 |", "|---|---|---:|---:|---|"]
    for name, pages in docs.items():
        pages.sort(key=lambda r: r["page_no"])
        out = MD_DIR / Path(name).with_suffix(".md")
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# {Path(name).stem}", "",
                 f"- 원본: `01_data/{name}`",
                 f"- 그룹: `{pages[0]['doc_group']}` · 페이지 {len(pages)} · 추출 방식 `{pages[0]['method']}`", ""]
        empty = []
        for r in pages:
            lines.append(f"## p.{r['page_no']}")
            lines.append("")
            if not r["blocks"]:
                empty.append(r["page_no"])
                lines += ["*(빈 페이지)*", ""]
            for b in r["blocks"]:
                lines += [block_md(b), ""]
            lines += ["---", ""]
        out.write_text("\n".join(lines), encoding="utf-8")
        rel = out.relative_to(MD_DIR).as_posix()
        n_blocks = sum(len(r["blocks"]) for r in pages)
        index.append(f"| [{name}]({rel.replace(' ', '%20')}) | {pages[0]['doc_group']} | {len(pages)} | {n_blocks} | "
                     f"{', '.join(map(str, empty)) or '-'} |")
    (MD_DIR / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"wrote {len(docs)} docs -> {MD_DIR}")


if __name__ == "__main__":
    main()
