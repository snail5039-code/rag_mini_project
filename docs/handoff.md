# 인수인계: 현재 상태와 남은 할 일

2026-10-21 기준입니다. 이 문서만 보고 환경을 준비하고 다음 작업을 이어갈 수 있게 정리했습니다. 프로젝트 전체 설명은 [README.md](../README.md), 설계 상세는 [pipeline.md](./pipeline.md)와 [agent_graph.md](./agent_graph.md)에 있습니다.

## 1. 브랜치

| 브랜치 | 내용 |
|---|---|
| `dev` | **작업 기준 브랜치.** 추출, 파이프라인 설계, 청킹·검색·RAG·Multi-Agent, 팀 골든셋, 평가 결과가 모두 합쳐져 있음 |
| `main` | PDF 추출과 추출 결과 Markdown까지만 있음. `dev`를 검토한 뒤 PR로 합칠 예정 |
| `feature/*` | 각자 작업한 원본 브랜치. 모두 `dev`에 포함됨 |

새 작업은 `dev`에서 브랜치를 따서 진행하고 `dev`로 합칩니다.

## 2. 지금까지 끝난 것

| 단계 | 상태 | 결과물 |
|---|---|---|
| PDF 추출 | 완료 | `04_extracted/extracted_pages.jsonl` (490쪽, 블록 3,277개), 추출 비용은 README 1장 |
| 청킹 | 완료 | `scripts/build_chunks.py` → `05_chunks/` (git 제외, 다시 생성 가능) |
| 임베딩·DB 적재 | 완료 | `parent_child_300_60__gemini-embedding-2_1536` (child 3,041 / parent 965) |
| 검색 평가 | 완료 | 기준 설정 Parent-Child 300/60 + Vector (child MRR 0.885), `06_results/*.json` |
| 기본 RAG · Multi-Agent | 완료 | `rag/basic_rag.py`, `rag/multi_agent.py` |
| 팀 골든셋 | 작성·자동 검사 완료 | `team_golden_set/` 90문항. 사람 원문 확인은 진행 중 |
| 제공 + 팀 골든셋 평가 | 완료 (응답 유형·인용) | `06_results/rag/*both_golden*`, 결과 표는 README 5장 |

## 3. 환경 준비 (새 PC에서 이어받을 때)

### 3-1. 패키지

```bash
pip install -r requirements.txt
```

### 3-2. PostgreSQL + pgvector

로컬 PostgreSQL 17을 쓰며 pgvector 0.8.1을 직접 빌드해 설치했습니다. Windows에는 설치 파일이 없어 빌드가 필요합니다.

1. Visual Studio 2022 Build Tools를 설치합니다. "C++를 사용한 데스크톱 개발" 워크로드가 필요합니다.

```bash
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

2. "x64 Native Tools Command Prompt for VS 2022"를 **관리자 권한**으로 열고 빌드·설치합니다.

```bat
set "PGROOT=C:\Program Files\PostgreSQL\17"
cd %TEMP%
git clone --branch v0.8.1 https://github.com/pgvector/pgvector.git
cd pgvector
nmake /F Makefile.win
nmake /F Makefile.win install
```

Docker를 쓸 수 있다면 `pgvector/pgvector:pg17` 이미지를 다른 포트(예: 5433)로 띄우고 `.env`에 `DATABASE_URL`을 지정하는 방법도 됩니다.

### 3-3. `.env`

저장소 루트에 둡니다(git 제외). 비밀번호·키는 각자 값으로 채웁니다.

```text
GEMINI_API_KEY=...
POSTGRES_USER=postgres
POSTGRES_PASSWORD=...
POSTGRES_DB=rag
```

`POSTGRES_DB`는 반드시 `rag`로 둡니다. 다른 실습 DB를 가리키면 그 DB에 RAG 테이블이 만들어집니다.

### 3-4. DB 초기화와 적재

새 DB에서는 `rag/db.py`의 `connect()`가 vector 타입을 먼저 등록하려다 실패합니다. 그래서 `rag` DB에서 확장을 한 번 먼저 만들어 둡니다.

```sql
-- psql -U postgres -d rag
CREATE EXTENSION IF NOT EXISTS vector;
```

```bash
python scripts/init_db.py
python scripts/build_chunks.py
python scripts/load_chunks.py --method parent_child_300_60
```

`load_chunks.py`는 child 3,041개를 임베딩합니다(약 73만 자). 이미 저장된 `chunk_id`는 다시 임베딩하지 않습니다.

## 4. 평가 실행

```bash
# 제공 180문항만 (기존 방식)
python scripts/run_rag.py --pipeline multi

