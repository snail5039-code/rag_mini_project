# 금융 문서 기반 Multi-Agent RAG

금융 PDF 23개(490쪽)를 검색 가능한 데이터로 가공하고, 여러 Agent가 검색 결과를 평가·개선해 근거(파일명·PDF 페이지)가 있는 한국어 답변을 만드는 프로젝트입니다.

| 문서 | 내용 |
|---|---|
| [기획서.md](./기획서.md) | 목표, 역할, 평가 체계 (기획 단계) |
| [docs/pipeline.md](./docs/pipeline.md) | 파이프라인 상세 설계: 스키마, 근거 ID 매핑, 실행 기록 형식, 비교 실험, 확정 필요 항목 |
| [docs/agent_graph.md](./docs/agent_graph.md) | Multi-Agent 그래프의 노드·종료 조건·공통 상태·미들웨어 |
| [team_golden_set/README.md](./team_golden_set/README.md) | 팀 골든셋 구성과 검수 방법 |
| [docs/handoff.md](./docs/handoff.md) | **인수인계**: 환경 준비(pgvector 설치 포함), 평가 실행, 남은 할 일, 평가 방법 비교 |

## 프로젝트 목표

- PDF 본문·표·차트를 페이지 단위 JSONL로 추출
- Recursive와 Parent-Child 청킹 비교
- Vector·BM25·Hybrid·MMR 검색 성능 평가
- PostgreSQL + pgvector에 청크·임베딩·실행 기록·평가 결과 저장
- 검색 → 평가 → 피드백 → 개선을 반복하는 Multi-Agent RAG 구현
- 답변에 근거 파일명과 PDF 페이지 표시
- 근거가 없을 때 확인·정정·보류·거절
- 기본 RAG와 Multi-Agent RAG의 품질·비용 비교

## 전체 구조

![전체 파이프라인](docs/images/01_overview.png)

| 단계 | 시점 | 하는 일 |
|---|---|---|
| ① 인덱싱 | 오프라인, 설정이 바뀔 때만 | 추출 JSONL을 parent(구조 단위)와 child(작은 단위)로 나누고, child만 임베딩해 PostgreSQL에 저장 |
| ② 질의 실행 | 온라인, 문항마다 | Multi-Agent가 child를 검색하고, parent를 조회하고, 근거가 충분한지 평가하고, 답변 |
| ③ 기록·평가 루프 | 실행 후 | 실행 기록을 저장하고 채점한 뒤, 실패 원인을 분석해 한 요소만 바꿔 재평가 |

## 역할 분담

| 담당 | 역할 | 결과물 |
|---|---|---|
| 박의혁 | PDF 추출 및 검수 | `extraction/`, `04_extracted/extracted_pages.jsonl`, 추출 보고서 |
| 정원하 | 파이프라인 설계, 청킹·임베딩, 검색 평가, 기본 RAG·Multi-Agent RAG | `docs/`, `rag/`, `scripts/`, `db/`, `06_results/` |
| 한용님 | 골든셋 작성·검수 | `team_golden_set/`, `src/golden_*.py` |

## 폴더 구성

| 경로 | 내용 |
|---|---|
| `01_data/` | 원문 PDF 23개 |
| `02_questions/`, `03_answers/` | 제공 질문 180개와 기준 답안 |
| `extraction/` | PDF 추출 코드 (`extract_pdfs.py`, `vision_fill.py`, `report.py`, `to_markdown.py`) |
| `04_extracted/` | 추출 결과 `extracted_pages.jsonl`, 검수 통계 `extraction_report.json`, 사람이 읽는 `md/` |
| `rag/` | 문서 구조 인식, 청킹, 임베딩, 검색기, 기본 RAG, Multi-Agent RAG |
| `scripts/` | DB 초기화, 청크 생성·적재, 검색 평가, RAG 실행·채점 |
| `db/schema.sql` | PostgreSQL + pgvector 스키마 |
| `05_chunks/` | 청크 JSONL (생성물, git 제외) |
| `06_results/` | 검색 평가 결과, RAG 실행 기록(`rag/*.jsonl`)과 요약 |
| `team_golden_set/` | 팀 골든셋 90문항, 문서별 검수 결과(`verification/`) |
| `adversarial_set/` | 가드레일 측정용 적대적 문항 36개 (`--golden adversarial`) |
| `src/` | 골든셋 생성·자동 검사 코드 |

## 질문·답안 세트

| 세트 | 제공 문항 | 팀 골든셋 | 검색 대상 |
|---|---|---|---|
| 기본 positive | POS001~060 (60) | POS091~120 (30) | 금융용어집 + 표준약관 |
| 기본 negative | NEG001~040 (40) | NEG041~060 (20) | 금융용어집 + 표준약관 |
| 금융생활 positive | POS061~080 (20) | POS081~090 (10) | 금융생활 가이드북 |
| 추가 문서 positive | ADD-*01~10 (60) | ADD-*11~15 (30) | 추가 PDF 6개 |

- 질문과 기준 답안은 검색 DB와 Agent 프롬프트에 넣지 않습니다.
- 제공 세트는 설정 비교에, 팀 골든셋은 제공 세트와 **구분해서** 최종 검증에 씁니다.
- 기본 negative의 "자료에 없음"은 용어집과 약관만 검색한다는 조건입니다. 세트마다 검색 범위를 `file_name` 필터로 강제합니다.

## 1. PDF 추출

**담당: 박의혁**

문서 성격에 따라 추출 방식을 나눴습니다.

| 문서 | 특징 | 방식 |
|---|---|---|
| 표준약관 15개, 용어집 | 1단 텍스트, 표·이미지 없음 | `pdfplumber` 페이지 전체 |
| 금융생활 가이드북 | 책 2쪽이 PDF 1쪽에 들어간 펼침면 | `RapidLayout(PP-DocLayoutV3)` 영역별 |
| 추가 PDF 6개 | 2단 편집, 표·차트·이미지 다수 | `RapidLayout(PP-DocLayoutV3)` 영역별 |

```text
페이지 렌더링
 → RapidLayout으로 text·title·table·chart·image 영역 탐지
 → 글 영역: pdfplumber 글자를 영역에 배정, 텍스트 레이어가 없으면 RapidOCR(한국어)
 → 표 영역: pdfplumber 표 → 품질 검사 실패 시 RapidTable → 그래도 실패하면 Vision 대기
 → 차트·큰 그림·OCR 글 영역: crop 이미지 저장 후 Gemini Vision으로 텍스트화
 → 반복 워터마크·인쇄 문구 제거 후 페이지별 JSONL 저장
```

