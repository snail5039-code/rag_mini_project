# new_golden_set.md — 팀 골든셋 작성 계획 (v3)

> 작성: 2026-10-20 · 상태: **아직 골든셋을 만들지 않았다.** 2차 답변까지 반영했고, 아래 "8. 남은 확인 사항" 3개에 답하면 하나씩 진행한다.
> 골든셋은 사용자 혼자 담당한다 (다른 팀원은 다른 작업 중이므로 담당 문서 분담은 고려하지 않는다).

## 1. 확정된 작업 내용

- **제공된 모든 질문 세트의 절반 분량을 새 질문으로 만든다.** 제공 질문과 겹치지 않는 새 질문이어야 한다.
- 근거는 PDF 원문과 박의혁 님의 `04_extracted/extracted_pages.jsonl`을 함께 사용한다.
- 결과는 `rag_mini_project/team_golden_set/`에 **제공 세트와 같은 파일 형식**으로 저장한다. 제공 원본(`02_questions`, `03_answers`)은 수정하지 않는다.
- **case_id는 기존 번호 뒤에서 이어서 붙인다.**
- **새 질문의 20%는 문서만으로 답할 수 없는 유형**으로 만든다.
- README 요건도 만족시킨다: 질문 유형 혼합(용어 정의·조건 비교·표 해석), 질문·기준 답변·근거 구절·파일명·페이지 기록, PDF 원문 대조 검수, 질문·답안은 검색 DB에 넣지 않음, 제공 세트와 구분해서 평가.

## 2. 근거 자료 확인 결과

`extracted_pages.jsonl`(490줄 = 490쪽)을 받아 확인했다. 저장소: `snail5039-code/rag_mini_project`.

| 항목 | 내용 |
|---|---|
| 범위 | 23개 PDF 전부 (additional 6, 약관 15, 용어집, 가이드북) |
| 줄 단위 | 1줄 = PDF 1페이지. `page_no`는 1부터이고 PDF 쪽수와 일치 |
| 줄의 key | `file_name`(예: `additional/housing_pension_2026.pdf`), `doc_group`, `page_no`, `method`, `used_ocr`, `char_count`, `warnings`, `elapsed_sec`, `blocks` |
| `blocks` | 블록별 `type`(text/title/table/image/chart/caption), `bbox`, `text`, `block_id`, `order` |
| 이미지·차트 블록 | `text`에 이미지 내용을 글로 옮긴 결과가 들어 있다 |
| 용어집·약관 | 쪽당 text 블록 1개 (표·이미지 없음) |
| 주의 | OCR 사용 쪽이 많다 (주택연금 34/119쪽, 가이드북 38/43쪽). 이미지·차트 해석은 모델이 읽은 것이라 오류 가능성이 있다. **숫자·표 값은 반드시 PDF 원문과 대조한다.** |

## 3. 제공 세트의 형식 (그대로 따라 만들 것)

### 3-1. 질문 파일 `02_questions/*.json`
- ADD·가이드북·POS: `[{"case_id", "difficulty"(basic/intermediate/advanced), "question"}, ...]`
- NEG: `[{"case_id", "question"}, ...]` (difficulty 없음)

### 3-2. 정답 파일
- **JSONL** (한 줄에 한 문항)
  - ADD 필드: `case_id, difficulty, question, reference_answer, must_include, must_not_include, source_file, source_pages, source_locator, set, category, expected_behavior, expected_source_ids`
  - 가이드북 필드: ADD에서 `source_file`만 없음
  - POS/NEG 필드: `case_id, category, difficulty, expected_behavior, expected_source_ids, must_include, must_not_include, question, reference_answer, set` (`source_file`·`source_pages` 없음)
  - ADD 값: `set: positive`, `category: grounded_qa`, `expected_behavior: answer_with_citation`, `expected_source_ids: ["{파일명}-pdf-{쪽}"]`
- **Markdown** (사람이 읽는 용도): 문항마다 `## {case_id} · {난이도}` / 질문 / 기준 답안 / 근거(파일명·PDF n쪽·위치) / 확인할 내용(= must_include) / 피해야 할 오류(= must_not_include)

## 4. 만들 분량과 번호 (확정 + 제안)

| 세트 | 제공 개수 | 새로 만들 개수 | 새 case_id | 근거 PDF |
|---|---|---|---|---|
| ADD-HP | 10 | 5 | ADD-HP11 ~ HP15 | housing_pension_2026 |
| ADD-HF | 10 | 5 | ADD-HF11 ~ HF15 | housing_policy_finance_2025 |
| ADD-IN | 10 | 5 | ADD-IN11 ~ IN15 | insurance_terms_example_2020 |
| ADD-PF | 10 | 5 | ADD-PF11 ~ PF15 | policy_finance_debt_adjustment_2026 |
| ADD-RP | 10 | 5 | ADD-RP11 ~ RP15 | retirement_pension_2025 |
| ADD-SE | 10 | 5 | ADD-SE11 ~ SE15 | self_employed_debt_2025 |
| 가이드북 positive | 20 (POS061~080) | 10 | **POS081 ~ POS090** | financial_life_guide |
| 기본 positive (용어집+약관) | 60 (POS001~060) | 30 | **POS091 ~ POS120** | 용어집 + 표준약관 15개 |
| 기본 negative | 40 (NEG001~040) | 20 | NEG041 ~ NEG060 | 용어집 + 표준약관 |
| **합계** | 180 | **90** | | |