# 제공 180 + 팀 골든셋 90 (요약은 golden:provided / golden:team 으로 따로 집계)
python scripts/run_rag.py --pipeline basic --golden both
python scripts/run_rag.py --pipeline multi --golden both

# 일부 문항만 확인 (저장 안 함)
python scripts/run_rag.py --pipeline multi --golden team --cases POS091 NEG041 --no-save
```

| 지표 | 의미 |
|---|---|
| `behavior_strict` | 응답 유형이 기대 행동의 첫 번째 유형과 정확히 같음 |
| `behavior_lenient` | 응답 유형이 허용 유형 안에 있음 (예: `answer` 기대에 `correct`도 허용) |
| `context_recall` | 답변 Agent가 받은 parent에 정답 근거가 있는 비율 |
| `citation_hit` / `citation_recall` | 답변이 인용한 근거가 정답 근거를 포함하는지 / 비율 |
| `must_include_rate` | `must_include` 글자 일치율. 제공 기본 positive에서만 의미 있음 |

팀 골든셋의 기본 세트 근거 ID는 `{파일명}-pdf-{쪽}` 형식이라 `run_rag.py`가 청크의 파일·페이지로 비교합니다(`page_ids()`, `PARENT_PAGES`).

## 5. 남은 할 일

우선순위 순서입니다. 비교 실험은 기준 설정 대비 **한 번에 한 요소만** 바꾸고 같은 질문 세트로 다시 평가합니다.

### 5-1. 답변 품질·경로 평가 (담당: 한용님, 다음 작업)

현재 `run_rag.py`는 응답 유형과 인용만 코드로 채점합니다. 다음은 아직 측정하지 않습니다.

1. 답변 내용이 기준 답안과 맞는가 (`must_include`가 문장형이라 글자 일치로는 0점 근처)
2. 답변이 받은 문맥에만 근거했는가 (충실성, 지어낸 수치)
3. `must_not_include`(피해야 할 오류)를 어겼는가
4. Agent가 필요한 단계를 거치고 불필요한 재검색을 피했는가 (Trajectory)

이를 **A. 커스텀 LLM Judge**, **B. Ragas**, **C. 경로(Trajectory) 평가** 세 가지로 나눠 평가합니다. A가 주 지표이고, B는 A를 교차 확인하며, C는 Agent 실행 경로를 봅니다.

#### 공통 입력

평가 대상은 같은 기준 설정에서 돌린 두 실행입니다. 둘 다 같은 방법으로 평가해야 기본 RAG와 Multi-Agent를 비교할 수 있습니다.

| 실행 | 파일 |
|---|---|
| Multi-Agent, 제공 180 + 팀 90 | `06_results/rag/20261021_093905__multi_agent__both_golden.jsonl` |
| 기본 RAG, 제공 180 + 팀 90 | `06_results/rag/20261021_094418__basic_rag__both_golden.jsonl` |

한 줄이 한 문항이고, 평가에 쓰는 필드는 다음과 같습니다.

| 필드 | 내용 |
|---|---|
| `case_id`, `golden`, `question_set`, `question` | 문항 식별. `golden`은 `provided` / `team` |
| `response_type`, `answer` | 최종 응답 유형과 답변 |
| `citations` | 인용한 parent의 `parent_id`, `file_name`, `page_no`, `page_end`, `source_ids` |
| `delivered_parents` | 답변 Agent가 받은 parent의 `parent_id`, `source_ids`, `chars` (**원문 없음**) |
| `trace` | 노드 실행 순서와 단계별 정보 (C에서 사용) |
| `search_rounds`, `stop_reason`, `used_queries`, `usage` | 재검색 횟수, 종료 사유, 사용한 검색어, 호출 수·토큰·시간 |
| `checks` | 이미 계산한 코드 채점 (`behavior_strict`, `context_recall`, `citation_hit` 등) |

- **문맥 원문:** 실행 기록에 없습니다. `parent_id`로 `05_chunks/parent_child_300_60.parents.jsonl`의 `content`나 DB `parent_chunks.content`(같은 `experiment_id`)에서 가져옵니다.
- **기준 답안:** `case_id`로 `03_answers/*.jsonl`(제공)과 `team_golden_set/03_answers/*.jsonl`(팀)에서 `reference_answer`, `must_include`, `must_not_include`, `expected_behavior`를 가져옵니다.
- **결과 저장:** `06_results/eval/<run_id>__<방법>.jsonl`(문항별)과 `.summary.json`(집계)으로 저장합니다. 집계는 `run_rag.py`처럼 `golden:provided` / `golden:team`과 세트별로 나눕니다.
- **고정할 것:** Judge 모델 이름, 프롬프트(기준표), temperature(0)를 결과 파일에 함께 기록합니다. 기준표를 바꾸면 새 버전으로 다시 돌립니다.

#### A. 커스텀 LLM Judge (주 지표)

우리 골든셋 필드(`reference_answer`, `must_include`, `must_not_include`)를 그대로 쓰는 유일한 방법이라 주 지표로 씁니다. 문항당 Judge 호출 1회입니다.

- **입력:** 질문, 기대 행동, 기준 답안, `must_include`, `must_not_include`, 답변 Agent가 받은 문맥(parent 원문, 문서 번호 포함), 최종 답변, 인용 문서 번호.
- **Judge 모델:** 답변 모델(`gemini-3.6-flash`)과 다른 모델을 씁니다(예: `gemini-3.8-flash` 또는 Pro 계열). 같은 모델이 자기 답을 채점하는 편향을 줄이기 위해서입니다.
- **출력:** JSON 구조화 출력으로 받습니다. 항목마다 점수와 이유(근거 문장)를 함께 받습니다.

기준표 초안입니다. 기준을 다듬어도 항목 이름은 유지해 결과를 비교할 수 있게 합니다.

| 항목 | 점수 | 기준 |
|---|---|---|
| `correctness` | 0 / 1 / 2 | 기준 답안의 핵심 사실과 일치하는가 (2: 일치, 1: 일부 누락·부정확, 0: 틀림) |
| `must_include_coverage` | 0~1 | `must_include` 항목 중 의미상 충족한 비율 (항목별 충족 여부도 기록) |
| `must_not_violation` | true / false | `must_not_include`에 해당하는 내용을 말했는가 |
| `faithfulness` | 0 / 1 / 2 | 답변의 사실·수치가 받은 문맥에 있는가 (2: 모두 있음, 1: 일부 없음, 0: 지어낸 핵심 수치·조건 있음) |
| `citation_support` | 0 / 1 / 2 | 인용한 문서가 해당 문장을 실제로 뒷받침하는가 |
| `behavior_appropriate` | true / false | 보류·거절·되묻기 문항에서 이유와 확인할 곳을 적절히 안내했는가 |

- 보류·거절·되묻기가 기대인 문항은 `correctness`·`must_include_coverage`를 그 대응이 맞는지 기준으로 봅니다(예: 문서에 없음을 밝히고 공식 자료를 안내했는가).
- **사람 보정:** 30문항 정도를 직접 채점해 Judge와 비교합니다. 세트별·응답 유형별로 고르게 뽑습니다. 일치율이 낮은 항목은 기준표 문구를 고칩니다.
- **비용:** 문항당 입력은 문맥 포함 약 4천~8천 토큰입니다. Multi-Agent 270문항이면 입력 약 150만~200만 토큰이고, 기본 RAG까지 하면 두 배입니다.

#### B. Ragas (교차 확인)

A의 충실성·정확성 점수가 일반적인 RAG 지표와 크게 어긋나지 않는지 확인하는 용도입니다. 전체가 아니라 **일부 문항(약 50개, 세트별로 고르게)**으로 시작합니다.

- **버전:** 설치된 버전은 `ragas 0.4.3`입니다. 지표는 새 API인 `ragas.metrics.collections`를 씁니다(`Faithfulness`, `ContextRecall`, `FactualCorrectness`, `AnswerRelevancy` 등). `ragas.metrics`의 밑줄 붙은 이름(`_Faithfulness` 등)은 구버전 호환용입니다.
- **모델 연결:** LLM은 `ragas.llms.llm_factory`, 임베딩은 `ragas.embeddings.GoogleEmbeddings`로 Gemini를 연결합니다. 정확한 사용법은 0.4 문서를 확인합니다.
- **입력 매핑:** 질문 → `user_input`, 최종 답변 → `response`, 받은 parent 원문 목록 → `retrieved_contexts`, 기준 답안 → `reference`.
- **추천 지표:**

| 지표 | 비교 대상 |
|---|---|
| `Faithfulness` | A의 `faithfulness` |
| `FactualCorrectness` 또는 `AnswerCorrectness` | A의 `correctness` |
| `ContextRecall` | 코드 채점의 `context_recall` |

- **주의:** 기본 프롬프트가 영어라 한국어 답변에서 점수가 낮게 나올 수 있습니다. 답변을 주장 단위로 나눠 여러 번 호출하므로 A보다 비용이 크고, 실행마다 점수가 조금씩 달라집니다. 보류·거절 문항은 Ragas 지표가 맞지 않으니 `answer`·`correct`가 기대인 문항만 넣습니다.

#### C. 경로(Trajectory) 평가

Agent가 필요한 단계를 거쳤는지, 불필요한 재검색을 했는지 봅니다. 기본 RAG는 경로가 `search → judge_and_answer`로 고정이라 Multi-Agent만 대상입니다.

**C-1. 코드 지표 (LLM 호출 없음, 먼저 할 것)**

`trace`, `search_rounds`, `stop_reason`, `used_queries`, `scope_files`, `checks`로 계산합니다.

| 지표 | 계산 |
|---|---|
| 재검색률 | `search_rounds > 1` 비율 (현재 270문항 중 24개: 2회 11, 3회 13) |
| 재검색 효과 | 재검색한 문항 중 최종 `behavior_strict`·`context_recall`이 통과한 비율 |
| 헛된 재검색 | 재검색했는데 `trace`의 `search` 단계 `new_parents`가 0이거나 `stop_reason=max_rounds`로 끝난 문항 (현재 `max_rounds` 9개) |
| 검색 범위 준수 | `scope_files`가 세트별 범위(`rag/config.py`의 `SCOPE_GROUPS`)와 일치하는가 |
| 검색어 중복 | `used_queries`에 같은 검색어가 반복되는가 |
| 보류·거절 문항의 검색 | 범위 밖·부적절 질문에서 불필요하게 재검색했는가 |

**C-2. AgentEvals 경로 일치**

설치된 `agentevals 0.0.9`의 LangGraph용 함수를 씁니다.

| 함수 | 용도 |
|---|---|
| `agentevals.graph_trajectory.strict.graph_trajectory_strict_match` | 실제 노드 순서가 기대 경로와 정확히 같은가 (LLM 없음) |
| `agentevals.graph_trajectory.llm.create_graph_trajectory_llm_as_judge` | 경로가 논리적이고 효율적인지 LLM이 판단 (`judge=`에 LangChain Gemini 모델 전달) |

- **변환:** `trace`의 `step` 값을 순서대로 뽑아 graph trajectory의 단계 목록으로 바꿉니다. 예: `orchestrator → search → evaluate → feedback → improve → search → evaluate → answer`.
- **기대 경로 정의:**

| 문항 | 기대 경로 |
|---|---|
| 첫 검색으로 답할 수 있는 positive | `orchestrator → search → evaluate → answer` |
| 범위 밖·부적절·되묻기 negative | `orchestrator → search → evaluate → answer` (재검색 없이 판정) |
| 근거가 여러 조항·쪽에 걸친 문항 | 재검색 1회까지 허용 (`subset`/`superset` 성격이라 LLM Judge로 판단) |

- 기대 경로는 골든셋 필드(근거 ID 수, `set`, `category`)로 정하고, 정한 규칙을 결과 파일에 함께 적습니다.

#### 완료 기준

- 두 실행(Multi-Agent, 기본 RAG)에 A와 C-1을 돌린 결과와 요약이 `06_results/eval/`에 있음
- B는 약 50문항 결과와, A와의 점수 비교(상관 또는 불일치 사례)가 있음
- C-2는 Multi-Agent 270문항의 경로 일치율과 불일치 사례가 있음
- 사람 보정 30문항의 Judge 일치율이 있음
- README 5장에 결과 표를 추가하고, 이 문서의 5-1을 "완료"로 바꿈

이 결과가 나오면 5-2(프롬프트 수정)의 기준선이 됩니다. 프롬프트를 고친 뒤 같은 270문항으로 다시 실행하고 A·C로 다시 채점해 비교합니다.

### 5-2. Multi-Agent 보류 판단 프롬프트 수정

팀 골든셋에서 Multi-Agent가 틀린 9문항 중 7문항이 같은 패턴입니다(ADD-HF15, ADD-HP15, ADD-IN15, ADD-PF15, POS086, POS099, POS120).

- **현상:** 답변 본문에는 "문서에서 확인할 수 없다"고 정확히 쓰지만 응답 유형을 `answer`(`correct`)로 붙임. 같은 문항에서 기본 RAG는 대부분 `abstain`.
- **원인:** 2차 답변 프롬프트(`rag/multi_agent.py`의 answer 프롬프트)의 "근거 일부만 확인되면 answer, abstain은 근거가 전혀 없을 때만" 규칙. 제공 세트 2차 실행에서 엄격 점수가 0.883 → 0.800으로 떨어진 원인으로도 추정됩니다.
- **할 일:** "질문의 핵심 요구(수치·최신 정보·개인 정보)에 답할 수 없으면 일부 정보가 있어도 `abstain`" 쪽으로 규칙을 고치고, 같은 270문항으로 재평가합니다. 5-1의 답변 품질 지표를 함께 봐서 유형은 맞췄는데 내용이 나빠지지 않았는지 확인합니다.
- **나머지 2문항:**
  - NEG046 "약관이 바뀌면 언제부터 적용돼?": `clarify`여야 하는데 답함. 평가 Agent의 `ambiguous` 판정 기준을 확인해야 합니다.
  - NEG052 DC형 적립금 ELW 질문: `refuse` 대신 `abstain`. `refuse`와 `abstain`의 경계 기준이 필요합니다.

### 5-3. 추출 오류 후보 재검증 (박의혁)

팀 골든셋 검수에서 나온 항목입니다. 원본 PDF와 대조해 맞으면 추출을 고치고, 해당 문서만 다시 추출·적재합니다.

| 문서·쪽 | 현상 |
|---|---|
| 주택 정책금융 21쪽 | 표 아래 각주가 표 셀로 인식되어 조각남 |
| 퇴직연금 23쪽 | 표 일부 행의 숫자가 섞임 |
| 퇴직연금 17쪽 | '권역별 점유율 추이' 차트 값이 4쪽 본문과 한 칸씩 어긋남 |

```bash
python extraction/extract_pdfs.py --files additional/retirement_pension_2025.pdf
python extraction/vision_fill.py
```

추출이 바뀌면 청크 `chunk_id`가 같아도 내용이 달라지므로, 해당 experiment를 지우고 다시 적재하거나 새 `experiment_id`로 적재합니다.

### 5-4. 팀 골든셋 사람 검수 (한용님)

`team_golden_set/verification/*.md`의 "사람이 PDF 원문 확인" 칸을 채웁니다. 일부 기준 답안 수치는 질문을 위해 계산한 값이라(각 문서의 참고 항목에 표시) 계산식도 함께 확인합니다.

### 5-5. 그 밖에

- 표·차트 child 분할 방식(영역 전체 vs 행 단위) 결정: 차트 Vision 텍스트는 제목·축·수치 표·추세가 한 덩어리입니다.
- `child_k`, `max_parents`, 재검색 횟수, Hybrid 가중치 등 [pipeline.md 5장](./pipeline.md#5-확정이-필요한-항목)의 확정 필요 항목.
- 비용 기록: 추출 비용은 README에 있습니다. 임베딩 적재와 RAG 실행 비용은 아직 정리하지 않았습니다(`06_results/rag/*.summary.json`의 `avg_input_tokens`·`avg_output_tokens` 참고).
- `dev` → `main` PR.

### 5-6. 참고: 평가 방법 비교 (2026-10-21 조사)

5-1에서 A·B·C를 고른 근거입니다. 이 PC에는 `ragas 0.4.3`, `agentevals 0.0.9`, `openevals 0.2.0`, `langsmith`가 설치되어 있고 `deepeval`·`trulens`는 없습니다.

| 방법 | 잘하는 것 | 우리 데이터에 맞는 정도 | 비고 |
|---|---|---|---|
| 커스텀 LLM Judge | 기준 답안 대비 정확성, `must_include` 의미 충족, `must_not_include` 위반, 충실성 | 가장 높음 | 직접 구현, 문항당 1회 호출 → **A** |
| Ragas | 충실성, 답변 정확성, 문맥 정밀도·재현율 | 중간 | 영어 프롬프트, 문항당 여러 번 호출 → **B (교차 확인)** |
| AgentEvals | LangGraph 경로 일치, 경로 LLM Judge | 경로 평가에 적합 | → **C-2** |
| DeepEval | G-Eval(커스텀 기준), 충실성, pytest 연동 | 중간~높음 | 미설치, Gemini 모델 클래스 연결 필요. A를 프레임워크로 옮기고 싶을 때 후보 |
| OpenEvals | RAG용 Judge(groundedness, helpfulness, retrieval relevance) | 중간 | 설치됨, 영어 프롬프트 |
| TruLens | 청크 단위 근거성, 추적 | 낮음~중간 | 미설치, 추적 중심 |
| LangSmith | 실험 비교 UI | 보조 | 계정 필요, 데이터 외부 업로드 |

기획서의 기본 조합 "커스텀 코드 + Ragas + AgentEvals"와 같은 구성이며, 커스텀 Judge를 주 지표로 두고 Ragas를 교차 확인용으로 둔 점만 다릅니다.

## 6. 주의할 점

- 질문과 기준 답안(제공·팀 골든셋 모두)은 검색 DB와 Agent 프롬프트에 넣지 않습니다.
- `page_no`·`source_pages`는 PDF 실제 쪽 순서(1부터)입니다. 가이드북은 PDF 1쪽에 책 2쪽이 들어 있고, 주택연금은 인쇄 쪽번호와 2쪽 차이가 납니다.
- 기본 positive·negative의 검색 범위는 용어집 + 약관뿐입니다. 범위를 넓히면 "자료에 없음"의 기준이 달라집니다.
- 팀 골든셋의 "답할 수 없는 질문"에도 근거 페이지가 적혀 있어, 올바르게 보류해도 인용 Hit가 낮아집니다.
- `.env`, `04_extracted/crops/`, `04_extracted/vision_cache/`, `05_chunks/`, `logs/`는 git에 올리지 않습니다.
