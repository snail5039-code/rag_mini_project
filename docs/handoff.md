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

### 5-1. 답변 품질 평가 방법 확정과 실행 (다음 작업)

현재 채점은 응답 유형과 인용만 봅니다. 다음 세 가지는 아직 측정하지 않습니다.

1. 답변 내용이 기준 답안과 맞는가 (`must_include`가 문장형이라 글자 일치로는 0점 근처)
2. 답변이 받은 문맥에만 근거했는가 (충실성, 지어낸 수치)
3. `must_not_include`(피해야 할 오류)를 어겼는가

평가 방법 후보를 비교한 결과입니다. 이 PC에는 `ragas 0.4.3`, `agentevals 0.0.9`, `openevals 0.2.0`이 설치되어 있고 `deepeval`·`trulens`는 없습니다.

| 방법 | 잘하는 것 | 우리 데이터에 맞는 정도 | 비고 |
|---|---|---|---|
| 커스텀 LLM Judge (Gemini, 고정 기준표) | 기준 답안 대비 정확성, `must_include` 의미 충족, `must_not_include` 위반, 충실성, 인용 근거 | 가장 높음. 골든셋 필드를 그대로 씀 | 직접 구현. 문항당 1회 호출. 기획서의 "기준표 고정 LLM Judge" |
| Ragas | 충실성, 답변 정확성, 문맥 정밀도·재현율 | 중간. `must_include`·`must_not_include` 미사용 | 기본 프롬프트 영어, 문항당 여러 번 호출, 실행마다 점수 변동 |
| DeepEval | G-Eval(커스텀 기준), 충실성, pytest 연동 | 중간~높음 | 기본 OpenAI라 Gemini 모델 클래스 연결 필요 |
| OpenEvals | RAG용 Judge(groundedness, helpfulness, retrieval relevance) | 중간 | LangChain 모델로 Gemini 연결 쉬움, 프롬프트 영어 |
| AgentEvals | LangGraph 실행 경로 일치(strict / unordered / subset / superset), 경로 LLM Judge | Trajectory 평가에 적합 | 경로 일치는 LLM 없이 계산, trace 형식 변환 필요 |
| TruLens | 청크 단위 근거성, 추적 | 낮음~중간 | 추적 중심이라 오프라인 채점에는 무거움 |
| LangSmith | 실험 비교 UI | 보조 | 계정 필요, 데이터가 외부로 업로드됨 |

**추천 구성 (팀 결정 필요)**

1. 주 지표: 커스텀 LLM Judge. 답변 모델(`gemini-3.6-flash`)과 다른 Judge 모델을 쓰고, 기준표와 Judge 프롬프트를 파일로 고정해 결과와 함께 기록합니다. Multi-Agent 270문항 기준 입력 약 150만~200만 토큰입니다.
2. Trajectory: 기록된 `search_rounds`·`stop_reason`으로 불필요한 재검색 집계, 필요하면 AgentEvals 경로 일치.
3. 교차 확인: Ragas 충실성을 일부 문항(약 50개)에만 돌려 Judge 점수와 비교.
4. 사람 검수: 30문항 정도를 직접 보고 Judge 기준을 보정.

기획서의 기본 조합은 "커스텀 코드 + Ragas + AgentEvals"였습니다. 위 구성은 커스텀 Judge 비중을 키우고 Ragas를 보조로 둔 안입니다.

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

## 6. 주의할 점

- 질문과 기준 답안(제공·팀 골든셋 모두)은 검색 DB와 Agent 프롬프트에 넣지 않습니다.
- `page_no`·`source_pages`는 PDF 실제 쪽 순서(1부터)입니다. 가이드북은 PDF 1쪽에 책 2쪽이 들어 있고, 주택연금은 인쇄 쪽번호와 2쪽 차이가 납니다.
- 기본 positive·negative의 검색 범위는 용어집 + 약관뿐입니다. 범위를 넓히면 "자료에 없음"의 기준이 달라집니다.
- 팀 골든셋의 "답할 수 없는 질문"에도 근거 페이지가 적혀 있어, 올바르게 보류해도 인용 Hit가 낮아집니다.
- `.env`, `04_extracted/crops/`, `04_extracted/vision_cache/`, `05_chunks/`, `logs/`는 git에 올리지 않습니다.