난이도 배분(제공 ADD 세트의 비율 basic 2 : intermediate 3 : advanced 5 기준):
- ADD 문서당 5문항: basic 1 / intermediate 2 / advanced 2
- 가이드북 10, POS 30은 제공 세트의 난이도 비율을 따른다 (작성 시 `difficulty` 분포를 확인).

## 5. "답할 수 없는 질문 20%" 처리 (확정: 70문항의 20% = 14문항, 문서 번호 안에 배치)

**계산**
- 답이 문서에 있는 positive 계열(ADD 30 + 가이드북 10 + POS 30 = **70문항**)의 20%에 해당하는 **14문항**을 "답할 수 없는 질문"으로 만든다.

| 세트 | 새 문항 | 그중 답할 수 없는 질문 |
|---|---|---|
| ADD 문서당 | 5 | 1 (6개 문서 합 6) |
| 가이드북 | 10 | 2 |
| 기본 positive | 30 | 6 |
| 기본 negative | 20 | (전부 이미 답하지 않거나 보정해야 하는 유형이라 별도 비율 없음) |

**유형 (README의 "확인·보류 등의 대응")**: 제공 NEG의 `expected_behavior`를 따른다. 예: `abstain_and_redirect`, `abstain_and_request_source`, `ask_clarifying_question`, `correct_with_citation`(잘못된 전제 정정), `refuse_personalized_recommendation`. 이유와 기대 대응은 `reference_answer`·`must_include`에 적는다.

**형식 (확정)**
- 문서의 5문항 중 **마지막 1개**를 답할 수 없는 질문으로 한다. 예: `ADD-HP15`. case_id 번호는 문서 순서를 그대로 이어간다.
- 구분은 필드로 한다: `set: "negative"`, `category`(예: `unsupported_corpus`, `insufficient_context`, `false_premise`), `expected_behavior`(위 목록).
- 그 문서에서 실제로 다루는 주제에 가깝지만 문서에 없는 정보(예: 문서에 없는 최신 수치, 개인 계약 정보, 문서에 없는 조건)를 묻는 질문으로 만든다. 문서와 무관한 질문은 만들지 않는다.
- 근거 필드: 답할 수 없는 질문도 "문서의 어느 쪽에서 확인했을 때 답이 없는지/관련 내용이 어디까지인지"를 `source_file`·`source_pages`·`source_locator`에 적는다 (정정형 질문은 인용 근거도 함께).

## 6. 저장 위치와 파일

```
rag_mini_project/team_golden_set/
  02_questions/
    housing_pension_2026_questions.json        (ADD-HP11~15)
    housing_policy_finance_2025_questions.json
    insurance_terms_example_2020_questions.json
    policy_finance_debt_adjustment_2026_questions.json
    retirement_pension_2025_questions.json
    self_employed_debt_2025_questions.json
    positive_life_guide_questions.json         (POS081~090)
    positive_questions.json                    (POS091~120)
    negative_questions.json                    (NEG041~060)
  03_answers/
    housing_pension_2026_answers.md ... (ADD 6개 문서)
    additional_cases.jsonl                     (ADD 30문항 통합)
    positive_life_guide_cases.md / .jsonl
    positive_cases.md / .jsonl
    negative_cases.md / .jsonl
  verification.md   (문항별 PDF 원문 대조 결과)
```
- 파일명은 제공 세트와 같게 하고 폴더로만 구분한다.

## 7. 문항 작성 절차 (세트 1개 기준)

1. PDF와 `extracted_pages.jsonl`로 해당 문서의 쪽별 내용을 읽는다 (표·이미지 많은 쪽 우선).
2. 제공 질문의 근거 쪽과 유형을 정리해 **겹치지 않는 쪽·주제**를 고른다. 의미가 비슷한 질문도 피한다.
3. 새 질문을 쓴다. 제공 세트처럼 일상 말투의 상황형 질문으로 쓰고, positive는 정답이 문서 안에 있어야 한다. 용어 정의·조건 비교·표 해석·(있으면) 그림·차트 해석을 섞는다.
4. 문항마다 `reference_answer`, `must_include`(핵심 문구·수치), `must_not_include`(흔한 오해), `source_pages`, `source_locator`를 쓴다.
5. **PDF 원문과 대조 검수**한다. 숫자·표 값·단위는 추출 결과가 아니라 PDF 쪽 화면 기준으로 확인하고 `verification.md`에 기록한다.
6. 파일(질문 JSON, 답안 MD, JSONL)을 만들고 자동 검사한다: JSON 유효성, `case_id` 중복·연속성, `source_pages` 범위, 필드 누락, 제공 세트와 질문 중복 여부.
7. **한 세트씩 만들어 보여 주고 승인받은 뒤 다음으로 넘어간다.**