| 대상 | 도구 |
|---|---|
| 본문·선이 있는 표·글자 좌표 | `pdfplumber` |
| 표·차트·그림 위치 | `RapidLayout` + PP-DocLayoutV3 |
| 텍스트 레이어가 없는 영역 | `RapidOCR` (korean PP-OCRv5) |
| 이미지 기반 표 구조 | `RapidTable` (SLANet+) |
| 차트·깨진 표·큰 그림·OCR 글 영역 | Gemini Vision (`gemini-3.5-flash`) |

### JSONL 형식

`extracted_pages.jsonl`은 페이지 1개가 한 줄입니다. `page_no`는 PDF 실제 쪽 순서(1부터)로, 기준 답안의 `source_pages`와 같은 기준입니다.

```jsonl
{"file_name":"additional/self_employed_debt_2025.pdf","doc_group":"additional","page_no":1,"method":"layout","blocks":[{"block_id":"additional/self_employed_debt_2025#p1-b2","type":"title","text":"...","bbox":[71.9,115.2,285.4,163.2],"source":"pdfplumber","order":2}]}
```

| 필드 | 의미 |
|---|---|
| `doc_group` | `standard_terms` / `glossary` / `life_guide` / `additional`. 세트별 검색 범위에 사용 |
| `blocks[].type` | `text` / `title` / `caption` / `table` / `chart` / `image` |
| `blocks[].source` | 추출 도구 (`pdfplumber`, `rapidtable`, `gemini_vision`, `rapidocr`, `pdfplumber_leftover`) |
| `blocks[].bbox` | PDF 포인트 좌표 `[x0, top, x1, bottom]` |

### 추출 결과와 비용

| 항목 | 값 |
|---|---|
| 대상 | PDF 23개, 490쪽 → 블록 3,277개 |
| 추출 시간 | 약 18분 (CPU, 레이아웃 문서 348쪽 기준) |
| 로컬 도구 | `pdfplumber`·`RapidLayout`·`RapidOCR`·`RapidTable`은 로컬 실행이라 API 비용 없음 |
| Gemini Vision 모델 | `gemini-3.5-flash` (`extraction/vision_fill.py`) |

Gemini Vision은 차트·깨진 표·큰 그림·OCR 글 영역에만 호출했습니다. 아래는 다시 실행·재처리한 호출까지 포함한 **실제 API 사용량**입니다(`logs/app.log`, `04_extracted/vision_cache/` 296건 기준).

| 실행 | 호출 수 | 입력 토큰 | 출력 토큰 |
|---|---:|---:|---:|
| 시험 실행 (5개) | 5 | 7,718 | 3,129 |
| 차트·표·그림 1차 | 159 | 218,279 | 49,632 |
| OCR 글 영역 (OCR 힌트 포함) | 66 | 81,018 | 972 |
| OCR 글 영역 재처리 (힌트 제거) | 66 | 78,214 | 977 |
| **합계** | **296** | **385,229** | **54,710** |

최종 `extracted_pages.jsonl`에 반영된 Vision 블록은 230개(입력 304,211 · 출력 53,738 토큰)입니다. 나머지는 프롬프트를 바꾸기 전 결과라 덮어썼습니다.

**비용 추정**: Gemini API 가격표(2026-10-21 확인)에 `gemini-3.5-flash` 단가가 없어, 같은 계열 모델 단가로 범위를 잡았습니다.

| 기준 단가 (100만 토큰당) | 입력 비용 | 출력 비용 | 합계 |
|---|---:|---:|---:|
| Gemini 3.5 Flash-Lite (입력 $0.30 / 출력 $2.50) | $0.12 | $0.14 | **$0.25** |
| Gemini 3.6 Flash (입력 $0.75 / 출력 $3.75) | $0.29 | $0.21 | **$0.49** |

- 추출 전체 Gemini 비용은 약 **$0.25~$0.49**(약 350~700원)로 추정합니다.
- 출력 토큰은 응답 본문(`candidates_token_count`)만 기록했고 모델의 생각(thinking) 토큰은 기록하지 않아, 실제 청구액은 이보다 클 수 있습니다. 정확한 금액은 Google Cloud 결제 내역에서 확인합니다.
- 결과를 이미지 해시로 캐시하므로 같은 설정으로 다시 추출하면 추가 비용이 들지 않습니다.

### 알려진 추출 오류 후보

팀 골든셋 검수(`team_golden_set/verification/`)에서 찾은 항목으로, 재검증이 필요합니다.

- 주택 정책금융 21쪽: 표 아래 각주가 표 셀로 인식되어 조각남
- 퇴직연금 23쪽: 표 일부 행의 숫자가 섞임
- 퇴직연금 17쪽: '권역별 점유율 추이' 차트 값이 4쪽 본문과 한 칸씩 어긋남

## 2. 청킹 및 임베딩

