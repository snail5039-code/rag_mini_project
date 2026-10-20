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


# ---------------------------------------------------------------------------
# 기본 positive 세트 (용어집 + 표준약관 여러 문서에 걸친 질문, POS091~)
# ---------------------------------------------------------------------------
POS_KEYS = ["case_id", "category", "difficulty", "expected_behavior", "expected_source_ids",
            "source_files", "source_pages", "source_locator", "must_include", "must_not_include",
            "question", "reference_answer", "set"]


def build_pos(cases, first_no, md_title, required_terms_docs=(), n_negative=6, n_glossary=12, n_terms=18,
              absent_terms=(), notes=(), name="positive"):
    """case 필드: source_files(파일명 목록), source_pages({파일명: [쪽]}), evidence([(파일명, 구절)]), group('glossary'|'terms')."""
    root = find_project_root()
    team = root / "team_golden_set"
    q_dir, a_dir, v_dir = team / "02_questions", team / "03_answers", team / "verification"
    for d in (q_dir, a_dir, v_dir):
        d.mkdir(parents=True, exist_ok=True)

    provided = load_jsonl(root / "03_answers" / "positive_cases.jsonl")
    extracted = root / "04_extracted" / "extracted_pages.jsonl"
    if not extracted.is_file():
        extracted = root / "artifacts" / "extracted_pages.jsonl"
    if not extracted.is_file():
        extracted.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(EXTRACTED_URL, extracted)
    pages = {}
    for row in load_jsonl(extracted):
        pages[(Path(row["file_name"]).name, row["page_no"])] = "\n".join(b["text"] for b in row["blocks"])
    n_pages = {}
    for (f, p) in pages:
        n_pages[f] = max(n_pages.get(f, 0), p)

    for i, c in enumerate(cases):
        c["case_id"] = f"POS{first_no + i:03d}"
        c["expected_source_ids"] = [f"{Path(f).stem}-pdf-{p}" for f in c["source_files"] for p in c["source_pages"][f]]

    report, failures = [], []

    def check(ok, message):
        report.append(f"- {'✅' if ok else '❌'} {message}")
        print(("OK   " if ok else "FAIL ") + message)
        if not ok:
            failures.append(message)

    for c in cases:
        check(all(k in c for k in POS_KEYS) and c["group"] in ("glossary", "terms"), f"{c['case_id']} 필수 필드 {len(POS_KEYS)}개")
    ids = [c["case_id"] for c in cases]
    taken = {r["case_id"] for r in provided} | {f"POS{n:03d}" for n in range(61, first_no)}
    check(len(set(ids)) == len(ids) and not set(ids) & taken,
          f"case_id {ids[0]}~{ids[-1]}가 서로·제공 세트(POS001~{first_no - 1:03d})와 겹치지 않음")
    check(all(set(c["source_pages"]) == set(c["source_files"]) and
              all(1 <= p <= n_pages.get(f, 0) for f in c["source_files"] for p in c["source_pages"][f])
              for c in cases), "source_pages가 각 PDF 쪽수 안")
    n_neg = sum(c["set"] == "negative" for c in cases)
    check(n_neg == n_negative, f"답할 수 없는 질문 {n_neg}/{len(cases)}개")
    levels = [c["difficulty"] for c in cases]
    report.append("- ℹ️ 난이도 분포: " + ", ".join(f"{LEVEL_KO[k]} {levels.count(k)}" for k in LEVEL_KO))
    for k in LEVEL_KO:
        n = sum(c["set"] == "negative" for c in cases if c["difficulty"] == k)
        report.append(f"- ℹ️ {LEVEL_KO[k]} 중 답할 수 없는 질문 {n}개")
    n_g = sum(c["group"] == "glossary" for c in cases)
    check(n_g == n_glossary and len(cases) - n_g == n_terms, f"용어집 {n_g} / 약관 {len(cases) - n_g} (목표 {n_glossary} / {n_terms})")
    for doc in required_terms_docs:
        n = sum(doc in c["source_files"] for c in cases)
        check(n >= 1, f"{doc} 근거 질문 {n}개 (1개 이상 필요)")

    provided_q = [(r["case_id"], r["question"]) for r in provided]
    for c in cases:
        best = max(provided_q, key=lambda x: difflib.SequenceMatcher(None, c["question"], x[1]).ratio())
        ratio = difflib.SequenceMatcher(None, c["question"], best[1]).ratio()
        check(ratio < 0.5, f"{c['case_id']} 가장 비슷한 제공 질문 {best[0]} (유사도 {ratio:.2f})")

    quote_rows = []
    for c in cases:
        for f, q in c["evidence"]:
            page_text = normalize("\n".join(pages[(f, p)] for p in c["source_pages"][f]))
            found = normalize(q) in page_text
            quote_rows.append((c["case_id"], f, q, found))
            check(found, f"{c['case_id']} 근거 구절 「{q}」 → {f} {c['source_pages'][f]}쪽 추출 텍스트에 {'있음' if found else '없음 (PDF 원문으로 직접 확인)'}")

    for t in absent_terms:
        is_re = t.startswith("re:")
        pat = t[3:] if is_re else normalize(t)
        hits = [(f, p) for (f, p), text in pages.items()
                if (re.search(pat, normalize(text)) if is_re else pat in normalize(text))]
        check(not hits, f"핵심어 「{t}」가 23개 PDF 어디에도 없음" + (f" (히트: {hits[:5]})" if hits else ""))

    if failures:
        raise SystemExit(f"검증 실패 {len(failures)}건 — 저장하지 않고 중단합니다.")

    q_path = q_dir / f"{name}_questions.json"
    q_path.write_text(json.dumps(
        [{"case_id": c["case_id"], "difficulty": c["difficulty"], "question": c["question"]} for c in cases],
        ensure_ascii=False, indent=2), encoding="utf-8")
    jsonl_path = a_dir / f"{name}_cases.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps({k: c[k] for k in POS_KEYS}, ensure_ascii=False) + "\n")

    lines = [f"# {md_title} - 팀 골든셋", "",
             "기준 답안은 유일한 정답 문장이 아닙니다. 같은 의미의 정확한 답변도 가능합니다.",
             "PDF 페이지는 뷰어의 1부터 시작하는 번호입니다. 원문의 기준시점과 예시 조건을 따릅니다.", ""]
    for c in cases:
        src = " / ".join(f"{f} · PDF {', '.join(str(p) for p in c['source_pages'][f])}쪽" for f in c["source_files"])
        lines += [f"## {c['case_id']} · {LEVEL_KO[c['difficulty']]}" + (" · 답할 수 없는 질문" if c["set"] == "negative" else ""), "",
                  f"**질문** {c['question']}", "",
                  f"**기준 답안** {c['reference_answer']}", "",
                  f"근거: {src} · {c['source_locator']}", "",
                  "확인할 내용:", *[f"- {x}" for x in c["must_include"]], "",
                  "피해야 할 오류:", *[f"- {x}" for x in c["must_not_include"]], ""]
    md_path = a_dir / f"{name}_cases.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    v = [f"# {md_title} 새 질문 검증", "", "## 자동 검사 결과", *report, "",
         "## 근거 구절 (PDF 원문과 대조)", "",
         "| case_id | 파일 | 근거 구절 | 추출 텍스트에 있음 | 사람이 PDF 원문 확인 |", "|---|---|---|---|---|"]
    v += [f"| {cid} | {f} | {q} | {'예' if ok else '아니오'} | ☐ |" for cid, f, q, ok in quote_rows]
    v += ["", "## 참고", *[f"- {n}" for n in notes]]
    v_path = v_dir / f"{name}_cases.md"
    v_path.write_text("\n".join(v), encoding="utf-8")
    for p in (q_path, jsonl_path, md_path, v_path):
        print(f"team_golden_set/{p.relative_to(team)}  ({p.stat().st_size:,} bytes)")
    return cases


