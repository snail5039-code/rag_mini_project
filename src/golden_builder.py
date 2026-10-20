"""team_golden_set 만들기 공통 코드.

문서별 스크립트(golden_<문서>.py)가 질문 목록(cases)을 정의하고 build()를 호출한다.
- 제공 세트 마지막 번호 뒤에서 case_id를 이어 붙인다.
- 필드·번호·질문 중복·근거 구절·(답할 수 없는 질문의) 키워드 부재를 검사한다.
- 질문 JSON, 정답 JSONL/MD, 검증 MD를 team_golden_set/ 아래에 저장한다.

kind="add"  : additional 문서별 세트 (ADD-xx), 제공 정답은 03_answers/additional_cases.jsonl
kind="life" : 금융생활 가이드북 세트 (POS081~), 제공 정답은 03_answers/positive_life_guide_cases.jsonl
"""
import difflib
import json
import re
import urllib.request
from pathlib import Path

EXTRACTED_URL = (
    "https://raw.githubusercontent.com/snail5039-code/rag_mini_project/"
    "refs/heads/main/04_extracted/extracted_pages.jsonl"
)
LEVEL_KO = {"basic": "기초", "intermediate": "중급", "advanced": "심화"}

# 제공 세트의 필드 순서와 같다.
ADD_KEYS = ["difficulty", "source_pages", "source_locator", "question", "reference_answer",
            "must_include", "must_not_include", "case_id", "source_file", "set", "category",
            "expected_behavior", "expected_source_ids"]
LIFE_KEYS = ["case_id", "category", "difficulty", "expected_behavior", "expected_source_ids",
             "source_pages", "source_locator", "must_include", "must_not_include",
             "question", "reference_answer", "set"]

KINDS = {
    "add": {
        "provided": "additional_cases.jsonl", "jsonl": "additional_cases.jsonl", "id_width": 2,
        "keys": ADD_KEYS, "q_name": "{doc}_questions.json", "md_name": "{doc}_answers.md",
        "v_name": "{doc}.md", "source_ids": "{doc}-pdf-{p}",
    },
    "life": {
        "provided": "positive_life_guide_cases.jsonl", "jsonl": "positive_life_guide_cases.jsonl",
        "id_width": 3, "keys": LIFE_KEYS, "q_name": "positive_life_guide_questions.json",
        "md_name": "positive_life_guide_cases.md", "v_name": "positive_life_guide.md",
        "source_ids": "fss-life-guide-pdf-{p}",
    },
}


def find_project_root():
    for folder in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
        if (folder / "01_data").is_dir():
            return folder
    raise FileNotFoundError("01_data 폴더가 있는 rag_mini_project 위치를 찾지 못했습니다.")


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def normalize(text):
    """공백·표 구분선(|)·마크다운 기호를 지워 문구를 비교하기 쉽게 만든다."""
    return re.sub(r"[\s|\\*]", "", text)