**담당: 정원하** · 상세: [docs/pipeline.md 1장](./docs/pipeline.md#1-인덱싱-파이프라인)

![인덱싱 파이프라인](docs/images/02_indexing.png)

핵심 구조는 **Parent-Child**입니다. 작은 child를 pgvector에서 검색해 정밀도를 높이고, child의 `parent_id`로 근거가 포함된 구조 단위(조항, 소제목 문단)를 통째로 가져와 답변 Agent가 읽습니다.

| 문서 | parent | child |
|---|---|---|
| 용어집 | 용어 + 정의 | parent가 짧아 child와 같아질 수 있음 |
| 표준약관 | 조항 | 약 300자, 겹침 60 |
| 가이드북·추가 PDF | 소제목 + 문단 | 약 300자, 겹침 60 |
| 표·차트 | 영역 전체 | 영역 전체 또는 행 단위 (결정 필요) |

비교한 청킹 방식은 Recursive `300/60`, `500/60`, `800/60`, `1000/60`(페이지 단위)과 Parent-Child `300/60`입니다.

모든 청크에 기준 답안과 같은 형식의 `source_ids`(예: `fsc-glossary-1697`, `kofia-terms-123-1709-015`, `fss-life-guide-pdf-10`)를 붙입니다. 청킹 방식을 바꿔도 같은 정답 ID로 채점해야 비교가 공정하기 때문입니다.

```text
chunk_id, parent_id, chunk_method, file_name, doc_group, page_no, page_end,
section_title, content_type, source_ids, content
```

| 설정 (`rag/config.py`) | 값 |
|---|---|
| 임베딩 모델·차원 | `gemini-embedding-2`, 1536차원 (pgvector `vector` HNSW 인덱스는 약 2,000차원까지 지원) |
| 생성 모델 | `gemini-3.6-flash` |
| 기준 실험 | `parent_child_300_60__gemini-embedding-2_1536` |

## 3. 데이터베이스와 검색

**PostgreSQL + pgvector**에 청크, parent 원문, 임베딩, 실행 기록, 평가 결과를 저장합니다. 스키마는 [db/schema.sql](./db/schema.sql)입니다.

| 테이블 | 저장 대상 |
|---|---|
| `chunks` | child 청크 + 메타데이터 + `embedding` (HNSW, cosine) |
| `parent_chunks` | parent 원문 + 메타데이터 (임베딩 없음) |
| `retrieval_eval_runs` / `retrieval_eval_cases` | 검색 평가 결과 |
| `rag_runs` / `rag_case_results` | RAG 실행 설정·요약과 문항별 실행 기록 |

| 검색기 | 구현 (`rag/retrieval.py`) |
|---|---|
| Vector | pgvector cosine 거리 (`embedding <=> query`) |
| BM25 | `chunks`를 읽어 메모리에서 구성, Kiwi 토큰화 |
| Hybrid | Vector와 BM25 순위를 RRF로 결합 (`rrf_k=60`) |
| MMR | 관련성과 중복을 함께 고려 (`lambda_mult=0.7`) |

### 검색 평가 결과

제공 positive 140문항, `child_k=8`, `max_parents=5` 기준입니다. 전체 결과는 `06_results/*.json`에 있습니다.

| 실행 | child MRR | child Hit@5 | child Recall@5 | parent Recall@5 |
|---|---:|---:|---:|---:|
| **parent_child_300_60 · vector** | **0.885** | **0.993** | **0.840** | **0.901** |
| parent_child_300_60 · mmr | 0.885 | 0.964 | 0.829 | 0.871 |
| parent_child_300_60 · hybrid | 0.854 | 0.957 | 0.818 | 0.878 |
| recursive_300_60 · hybrid | 0.786 | 0.921 | 0.780 | - |
| recursive_300_60 · vector | 0.768 | 0.921 | 0.781 | - |
| recursive_1000_60 · vector | 0.684 | 0.829 | 0.694 | - |
| parent_child_300_60 · bm25 | 0.662 | 0.807 | 0.670 | 0.723 |

- 기준 설정은 **Parent-Child 300/60 + Vector**로 정했습니다. 전체 MRR과 parent Recall@5가 가장 높습니다.
- 세트별 child MRR은 기본 0.938(Vector) / 금융생활 0.933(Vector) / 추가 PDF 0.844(Hybrid)입니다. 추가 PDF는 Hybrid가 높아, 개선 Agent가 `vector`와 `hybrid` 중에서 고르게 했습니다.

## 4. Multi-Agent RAG

**담당: 정원하** · 상세: [docs/agent_graph.md](./docs/agent_graph.md) · 구현: `rag/multi_agent.py` (LangGraph)

![멀티 Agent 흐름](docs/images/03_agent_flow.png)

```mermaid
flowchart TD
    Q([질문 + 질문 세트]) --> O[오케스트레이터<br/>검색 범위 결정 · 상태 초기화]
    O --> S[검색 Agent<br/>child 벡터/하이브리드 검색 → parent 조회 · 누적]
    S --> E{평가 Agent<br/>근거 판정}
    E -- "sufficient / ambiguous /<br/>out_of_scope / inappropriate" --> A[답변 Agent<br/>응답 유형 결정 · 파일명·페이지 인용]
    E -- "insufficient<br/>(재검색 가능)" --> F[피드백 Agent<br/>부족한 근거 · 실패 원인 분석]
    E -- "insufficient<br/>(횟수 소진 · 새 근거 없음)" --> A
    F --> I[개선 Agent<br/>새 검색어 1~3개 · 검색기 선택]
    I --> S
    A --> END([종료: answer / correct / clarify / abstain / refuse])
```

| 노드 | 종류 | 입력 → 출력 |
|---|---|---|
| 오케스트레이터 | 코드 | 질문 세트 → 검색 범위(`file_name` 목록), 반복 횟수·사용량 초기화 |
| 검색 Agent | 코드(도구) | 검색어 → child 검색(top 8), parent 조회(검색어당 최대 5), 누적 문맥(최대 8 parent) |
| 평가 Agent | LLM | 질문 + 누적 문서 → `sufficient` / `insufficient` / `ambiguous` / `out_of_scope` / `inappropriate` |
| 피드백 Agent | LLM | 평가 결과 + 사용한 검색어 + 검색된 제목 → 부족 원인 |
| 개선 Agent | LLM | 피드백 → 새 검색어 1~3개, 검색기(`vector` / `hybrid`) |
| 답변 Agent | LLM | 질문 + 문서 + 평가 → 응답 유형, 답변, 인용 문서 번호 |

| 종료 조건 | 결과 |
|---|---|
| 평가가 `insufficient`가 아님 | 답변 Agent로 이동 |
| 검색 3회(첫 검색 + 재검색 2회) 도달 | 답변 Agent로 이동 (`stop_reason=max_rounds`) |
| 재검색에서 새 parent가 없음 | 답변 Agent로 이동 (`stop_reason=no_new_evidence`) |

| 응답 유형 | 해당 사례 |
|---|---|
| `answer` / `correct` | 근거를 찾아 답하거나, 잘못된 전제를 인용과 함께 정정 |
| `clarify` | 대상이 특정되지 않은 질문 (예: 어떤 계좌인지 없는 질문) |
| `abstain` | 최신 금리, 개인 계좌 정보, 문서에 없는 정보, 재시도 소진 |
| `refuse` | 개인 맞춤 투자 추천, 규정 우회, 고객 기만, 프롬프트 인젝션 |

### 공통 미들웨어

| 위치 | 역할 |
|---|---|
| 입력 | 질문 세트별 검색 범위 강제 (기본·negative: 용어집+약관, 금융생활: 가이드북, 추가: 추가 PDF) |
| 입력 검증 (GR1) | 빈 질문·2,000자 초과는 LLM·검색 없이 안내(`clarify`). 인젝션이 섞인 정상 질문은 막지 않음 (`rag/guardrail.py`) |
| 검색 전 | 이미 쓴 검색어 차단, 라운드당 검색어 최대 3개, 누적 문맥 최대 8 parent |
| 출력 | 인용 번호가 실제 문맥에 있는지 검증, 없는 번호는 `invalid_citations`로 기록 |
| 출력 검사 (GR3) | 인용 없는 답변, 주민·카드번호 패턴, 투자 권유 표현을 `guardrail_flags`에 **기록만** 함(차단 안 함) |
| 오류 대응 (G1) | 인증·결제 오류(401·402·403)는 즉시 중단(`FatalLLMError`), 구조화 출력 파싱 실패는 1회 재호출 (`rag/llm.py`) |
| 대체 경로 (G2) | 임베딩 실패→BM25, 평가 실패→현재 문맥으로 바로 답변, feedback·improve 실패→재검색 생략, 답변 실패→안전 응답. 응답에 `degraded` 표시, 점수 집계에서는 실패로 센다 |
| 전체 | 문항별 trace·사용량을 PostgreSQL(`rag_case_results`)과 `06_results/rag/*.jsonl`에 저장 |

문서 본문과 질문 속 지시문(이전 지시 무시, 출처 바꾸기 등)은 따르지 않도록 프롬프트에서 지시 영역과 문서 영역을 분리합니다.

## 5. 평가

**골든셋 담당: 한용님** · 상세: [docs/pipeline.md 3장](./docs/pipeline.md#3-기록평가-루프)

![기록·평가 루프](docs/images/04_eval_loop.png)

| 구분 | 확인 내용 | 방법 |
|---|---|---|
| 검색 | 정답 근거를 상위 결과에서 찾았는가 (Hit@k, Recall@k, MRR, nDCG@k) | 코드, child 단계 + parent 단계 |
| 응답 유형 | 기대 행동과 맞는가 (`behavior_strict` / `behavior_lenient`) | 코드 (`scripts/run_rag.py`) |
| 인용 | 받은 문맥·인용에 정답 근거가 있는가 (`context_recall`, `citation_hit`, `citation_recall`) | 코드 |
| 답변 | 정확성, 완전성, 근거 충실성 | Ragas, LLM Judge (예정) |
| Trajectory | 불필요한 재검색을 피했는가 | AgentEvals (예정) |
| 효율 | 모델 호출·검색 호출·토큰·응답 시간 | 실행 기록 집계 |

- `behavior_strict`는 기대 행동의 첫 번째 응답 유형과 정확히 같을 때, `behavior_lenient`는 허용 유형 안에 있을 때 통과입니다. 예를 들어 `answer`가 기대인데 `correct`로 답하면 lenient만 통과합니다.
- 검색을 child 단계와 parent 단계로 나눠, 검색기는 근거를 찾았지만 `max_parents` 때문에 답변 문맥에서 잘린 경우를 구분합니다.

### 기본 RAG vs Multi-Agent RAG (제공 180문항)

같은 기준 설정(Parent-Child 300/60 + Vector, `gemini-3.6-flash`)으로 실행했습니다. 기록은 `06_results/rag/`에 있습니다.

| 지표 | 기본 RAG | Multi-Agent 1차 | Multi-Agent 2차 |
|---|---:|---:|---:|
| behavior_strict | 0.661 | **0.883** | 0.800 |
| behavior_lenient | 0.956 | 0.967 | 0.967 |
| citation_hit | 0.953 | **0.986** | 0.980 |
| citation_recall | 0.855 | **0.886** | 0.880 |
| context_recall | 0.906 | **0.918** | 0.915 |
| 평균 모델 호출 | 1.00 | 2.30 | 2.25 |
| 평균 입력 토큰 | 3,003 | 6,839 | 6,847 |
| 평균 응답 시간 | 6.7초 | 13.1초 | 13.0초 |

- Multi-Agent는 엄격 기준을 0.661 → 0.883으로 올렸고, 차이는 주로 응답 유형 판단(`answer`와 `correct` 구분)에서 나왔습니다. 대신 모델 호출과 입력 토큰은 약 2.3배입니다.
- 2차 실행은 평가·답변 프롬프트를 바꾼 것으로, 금융생활은 1.000으로 올랐지만 전체 strict는 0.800으로 내려갔습니다. 문항별 원인 분석이 필요합니다.

### 팀 골든셋

제공 세트의 절반 분량(90문항)을 새로 만들었고, 그중 14문항(positive 계열의 20%)은 문서만으로 답할 수 없는 질문입니다. 근거 구절이 추출 텍스트에 있는지, 번호·필드가 맞는지 `src/golden_*.py`가 자동 검사하고 결과를 `team_golden_set/verification/`에 남깁니다. "사람이 PDF 원문 확인" 칸은 아직 채우는 중입니다.

### 제공 + 팀 골든셋 평가 (2026-10-21)

같은 DB·기준 설정(Parent-Child 300/60 + Vector, `gemini-3.6-flash`, 2차 프롬프트)에서 270문항(제공 180 + 팀 90)을 실행했습니다. 제공 세트와 팀 골든셋은 따로 집계합니다.

```bash
python scripts/run_rag.py --pipeline basic --golden both
python scripts/run_rag.py --pipeline multi --golden both
```

| 지표 | 제공 180 · 기본 RAG | 제공 180 · Multi-Agent | 팀 90 · 기본 RAG | 팀 90 · Multi-Agent |
|---|---:|---:|---:|---:|
| 응답 유형 (엄격) | 0.656 | **0.794** | 0.900 | 0.900 |
| 응답 유형 (완화) | 0.944 | **0.967** | **0.944** | 0.911 |
| 문맥 Recall | 0.906 | **0.922** | 0.947 | **0.962** |
| 인용 Hit | 0.946 | **0.986** | 0.772 | **0.899** |
| 인용 Recall | 0.858 | **0.894** | 0.738 | **0.863** |
| 평균 토큰 | 3,210 | 7,369 | 3,145 | 8,236 |
| 평균 응답 시간 | 7.0초 | 13.5초 | 6.0초 | 13.6초 |

결과 파일: `06_results/rag/20261021_094418__basic_rag__both_golden.*`, `06_results/rag/20261021_093905__multi_agent__both_golden.*`

- 제공 세트 점수는 전날 실행과 거의 같아(Multi-Agent 엄격 0.800 → 0.794, 기본 RAG 0.661 → 0.656) DB·임베딩을 새로 만들어도 재현됐습니다.
- 제공 세트에서는 Multi-Agent가 모든 지표에서 앞서고, 추가 PDF 엄격 점수가 0.350 → 0.683으로 크게 올랐습니다. 대신 토큰은 약 2.3배, 시간은 약 1.9배입니다.
- 팀 골든셋에서는 인용 정확도는 Multi-Agent가 높지만(인용 Hit 0.772 → 0.899), 응답 유형은 같거나 낮습니다.

**팀 골든셋에서 Multi-Agent가 틀린 9문항**

| 유형 | 문항 | 현상 | 원인 |
|---|---|---|---|
| 보류해야 하는데 `answer` | ADD-HF15, ADD-HP15, ADD-IN15, ADD-PF15, POS086, POS099, POS120 | 답변 본문에는 "문서에서 확인할 수 없다"고 정확히 쓰지만 응답 유형을 `answer`(`correct`)로 붙임. 기본 RAG는 대부분 `abstain` | 2차 답변 프롬프트의 "근거 일부만 확인되면 answer, abstain은 근거가 전혀 없을 때만" 규칙. 제공 세트 2차 하락의 원인으로도 추정 |
| 되물어야 하는데 답함 | NEG046 | "약관이 바뀌면 언제부터 적용돼?"에 대상 약관을 묻지 않고 답함 | 평가 Agent가 `ambiguous`로 판정하지 않음 |
| 거절해야 하는데 보류 | NEG052 | DC형 적립금을 ELW에 전부 넣는 질문에 `refuse` 대신 `abstain` | `refuse`와 `abstain` 경계 |

**해석할 때 주의할 점**

- 팀 골든셋의 "답할 수 없는 질문"에도 관련 근거 페이지가 적혀 있어, 올바르게 보류해도 인용이 없어 인용 Hit가 낮아집니다(8문항). 팀 세트의 인용 점수는 실제보다 낮게 나옵니다.
- 팀 골든셋은 기본 세트 근거 ID가 `{파일명}-pdf-{쪽}` 형식이라, `run_rag.py`가 청크의 파일·페이지로 근거를 비교합니다.
- 팀 골든셋과 가이드북·추가 세트의 `must_include`는 문장으로 풀어 쓴 기준이라 글자 일치 점수(`must`)는 0에 가깝습니다. 답변 내용은 Ragas·LLM Judge로 따로 평가합니다.

### 평가·개선 과정 (2026-10-21)

270문항(제공 180 + 팀 90) 기준으로 평가하고, 약점을 찾아 수정해 다시 비교한 과정입니다. 모든 수치는 단일 실행 값이며, 같은 코드를 3회 돌려도 점수가 흔들립니다(엄격 ±0.02, Judge 정확성 ±0.03, 만점 비율 ±0.07). 채점 기준도 엄격해서(항목 하나만 빠져도 감점) 절대 점수는 낮게 읽힙니다. 아래 그림은 저장된 결과만으로 `scripts/make_eval_figures.py`가 만들었고, LLM 호출은 없습니다.

| 단계 | 내용 | 결과 | 상세 |
|---|---|---|---|
| 1 | 검색 평가, 기본 RAG·Multi-Agent 실행 | 위 표와 같음 | 이 문서 |
| 2 | LLM Judge, Ragas, 경로 평가 | Judge 정확성 0.763 → 0.789, 충실성 0.998 | [eval_step2_1021.md](./docs/eval_step2_1021.md) |
| 3 | 실패 유형 분석 | 실패 원인의 60% 이상이 "답변 내용 불완전·부정확", 다음이 검색 단계에서 근거를 못 찾음 | [eval_step3_problems_1021.md](./docs/eval_step3_problems_1021.md) |
| 4 | 문제·개선책 우선순위 | P2 보류 판단 → P1 답변 완전성 → P5 헛된 재검색 → … | [eval_step4_priority_1021.md](./docs/eval_step4_priority_1021.md) |
| 5 | 한 번에 하나씩 수정 → 재실행 → 비교 | 6번 시도(P2, P2-b, P2-c, P1, P3, P3-b), 정확성 개선 없음 | [eval_changes_log.md](./docs/eval_changes_log.md) |
| 6 | 안정성·가드레일 (fault tolerance, fallback, guardrail) | G1·G2·GR1·GR3 구현, 적대적 36문항에서 취약점 없음 | [guardrail_review_1021.md](./docs/guardrail_review_1021.md), [adversarial_set_1022.md](./docs/adversarial_set_1022.md) |
| 보정 | 답할 수 없는 질문 제외 재집계, 필수 항목을 핵심/부가로 분리 | 만점 비율 0.589 → 약 0.785(추정) | [eval_rescore_1021.md](./docs/eval_rescore_1021.md) |

**기준선(수정 전, 270문항)**

| 지표 | 기본 RAG | Multi-Agent |
|---|---:|---:|
| 응답 유형 엄격 / 완화 | 0.730 / 0.941 | 0.830 / 0.959 |
| Judge 정확성 | 0.763 | 0.789 |
| 정확성 만점 비율 (원래 / 핵심 기준 보정) | 0.567 / 0.767 | 0.589 / 0.785 |
| 충실성 | 0.998 | 0.998 |
| 문맥 Recall | 0.916 | 0.935 |
| 평균 토큰 | 3,179 | 7,606 |

![기본 RAG vs Multi-Agent](docs/images/eval_01_basic_vs_multi.png)

- Multi-Agent는 응답 유형 판단(특히 엄격 기준)에서 앞서고 내용 정확성은 조금 높지만, 토큰은 약 2.4배입니다. 충실성은 둘 다 0.998로 근거 없는 내용을 지어내는 문제는 거의 없습니다.

![비용 비교](docs/images/eval_03_cost.png)

**실패 원인** (원인이 붙지 않은 통과 문항 제외, Multi-Agent 실패 136건)

![실패 원인 구성비](docs/images/eval_02_failure_causes.png)

- 가장 큰 원인(약 68%)은 답을 했지만 조건·예외·부가 설명이 빠지는 "내용 불완전"입니다. 검색 단계에서 근거를 못 찾은 경우가 약 18%, 응답 유형 판단 오류가 약 8%입니다.
- "내용 불완전" 중 상당수는 핵심은 맞고 부가 항목만 빠진 경우입니다. 필수 항목을 핵심/부가로 나눠 다시 채점하면 만점 비율이 올라갑니다(아래 그림). 이 보정값은 LLM 분류에 기반한 추정이라 사람 검토가 필요합니다.

![만점 비율 보정](docs/images/eval_05_full_rate_adjusted.png)

**수정 시도와 결과**

| 시도 | 변경 | 결과 | 판정 |
|---|---|---|---|
| P2 | 답변 프롬프트의 보류 판단 기준 | 보류 대상 8문항 중 6개 고침, 과보류 0 → 3 | 되돌림 |
| P2-b | 위 문구에서 '개인 정보' 예시 삭제 등 좁힘 | 5/8, 과보류 3. 원인이 평가 단계의 `out_of_scope` 오판임을 확인 | 되돌림 |
| P2-c | 평가 단계에서 값의 근거 문장을 먼저 인용 | 6/8, 과보류 5, 토큰 +6.6% | 되돌림 |
| P1 | 답변 프롬프트에 하위 질문·단서 포함 지시 | 62문항 부분 확인, 부가 항목 충족률 0.103 → 0.123(문항 선택 편향 수준) | 되돌림 |
| P3 | 평가 프롬프트: 방법·판단을 묻는 질문은 사실이 문서에 있으면 `sufficient` | 150문항 2회: 정확성 변동 범위 안(Judge +0.014), 토큰 -8.3%, 되묻기·거절 문항 2개 퇴보 | 코드에 남음(아래) |
| P3-b | P3에 "대상이 없으면 `ambiguous`, 부적절 요청은 `inappropriate` 우선" 조건 추가 | 150문항: 정확성 차이 없음(Judge -0.004, 완화 +0.002), 토큰 -7.9%, 되묻기 `NEG047` 복구·`NEG052` 미복구 | 코드에 남음(아래) |

**현재 코드 상태**: P2 계열과 P1은 되돌렸고, **P3와 P3-b(평가 프롬프트 문구)는 코드에 남아 있습니다.** 정확성은 좋아지지 않았고 평균 토큰이 약 8%, 응답 시간이 약 11% 줄어든 것이 확인된 효과의 전부입니다. 위 기준선 표와 그림 1~6은 P3 적용 전 코드의 270문항 값이고, **P3-b가 적용된 코드의 270문항 전체 점수는 측정하지 않았습니다.** 150문항 부분 집합 결과는 어려운 문항 비중이 높아 270문항 점수와 직접 비교할 수 없습니다. P3·P3-b를 되돌릴 때는 `git revert 62b7a8f a991174`입니다.

![시도별 점수와 변동 범위](docs/images/eval_04_attempts_variance.png)

![기준선 대비 좋아진·나빠진 문항](docs/images/eval_06_case_flips.png)

**P3 계열 (평가 프롬프트 수정, 150문항 부분 집합)**: 앞의 시도들이 "보류 판단"을 고치려 했다면, P3는 원인으로 지목된 평가 단계의 `out_of_scope` 오판을 직접 고쳤습니다. 방법·판단을 묻는 질문은 사실이 문서에 있으면 `sufficient`로 판정하게 했습니다. 결과는 정확성은 변동 범위 안이고 비용만 줄었습니다.

![P3 계열 효과](docs/images/eval_07_p3_effect.png)

P3는 되묻기·거절 문항을 무너뜨렸습니다(안전 문항 통과율 0.901 → 0.750). P3-b가 "대상이 없으면 `ambiguous`, 부적절 요청은 `inappropriate` 우선"을 더해 이를 복구했습니다(0.951). `NEG052` 하나만 복구되지 않았습니다.

![안전 문항 통과율](docs/images/eval_08_safety_cases.png)

- 의도한 문항은 고쳤지만 다른 문항에서 같은 수만큼 새 오류가 생겼습니다. 점수 변화(엄격 +0.015 등)는 모두 기준선 3회 반복의 변동 범위 안이라, 단일 실행으로는 효과가 있었다고 말할 수 없습니다. P3·P3-b에서도 같았습니다.
- 보류 판단은 평가 단계와 답변 단계 두 곳에서 일어나고 경계에 걸린 문항은 실행마다 결과가 갈리므로, 프롬프트 문구 한 군데를 고치는 방식으로는 정확성이 안정적으로 오르지 않았습니다. 다음 후보는 구조를 바꾸는 방법(답변 후 누락 점검 단계, 검색 양 조정, 평가 단계 개편)이고, 그 전에 Judge 사람 보정으로 점수 자체의 신뢰도를 확인하는 것을 권합니다([우선순위](./docs/eval_step4_priority_1021.md)).
- 앞으로 단일 실행에서 "효과 있음"으로 볼 최소 변화는 엄격 +0.03, 완화 +0.01, Judge 정확성 +0.03, 만점 비율 +0.08입니다.

### 안정성과 가드레일 (2026-10-22)

LLM 호출이 질문당 평균 2.4회인 Multi-Agent는 한 단계의 고장이 질문 전체의 실패가 됩니다. 실제로 선불 크레딧이 소진돼 52문항이 오류(402)로 실패한 적이 있습니다. 그래서 장애 대응(fault tolerance, fallback)과 가드레일을 검토하고 구현했습니다. 상세는 [guardrail_review_1021.md](./docs/guardrail_review_1021.md), 적대적 문항은 [adversarial_set_1022.md](./docs/adversarial_set_1022.md)에 있습니다.

| 구분 | 막는 문제 | 구현 | 검증 |
|---|---|---|---|
| G1 오류 구분·재시도 | 결제 오류 뒤에도 남은 문항을 계속 호출, 구조화 출력 파싱 실패 한 번에 질문 실패 | 401·402·403 즉시 중단, 파싱 실패 1회 재호출 | 가짜 클라이언트 8개 통과. 실제 호출에서 402가 나왔을 때 즉시 중단 작동 확인 |
| G2 대체 경로 | 노드 하나의 실패가 질문 전체 실패로 번짐 | 임베딩→BM25, 평가·feedback·improve 실패→현재 문맥으로 답변, 답변 실패→안전 응답 | 오류 주입 테스트 15개 통과, 정상 경로는 수정 전 코드와 응답·트레이스·호출 수 동일. 실제 모델 25문항에서 기본 RAG 수준 확인 |
| GR1 입력 검증 | 빈 질문·과도하게 긴 질문 | LLM·검색 없이 안내(`clarify`). 인젝션이 섞인 정상 질문은 막지 않음 | 단위 테스트 24개(GR3 포함) 통과 |
| GR3 출력 검사 | 인용 없는 답변, 주민·카드번호 노출, 투자 권유 표현 | 막지 않고 `guardrail_flags`에 기록만 | 기준선 270문항에 소급 적용: 신호 0건 |
| GR4 차단 규칙 | (실제 취약점이 있을 때만) | 구현하지 않음 | 적대적 문항에서 취약점이 측정되지 않음 |

**G2 저하 모드**: 평가 단계를 강제로 실패시킨 25문항에서 응답은 모두 정상적으로 나갔고, 점수와 비용은 기본 RAG 수준으로 낮아졌습니다.

![저하 모드](docs/images/eval_10_degraded_mode.png)

**적대적 문항 36개** (인젝션 변형 14, 내부 정보 빼내기 6, 개인정보 4, 권유·기만 우회 6, 정상 대조 6): 지시를 따르거나 비밀을 노출한 문항이 없었습니다. 응답 원문에서 주민번호, 프롬프트 문구, 키 정보를 직접 검색한 결과도 0건입니다. 정상 질문 오거절은 기본 RAG 1건뿐이고 Multi-Agent는 정상 대조 6개를 모두 답했습니다.

![적대적 문항 결과](docs/images/eval_09_adversarial.png)

- 낮게 보이는 막대(개인정보 C)는 취약점이 아니라 기대 라벨 문제이고, 결과를 본 뒤 문항을 고치면 측정이 오염되므로 그대로 두었습니다. 36문항이라 방향성만 봅니다(문항 1개 = 2.8%p).

### 성과 분석: 원인 분석으로 무엇을 얻었나

점수(Judge 정확성 0.789, 만점 비율 0.589)를 올리지는 못했습니다. 얻은 것은 **무엇이 문제이고 무엇이 문제가 아닌지를 측정으로 확정한 것**, **비용과 안정성의 개선**입니다.

| 원인 분석 결과 | 한 일 | 확인된 성과 | 한계 |
|---|---|---|---|
| 실패 136건 중 약 68%가 "내용 불완전"(핵심은 맞고 부가 항목 누락), 약 18%가 검색 근거 누락 | 실패를 원인별로 분류해 우선순위를 정함 | 개선 대상을 데이터로 정함. 검색(문맥 Recall 0.935)보다 답변 완전성이 병목임을 확인 | 완전성을 올리는 구조 변경은 아직 안 함 |
| 낮은 만점 비율(0.589)의 상당 부분은 채점 기준이 엄격해서 생김(부가 항목만 놓친 문항 53개) | 필수 항목을 핵심/부가로 나눠 재채점 | 같은 답변이 0.589 → 약 0.785로 읽힘. 점수의 의미를 바로잡음 | LLM 분류 기반 추정, 사람 검토 전 |
| 같은 코드도 점수가 흔들림 | 기준선 3회 반복 실행으로 변동 폭 측정 | 효과 판정 기준 확보(엄격 ±0.02, Judge ±0.03, 만점 비율 ±0.07). 시도 6건이 모두 노이즈 범위임을 확인해 **효과 없는 변경의 채택을 막음** | 150문항 부분 집합에서는 변동 폭이 더 큼 |
| 과보류의 원인은 답변 프롬프트가 아니라 평가 단계의 `out_of_scope` 오판 | P2·P2-b·P2-c로 원인을 좁힌 뒤 P3로 평가 단계를 직접 수정 | 목표 문항 `ADD-RP06`·`POS055` 고침, **평균 토큰 -7.9%, 응답 시간 -11%, 재검색률 0.116 → 0.067** | 정확성 개선 없음. P3-b가 적용된 코드의 270문항 전체는 미측정 |
| P3가 되묻기·거절 문항을 무너뜨림 | 우선 조건 보강(P3-b)과 반복 실행 확인 | 안전 문항 통과율 0.750 → **0.951**(기준선 0.901), `NEG047`·`NEG046` 복구 | `NEG052`는 미복구(기준선에서도 흔들리던 문항) |
| 크레딧 소진으로 52문항이 한꺼번에 실패한 사고 | G1 즉시 중단, G2 대체 경로 | 장애 시 호출 낭비 차단(실제 402에서 작동), 노드 고장에도 응답 유지(기본 RAG 수준) | 실제 장애를 270문항 규모로 재현하지는 않음 |
| 방어가 충분한지 알 수 없었음(인젝션 문항 9개뿐) | 적대적 문항 36개 작성·측정 | 지시 준수 0건, 비밀·개인정보 유출 0건, 차단 규칙 불필요 판정(**불필요한 가드레일 추가를 막음**) | 36문항, 방향성만 |

**성과가 아닌 것**: 정확성 지표(엄격 0.830, Judge 0.789, 만점 비율 0.589)는 개선하지 못했습니다. 프롬프트 한 군데를 고치는 방식은 의도한 문항을 고쳐도 다른 문항에서 같은 수만큼 새 오류가 생겼습니다. 다음 단계는 구조 변경(답변 후 누락 점검, 검색 양 조정)이고, 그 전에 Judge 사람 보정으로 점수의 신뢰도를 확인하는 것을 권합니다.

### 평가의 한계점 (2026-10-21 기준)

아래 점수는 현재 평가 방식의 한계를 감안해서 읽어야 합니다. 근거 자료는 [docs/eval_step2_1021.md](./docs/eval_step2_1021.md), [docs/eval_step3_problems_1021.md](./docs/eval_step3_problems_1021.md), [docs/eval_changes_log.md](./docs/eval_changes_log.md)에 있습니다.

| # | 한계점 | 내용 | 확인 상태 |
|---|---|---|---|
| 1 | 채점 기준이 엄격함 | `must_include`가 문항당 3~4개이고 핵심과 부가 설명을 구분하지 않습니다. 하나라도 빠지면 정확성이 1점으로 내려갑니다. Judge 정확성은 만점 59%, 0점 1% 안팎이라 대부분이 "핵심은 맞고 항목 하나가 빠진" 1점입니다. 점수가 핵심 사실 기준의 정답률보다 낮게 보일 수 있습니다 | 점수 분포로 확인. 낮게 보이는 정도는 미측정 |
| 2 | Judge 사람 보정 전 | 채점 모델(`gemini-3.8-flash`)이 사람과 얼마나 일치하는지 확인하지 않았습니다. `must_not_include`를 과하게 위반으로 본 사례가 있습니다(NEG056). 표본 30문항(`06_results/eval/judge_calibration_sample.md`)의 사람 판단 칸이 비어 있습니다 | 미확인 |
| 3 | 골든셋의 근거 표시 | 팀 골든셋의 "답할 수 없는 질문"에도 관련 근거 쪽이 `expected_source_ids`에 적혀 있어, 올바르게 보류해도 인용·문맥 지표가 낮아집니다(팀 세트 인용 Hit 약 0.85) | 확인됨 |
| 4 | 골든셋 검수 미완 | 팀 골든셋 90문항의 "사람이 PDF 원문 확인" 칸이 비어 있고, 자동 검사는 근거 구절의 존재만 확인했습니다. 어떤 `must_include` 항목이 정답에 꼭 필요한지는 검사하지 않았습니다 | 미확인 |
| 5 | 실행 간 변동 | 같은 설정에서도 `answer`와 `correct` 표시가 바뀌고(수정 전후 비교에서 17~21문항), 3번 재검색까지 가는 문항의 결과가 달라집니다. 단일 실행 점수의 ±0.02 이내 차이는 의미 있는 변화로 보기 어렵습니다. 기준선 3회 반복으로 변동 폭을 측정했습니다(엄격 ±0.02, Judge 정확성 ±0.03, 만점 비율 ±0.07). 자세한 기준은 [docs/eval_changes_log.md](./docs/eval_changes_log.md) 참고 | 측정 완료 |
| 6 | 보조 평가의 변별력 | Ragas FactualCorrectness는 짧은 기준 답안에서 낮게 나오고 Judge와의 상관이 낮습니다(0.28, -0.30). LLM 경로 Judge는 50문항 모두 통과로 변별력이 없습니다. 둘 다 주 지표가 아닌 교차 확인용입니다 | 확인됨 |
| 7 | 응답 유형 개선 시도의 한계 | 보류 판단을 고치려는 프롬프트 수정(P2, P2-b, P2-c)은 한 곳을 고치면 다른 곳에서 오류가 생겨 순이득이 없어 되돌렸습니다. 평가 단계를 고친 P3·P3-b도 정확성은 변동 범위 안이고 비용(토큰 -8%)만 줄었습니다 | 확인됨 (변경 이력 참고) |
| 8 | P3-b 적용 코드의 전체 점수 미측정 | 현재 코드에는 P3·P3-b가 남아 있는데, 270문항 전체 점수는 P3 이전 코드 기준입니다. 150문항 부분 집합(어려운 문항 위주)에서만 확인했습니다 | 미확인 (270문항 약 3M 토큰) |
| 9 | 적대적 문항이 작음 | 가드레일 측정은 36문항이라 방향성만 봅니다. 개인정보 문항(C)은 기대 라벨이 내용상 맞는 `refuse`를 실패로 집계합니다 | 확인됨 |
| 10 | 대체 경로의 실제 규모 검증 | G2는 가짜 객체 테스트와 실제 모델 25문항으로 확인했습니다. 저하 모드에서는 되묻기·거절이 답변 프롬프트에만 의존합니다 | 부분 확인 |

### 추가사항: 한계점을 고치는 방법

나중에 평가를 보완하려면 다음 순서로 진행합니다. 1~4는 시스템을 다시 실행하지 않고 저장된 결과를 다시 채점하는 것이라 비용이 낮습니다.

1. **Judge 사람 보정**: `judge_calibration_sample.md` 30문항에 사람 판단을 채워 Judge와의 일치율을 냅니다. 일치율이 낮은 항목은 `scripts/eval_judge.py`의 기준표를 고쳐 새 버전으로 두고, 기준선 결과를 같은 기준표로 다시 채점합니다.
2. **`must_include`를 핵심과 부가로 분리**: 골든셋에 핵심 항목(필수)과 부가 항목(가점) 필드를 나눠 담고, 핵심 항목만으로 다시 채점해 지금 점수와 비교합니다. 두 점수의 차이가 기준 엄격도의 크기입니다.
3. **답할 수 없는 질문의 근거 분리**: 정답 근거는 `expected_source_ids`에서 빼고 관련 쪽은 별도 필드로 둡니다. 또는 인용·문맥 지표 집계에서 보류·거절·되묻기 문항을 제외합니다.
4. **응답 유형 라벨 정리**: `answer`와 `correct`가 애매한 문항의 허용 유형을 정리하고, 엄격 점수와 함께 완화 점수를 기본 보고 지표로 둡니다.
5. **실행 간 변동 측정**: 같은 코드·설정으로 기준선을 3회 이상 실행해 평균과 범위를 보고하고, 개선 효과는 이 범위를 넘을 때만 유의미한 것으로 판단합니다. 병렬 실행으로 1회 약 10분이라 현실적입니다.
6. **Judge 보강**: 일부 문항은 두 번 채점해 일치 여부를 보거나 다른 모델과 교차 확인합니다. 경로 LLM Judge는 "헛된 재검색"의 판단 기준을 프롬프트에 명시해 변별력을 높이거나, 코드 지표(헛된 재검색 수, 불필요 재검색 수, 경로 일치)를 주 지표로 유지합니다.
7. **팀 골든셋 사람 검수**: `team_golden_set/verification/*.md`의 원문 확인 칸을 채우고, 계산한 기준 답안 수치와 `must_include` 항목의 필요성을 함께 확인합니다.
8. **시스템 개선 후보** (한계점 보완 이후): 답변 완전성(P1), 보류 판단을 평가 단계와 답변 단계에서 함께 재설계, 헛된 재검색 종료 조건(P5), 검색 양(P6). 우선순위와 근거는 [docs/eval_step4_priority_1021.md](./docs/eval_step4_priority_1021.md)에 있습니다.

## 실행 방법

PostgreSQL에 pgvector 확장이 필요합니다. `.env`에 `GEMINI_API_KEY`와 `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`(또는 `DATABASE_URL`)를 설정합니다.

```bash
pip install -r requirements.txt

# 1. PDF 추출 (결과가 이미 04_extracted/에 있으므로 다시 할 때만)
python extraction/extract_pdfs.py
python extraction/vision_fill.py
python extraction/report.py

# 2. 인덱싱
python scripts/init_db.py
python scripts/build_chunks.py
python scripts/load_chunks.py --method parent_child_300_60

# 3. 검색 평가
python scripts/eval_retrieval.py --experiments parent_child_300_60

# 4. RAG 실행·채점 (--golden team 또는 both로 팀 골든셋 포함)
python scripts/run_rag.py --pipeline basic
python scripts/run_rag.py --pipeline multi --golden both

# 5. 평가·그림 (저장된 결과만 사용, LLM 호출 없음)
python scripts/make_eval_figures.py
python scripts/make_guardrail_figures.py

# 6. 안정성·가드레일 테스트 (가짜 객체, API 비용 없음)
python scripts/test_g1_fault_tolerance.py
python scripts/test_g2_fallback.py
python scripts/test_gr_guardrail.py

# 7. 적대적 문항 측정 (가드레일)
python scripts/run_rag.py --pipeline multi --golden adversarial --sets negative --workers 16
python scripts/eval_judge.py --run <run_id> --workers 16
```

## 진행 상황

```text
1. PDF 추출 및 검수                     완료
2. Recursive·Parent-Child 청킹          완료
3. 임베딩 및 PostgreSQL 적재            완료
4. Vector·BM25·Hybrid·MMR 검색 평가     완료 → Parent-Child + Vector 선택
5. 기본 RAG 구현 및 평가                완료
6. Multi-Agent RAG 구현 및 평가         완료 (1차·2차)
7. 팀 골든셋 작성·자동 검사             완료 (사람 검수 진행 중)
8. 팀 골든셋으로 Agent 평가             완료 (제공 180 + 팀 90)
9. 실패 원인 분석과 개선                완료 (시도 6건, 정확성 개선 없음, 비용 -8%). 추출 오류 후보 3건은 미확인
10. 답변 품질(Ragas)·Trajectory 평가    완료 (Judge·Ragas·경로 평가, 변별력 한계는 한계점 6번)
11. 안정성·가드레일                      완료 (G1·G2·GR1·GR3 구현, 적대적 36문항 측정)
12. 점수 신뢰도 확보                     예정 (Judge 사람 보정, 핵심/부가 항목 검토, 팀 골든셋 원문 검수)
13. 정확성 개선                          예정 (답변 후 누락 점검, 검색 양 조정 등 구조 변경)
```

비교 실험에서는 한 번에 한 요소만 바꾸고 질문 세트, 임베딩 모델, 생성 모델, 평가 지표는 고정합니다. 확정이 필요한 항목은 [docs/pipeline.md 5장](./docs/pipeline.md#5-확정이-필요한-항목)에 있습니다.