제안 진행 순서: ① 보험약관(ADD-IN, 9쪽, 시범) → ② 나머지 ADD 5개 → ③ 가이드북 → ④ 기본 positive → ⑤ 기본 negative

## 8. 확정 사항과 남은 확인 사항

### 확정
- 20%는 positive 계열 70문항 기준 **14문항** (ADD 6 + 가이드북 2 + 기본 positive 6). NEG 20문항에는 별도 비율을 적용하지 않는다.
- 답할 수 없는 질문은 **문서 번호 안에 둔다** (예: `ADD-HP15`, `set: negative`로 구분).
- 작성 방식: **질문·답변 초안은 Claude가 쓰고, 한 세트씩 보여 주면 사용자가 읽고 수정·승인한다.** 승인 후 다음 세트로 넘어간다.

### 남은 확인 (3개)

**(A) 기본 positive 30문항의 약관 배분 — 확정: 안 쓰인 약관 6개(05, 08, 09, 12, 13, 14)에서 각 1문항 이상 포함, 용어집 12 / 약관 18** (아래는 근거 설명)
- 제공 POS/NEG 정답의 근거 ID(`kofia-terms-120-...` 등)를 질문 주제와 맞춰 보면 쓰인 약관은 9개다: 01 매매거래계좌, 02 파생상품계좌, 03 외화증권, 04 신용거래, 06 연금저축, 07 대고객 RP, 10 전자금융, 11 외국집합투자증권, 15 FX마진.
- **근거로 쓰인 적이 없는 약관 6개**: 05 증권대차, 08 기관간 RP, 09 기업어음, 12 수익증권저축, 13 해외파생 중개계좌, 14 해외파생 총괄계좌. (ID 코드와 파일 대응은 질문 주제로 추정한 것이다.)
- 제안: 새 positive 30문항에 이 6개 약관에서 **각 1문항 이상** 넣어 약관 15개를 모두 평가 범위에 포함하고, 나머지는 용어집 약 12 / 약관 약 18로 배분한다.

**(B) POS/NEG 새 문항의 근거 표기 방식**
- 제공 POS/NEG의 `expected_source_ids`는 `fsc-glossary-1697`, `kofia-terms-120-1785-006` 같은 **원래 데이터베이스의 레코드 번호**다. 파일명·쪽이 없고, 레코드 번호가 어떤 규칙인지 알 수 없어서 **새 문항에는 같은 번호를 만들 수 없다.**
- 제안: 새 문항은 ADD처럼 `source_file`, `source_pages`, `expected_source_ids: ["{파일명}-pdf-{쪽}"]`로 적는다. 장점은 쪽 단위로 검색 평가를 할 수 있다는 것이고, 단점은 제공 POS/NEG와 근거 표기가 달라진다는 것이다.
- 이렇게 하면 평가 때 제공 POS/NEG는 레코드 ID로, 새 문항은 파일+쪽으로 채점해야 한다 (두 세트를 구분해서 평가하라는 README 지침과도 맞다).

**(C) 새 NEG와 "답할 수 없는 질문"의 검색 범위 기준**
- README: 기본 NEG의 "자료에 없음"은 *용어집+표준약관만 검색한다*는 조건이다. 금융생활 가이드북·추가 PDF까지 검색하면 답할 수 있는 질문이 생길 수 있어서 검색 범위를 구분하라고 한다.
- 질문하신 대로 **실제 서비스에서 Agent가 23개 PDF를 모두 검색한다면**, 어떤 질문이 "자료에 없음"인지는 검색 범위에 따라 달라진다. 예를 들어 "퇴직연금 수수료는?"은 용어집+약관만 보면 답이 없지만 전체 PDF를 보면 답이 있다.
- 제안: **새로 만드는 NEG 20문항과 답할 수 없는 질문 14문항은 23개 PDF 전체에서도 답이 없는 질문**으로 만든다. 만든 뒤 `extracted_pages.jsonl` 전체에서 키워드를 검색해 정말 답이 없는지 확인한다. 이러면 검색 범위를 "용어집+약관"으로 하든 "23개 전체"로 하든 정답 라벨이 유효하다.
- 확인할 점: 최종 Agent의 검색 범위를 (1) 세트별로 나눌지, (2) 23개 전체로 할지 정해져 있는가? 정해지지 않았다면 위 제안(어느 범위에서도 유효한 질문)대로 간다.
