# team_golden_set — 팀 골든셋 (ADD 30문항 + 가이드북 10문항 + 기본 positive 30문항)

제공 질문·정답(`02_questions`, `03_answers`)과 **구분해서 평가**하기 위해 직접 만든 골든셋이다. 제공 파일은 수정하지 않았다.
질문과 기준 답안은 검색 DB에 넣지 않는다.

## 구성

| 문서 | 새 case_id | 질문 JSON | 답안 MD |
|---|---|---|---|
| insurance_terms_example_2020 | ADD-IN11 ~ 15 | `02_questions/insurance_terms_example_2020_questions.json` | `03_answers/insurance_terms_example_2020_answers.md` |
| self_employed_debt_2025 | ADD-SE11 ~ 15 | `02_questions/self_employed_debt_2025_questions.json` | `03_answers/self_employed_debt_2025_answers.md` |
| housing_policy_finance_2025 | ADD-HF11 ~ 15 | `02_questions/housing_policy_finance_2025_questions.json` | `03_answers/housing_policy_finance_2025_answers.md` |
| retirement_pension_2025 | ADD-RP11 ~ 15 | `02_questions/retirement_pension_2025_questions.json` | `03_answers/retirement_pension_2025_answers.md` |
| housing_pension_2026 | ADD-HP11 ~ 15 | `02_questions/housing_pension_2026_questions.json` | `03_answers/housing_pension_2026_answers.md` |
| policy_finance_debt_adjustment_2026 | ADD-PF11 ~ 15 | `02_questions/policy_finance_debt_adjustment_2026_questions.json` | `03_answers/policy_finance_debt_adjustment_2026_answers.md` |

### 금융생활 가이드북 (`financial_life_guide.pdf`)

| 세트 | 새 case_id | 질문 JSON | 정답 |
|---|---|---|---|
| 가이드북 positive | POS081 ~ POS090 (10문항, 2문항은 답할 수 없는 질문: POS086, POS090) | `02_questions/positive_life_guide_questions.json` | `03_answers/positive_life_guide_cases.md` / `.jsonl` |

- 제공 가이드북 세트(POS061~080)와 같은 필드·순서이며 `source_file` 필드는 없다. `expected_source_ids`는 `fss-life-guide-pdf-{쪽}`.
- 이 PDF는 한 쪽에 책 2쪽(펼침면)이 들어 있어 `source_pages`(PDF 뷰어 기준)와 책에 인쇄된 쪽번호가 다르다. `source_locator`에 인쇄 쪽을 함께 적었다.
- 생성 코드: `src/golden_life_guide.py`

### 기본 positive (금융용어 모음 + 표준약관)

| 세트 | 새 case_id | 질문 JSON | 정답 |
|---|---|---|---|
| 기본 positive | POS091 ~ POS120 (30문항: 용어집 12 + 약관 18, 기초·중급·심화 각 10) | `02_questions/positive_questions.json` | `03_answers/positive_cases.md` / `.jsonl` |

- 답할 수 없는 질문 6개(20%): POS097·099(기초), POS107·110(중급), POS117·120(심화). `set: "negative"`.
- 제공 질문이 쓰지 않은 약관(05 증권대차, 08 기관간RP, 09 기업어음, 12 수익증권저축, 13·14 해외파생)을 모두 1문항 이상 포함하고, 02 파생상품계좌설정약관은 서식 빈칸(교육 시간) 질문 1개에 썼다.
- 제공 POS 필드에 `source_files`(파일명 목록), `source_pages`(`{파일명: [쪽]}`), `source_locator`를 더했다. `expected_source_ids`는 `{파일명(확장자 제외)}-pdf-{쪽}`.
- 용어집 수치(고액현금거래보고 2,000만원, T+2/T+3 결제국 등)는 문서 기준이다.
- 생성 코드: `src/golden_positive_basic.py` (공통 `build_pos`는 `src/golden_builder.py`)

- `03_answers/additional_cases.jsonl`: ADD 30문항 통합 정답 (제공 `additional_cases.jsonl`과 같은 필드).
- `verification/*.md`: 문서별 자동 검사 결과, 근거 구절, 참고 사항. **"사람이 PDF 원문 확인" 칸(☐)은 아직 비어 있다.**
- `new_golden_set.md`: 작업 계획과 결정 사항.

## 형식 (제공 ADD 세트와 동일)

- 각 문서 5문항: 난이도 basic 1 / intermediate 2 / advanced 2.
- 5문항 중 1문항은 **문서만으로 답할 수 없는 질문**: `set: "negative"`, `category`, `expected_behavior`(`abstain_and_redirect`, `abstain_for_freshness` 등)로 구분한다. 번호는 문서의 마지막 번호(예: ADD-IN15)다.
- `source_pages`는 **PDF 뷰어 기준 1부터 시작**하는 쪽 번호다 (주택연금은 책에 인쇄된 쪽번호와 2쪽 차이).
- `expected_source_ids`는 `{파일명}-pdf-{쪽}` 형식이다.

## 다시 만들기

`src/golden_builder.py`(공통)와 문서별 `src/golden_*.py`(질문 정의)로 같은 파일을 다시 만들 수 있다. 저장소 루트에서:

```bash
python src/golden_self_employed_debt.py
```

- `04_extracted/extracted_pages.jsonl`(없으면 내려받음)과 `03_answers/additional_cases.jsonl`이 필요하다.
- 실행하면 질문 JSON, 답안 MD/JSONL, `verification/*.md`를 만들고, 근거 구절이 추출 텍스트에 없거나 필드·번호가 어긋나면 저장하지 않고 중단한다.
- 보험약관(ADD-IN)은 노트북으로 만들었고 스크립트는 없다. 파일은 `team_golden_set/`에 이미 들어 있다.

## 사용할 때 주의

- 기준 답안의 수치 중 일부는 질문을 위해 계산한 값이다(각 `verification/*.md`의 참고 항목에 표시).
- 박의혁 님 추출 결과에서 발견한 오류 후보는 `verification/`에 적어 두었다 (예: 주택 정책금융 21쪽 각주 조각남, 퇴직연금 17쪽 권역 점유율 표 어긋남).