def build(pdf_name, id_prefix, md_title, cases, absent_terms=(), notes=(), n_negative=1, kind="add"):
    cfg = KINDS[kind]
    keys = cfg["keys"]
    root = find_project_root()
    team = root / "team_golden_set"
    q_dir, a_dir, v_dir = team / "02_questions", team / "03_answers", team / "verification"
    for d in (q_dir, a_dir, v_dir):
        d.mkdir(parents=True, exist_ok=True)
    doc_id = Path(pdf_name).stem

    # 제공 세트와 추출 결과
    provided = load_jsonl(root / "03_answers" / cfg["provided"])
    if kind == "add":
        provided = [r for r in provided if r["source_file"] == pdf_name]
    last_no = max(int(r["case_id"][len(id_prefix):]) for r in provided)
    # 팀 저장소에는 04_extracted/extracted_pages.jsonl이 있으므로 먼저 쓰고, 없으면 내려받는다.
    extracted = root / "04_extracted" / "extracted_pages.jsonl"
    if not extracted.is_file():
        extracted = root / "artifacts" / "extracted_pages.jsonl"
    if not extracted.is_file():
        extracted.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(EXTRACTED_URL, extracted)
    pages = {}
    for row in load_jsonl(extracted):
        pages[(Path(row["file_name"]).name, row["page_no"])] = "\n".join(b["text"] for b in row["blocks"])
    n_pages = max(p for (f, p) in pages if f == pdf_name)

    for i, c in enumerate(cases):
        c["case_id"] = f"{id_prefix}{last_no + 1 + i:0{cfg['id_width']}d}"
        if kind == "add":
            c["source_file"] = pdf_name
        c["expected_source_ids"] = [cfg["source_ids"].format(doc=doc_id, p=p) for p in c["source_pages"]]

    report, failures = [], []

    def check(ok, message):
        report.append(f"- {'✅' if ok else '❌'} {message}")
        print(("OK   " if ok else "FAIL ") + message)
        if not ok:
            failures.append(message)

    for c in cases:
        check(all(k in c for k in keys), f"{c['case_id']} 필수 필드 {len(keys)}개")
    ids = [c["case_id"] for c in cases]
    check(len(set(ids)) == len(ids) and not set(ids) & {r["case_id"] for r in provided},
          f"case_id {ids[0]}~{ids[-1]}가 서로·제공 세트와 겹치지 않음")
    check(all(1 <= p <= n_pages for c in cases for p in c["source_pages"]), f"source_pages가 PDF 쪽수(1~{n_pages}) 안")
    n_neg = sum(c["set"] == "negative" for c in cases)
    check(n_neg == n_negative, f"답할 수 없는 질문 {n_neg}/{len(cases)}개")
    levels = sorted(c["difficulty"] for c in cases)
    report.append(f"- ℹ️ 난이도 분포: " + ", ".join(f"{LEVEL_KO[k]} {levels.count(k)}" for k in LEVEL_KO))

    provided_q = [(r["case_id"], r["question"]) for r in provided]
    for c in cases:
        best = max(provided_q, key=lambda x: difflib.SequenceMatcher(None, c["question"], x[1]).ratio())
        ratio = difflib.SequenceMatcher(None, c["question"], best[1]).ratio()
        used = sorted({p for r in provided for p in r["source_pages"]} & set(c["source_pages"]))
        check(ratio < 0.5, f"{c['case_id']} 가장 비슷한 제공 질문 {best[0]} (유사도 {ratio:.2f}), 제공 질문과 겹치는 근거 쪽 {used}")

    quote_rows = []
    for c in cases:
        page_text = normalize("\n".join(pages[(pdf_name, p)] for p in c["source_pages"]))
        for q in c["evidence"]:
            found = normalize(q) in page_text
            quote_rows.append((c["case_id"], q, found))
            check(found, f"{c['case_id']} 근거 구절 「{q}」 → 추출 텍스트 {c['source_pages']}쪽에 {'있음' if found else '없음 (PDF 원문으로 직접 확인)'}")

    for t in absent_terms:
        hits = [(f, p) for (f, p), text in pages.items() if normalize(t) in normalize(text)]
        check(not hits, f"핵심어 「{t}」가 23개 PDF 어디에도 없음" + (f" (히트: {hits[:5]})" if hits else ""))

    if failures:
        raise SystemExit(f"검증 실패 {len(failures)}건 — 저장하지 않고 중단합니다.")

    # 저장: 질문 JSON (제공 형식: case_id, difficulty, question)
    q_path = q_dir / cfg["q_name"].format(doc=doc_id)
    q_path.write_text(json.dumps(
        [{"case_id": c["case_id"], "difficulty": c["difficulty"], "question": c["question"]} for c in cases],
        ensure_ascii=False, indent=2), encoding="utf-8")

    # 저장: 정답 JSONL (add: 다른 문서 줄은 유지하고 이 문서 줄만 교체 / life: 이 세트 전체)
    jsonl_path = a_dir / cfg["jsonl"]
    existing = load_jsonl(jsonl_path) if jsonl_path.is_file() else []
    others = [r for r in existing if r.get("source_file") != pdf_name] if kind == "add" else []
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in others + [{k: c[k] for k in keys} for c in cases]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 저장: 정답 MD
    lines = [f"# {md_title} - 팀 골든셋", "",
             "기준 답안은 유일한 정답 문장이 아닙니다. 같은 의미의 정확한 답변도 가능합니다.",
             "PDF 페이지는 뷰어의 1부터 시작하는 번호입니다. 원문의 기준시점과 예시 조건을 따릅니다.", ""]
    for c in cases:
        pages_ko = ", ".join(str(p) for p in c["source_pages"])
        lines += [f"## {c['case_id']} · {LEVEL_KO[c['difficulty']]}", "",
                  f"**질문** {c['question']}", "",
                  f"**기준 답안** {c['reference_answer']}", "",
                  f"근거: {pdf_name} · PDF {pages_ko}쪽 · {c['source_locator']}", "",
                  "확인할 내용:", *[f"- {x}" for x in c["must_include"]], "",
                  "피해야 할 오류:", *[f"- {x}" for x in c["must_not_include"]], ""]
    md_path = a_dir / cfg["md_name"].format(doc=doc_id)
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # 저장: 검증 MD
    v = [f"# {pdf_name} 새 질문 검증", "", "## 자동 검사 결과", *report, "",
         "## 근거 구절 (PDF 원문과 대조)", "",
         "| case_id | 근거 구절 | 추출 텍스트에 있음 | 사람이 PDF 원문 확인 |", "|---|---|---|---|"]
    v += [f"| {cid} | {q} | {'예' if ok else '아니오'} | ☐ |" for cid, q, ok in quote_rows]
    v += ["", "## 참고", *[f"- {n}" for n in notes]]
    v_path = v_dir / cfg["v_name"].format(doc=doc_id)
    v_path.write_text("\n".join(v), encoding="utf-8")

    for p in (q_path, jsonl_path, md_path, v_path):
        print(f"team_golden_set/{p.relative_to(team)}  ({p.stat().st_size:,} bytes)")
    return cases