# ---------------------------------------------------------------------------
# 기본 negative 세트 (NEG041~): 제공 NEG001~040과 같은 필드에 source_files/source_pages/source_locator를 더했다.
# ---------------------------------------------------------------------------
NEG_KEYS = ["case_id", "category", "difficulty", "expected_behavior", "expected_source_ids",
            "source_files", "source_pages", "source_locator", "must_include", "must_not_include",
            "question", "reference_answer", "set"]


def build_neg(cases, first_no, md_title, n_adversarial=3, absent_terms=(), notes=(), name="negative"):
    """case 필드: source_files([]도 가능), source_pages({파일명: [쪽]}), evidence([(파일명, 구절)] - 근거가 있는 경우만)."""
    root = find_project_root()
    team = root / "team_golden_set"
    q_dir, a_dir, v_dir = team / "02_questions", team / "03_answers", team / "verification"
    for d in (q_dir, a_dir, v_dir):
        d.mkdir(parents=True, exist_ok=True)
    provided = load_jsonl(root / "03_answers" / "negative_cases.jsonl")
    extracted = root / "04_extracted" / "extracted_pages.jsonl"
    if not extracted.is_file():
        extracted = root / "artifacts" / "extracted_pages.jsonl"
    pages, n_pages = {}, {}
    for row in load_jsonl(extracted):
        f = Path(row["file_name"]).name
        pages[(f, row["page_no"])] = "\n".join(b["text"] for b in row["blocks"])
        n_pages[f] = max(n_pages.get(f, 0), row["page_no"])

    for i, c in enumerate(cases):
        c["case_id"] = f"NEG{first_no + i:03d}"
        c["set"] = "negative"
        c["expected_source_ids"] = [f"{Path(f).stem}-pdf-{p}" for f in c["source_files"] for p in c["source_pages"][f]]

    report, failures = [], []

    def check(ok, message):
        report.append(f"- {'✅' if ok else '❌'} {message}")
        print(("OK   " if ok else "FAIL ") + message)
        if not ok:
            failures.append(message)

    for c in cases:
        check(all(k in c for k in NEG_KEYS), f"{c['case_id']} 필수 필드 {len(NEG_KEYS)}개")
    ids = [c["case_id"] for c in cases]
    check(len(set(ids)) == len(ids) and not set(ids) & {r["case_id"] for r in provided},
          f"case_id {ids[0]}~{ids[-1]}가 서로·제공 세트(NEG001~{first_no - 1:03d})와 겹치지 않음")
    check(all(set(c["source_pages"]) == set(c["source_files"]) and
              all(1 <= p <= n_pages.get(f, 0) for f in c["source_files"] for p in c["source_pages"][f])
              for c in cases), "source_pages가 각 PDF 쪽수 안")
    n_adv = sum(c["difficulty"] == "adversarial" for c in cases)
    check(n_adv == n_adversarial, f"adversarial {n_adv}개 (목표 {n_adversarial})")
    cats = {}
    for c in cases:
        cats[c["category"]] = cats.get(c["category"], 0) + 1
    report.append("- ℹ️ 카테고리 분포: " + ", ".join(f"{k} {v}" for k, v in cats.items()))

    provided_q = [(r["case_id"], r["question"]) for r in provided]
    for c in cases:
        best = max(provided_q, key=lambda x: difflib.SequenceMatcher(None, c["question"], x[1]).ratio())
        ratio = difflib.SequenceMatcher(None, c["question"], best[1]).ratio()
        check(ratio < 0.5, f"{c['case_id']} 가장 비슷한 제공 질문 {best[0]} (유사도 {ratio:.2f})")

    quote_rows = []
    for c in cases:
        for f, q in c["evidence"]:
            page_text = normalize("\n".join(pages[(f, p)] for p in c["source_pages"][f]))
            found = normalize(q) in page_text
            quote_rows.append((c["case_id"], f, q, found))
            check(found, f"{c['case_id']} 근거 구절 「{q}」 → {f} {c['source_pages'][f]}쪽 추출 텍스트에 {'있음' if found else '없음 (PDF 원문으로 직접 확인)'}")

    for t in absent_terms:
        hits = [(f, p) for (f, p), text in pages.items() if normalize(t) in normalize(text)]
        check(not hits, f"핵심어 「{t}」가 23개 PDF 어디에도 없음" + (f" (히트: {hits[:5]})" if hits else ""))

    if failures:
        raise SystemExit(f"검증 실패 {len(failures)}건 — 저장하지 않고 중단합니다.")

    q_path = q_dir / f"{name}_questions.json"
    q_path.write_text(json.dumps(
        [{"case_id": c["case_id"], "difficulty": c["difficulty"], "question": c["question"]} for c in cases],
        ensure_ascii=False, indent=2), encoding="utf-8")
    jsonl_path = a_dir / f"{name}_cases.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps({k: c[k] for k in NEG_KEYS}, ensure_ascii=False) + "\n")
    lines = [f"# {md_title} - 팀 골든셋", "",
             "기준 답안은 유일한 정답 문장이 아닙니다. 같은 의미의 정확한 답변도 가능합니다.", ""]
    for c in cases:
        src = " / ".join(f"{f} · PDF {', '.join(str(p) for p in c['source_pages'][f])}쪽" for f in c["source_files"]) or "근거 문서 없음(문서에 없는 질문)"
        lines += [f"## {c['case_id']} · {c['category']} · {c['expected_behavior']}", "",
                  f"**질문** {c['question']}", "", f"**기준 답안** {c['reference_answer']}", "",
                  f"근거: {src} · {c['source_locator']}", "",
                  "확인할 내용:", *[f"- {x}" for x in c["must_include"]], "",
                  "피해야 할 오류:", *[f"- {x}" for x in c["must_not_include"]], ""]
    md_path = a_dir / f"{name}_cases.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    v = [f"# {md_title} 새 질문 검증", "", "## 자동 검사 결과", *report, "",
         "## 근거 구절 (PDF 원문과 대조)", "",
         "| case_id | 파일 | 근거 구절 | 추출 텍스트에 있음 | 사람이 PDF 원문 확인 |", "|---|---|---|---|---|"]
    v += [f"| {cid} | {f} | {q} | {'예' if ok else '아니오'} | ☐ |" for cid, f, q, ok in quote_rows]
    v += ["", "## 참고", *[f"- {n}" for n in notes]]
    v_path = v_dir / f"{name}_cases.md"
    v_path.write_text("\n".join(v), encoding="utf-8")
    for p in (q_path, jsonl_path, md_path, v_path):
        print(f"team_golden_set/{p.relative_to(team)}  ({p.stat().st_size:,} bytes)")
    return cases
