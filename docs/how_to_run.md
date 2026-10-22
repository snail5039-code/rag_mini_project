# 실행 방법

추출 결과(`04_extracted/extracted_pages.jsonl`)부터 청킹·임베딩, 검색 평가, 기본 RAG·Multi-Agent 실행, 답변 채점까지 재현하는 순서입니다. 명령은 모두 저장소 루트(`rag_mini_project/`)에서 실행합니다.

## 0. 준비

### Python 환경

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate && pip install -r requirements.txt
```

### PostgreSQL + pgvector

PostgreSQL 17에 pgvector 확장이 있어야 합니다. Docker는 쓰지 않습니다.

- macOS EDB 설치본(`/Library/PostgreSQL/17`)에 pgvector를 소스로 설치하는 경우, `pg_config`가 존재하지 않는 SDK 경로를 가리키면 `PG_SYSROOT`를 지금 SDK로 덮어써야 컴파일됩니다.

```bash
git clone --depth 1 --branch v0.8.7 https://github.com/pgvector/pgvector.git /tmp/pgvector
```

```bash
cd /tmp/pgvector && make PG_CONFIG=/Library/PostgreSQL/17/bin/pg_config PG_SYSROOT="$(xcrun --show-sdk-path)" && sudo make install PG_CONFIG=/Library/PostgreSQL/17/bin/pg_config PG_SYSROOT="$(xcrun --show-sdk-path)"
```

### `.env`

`.env.example`을 복사해 값을 채웁니다. `.env`는 git에 올리지 않습니다.

```bash
cp .env.example .env
```

| 키 | 설명 |
|---|---|
| `GOOGLE_API_KEY` | Gemini API 키 (임베딩·생성·채점) |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | DB 접속 (기본 DB 이름 `rag`) |
| `EMBEDDING_MODEL`, `EMBEDDING_DIM` | 기본 `gemini-embedding-2`, `1536` (실험 시작 전에 고정) |
| `GENERATION_MODEL` | 평가·피드백·개선 Agent와 기본 RAG 모델 (기본 `gemini-3.6-flash`) |
| `ANSWER_MODEL` | Multi-Agent 답변 Agent 모델 (기본 `gemini-3.7-flash`) |

## 1. 청킹

```bash
python scripts/build_chunks.py
```

- `05_chunks/`에 Recursive 4종(`recursive_{300,500,800,1000}_60.jsonl`)과 Parent-Child(`parent_child_300_60.jsonl`, `.parents.jsonl`)를 만듭니다.
- `--stats`는 파일을 쓰지 않고 개수·길이만 출력합니다.

근거 ID가 기준 답안과 맞는지 확인합니다(251개 전부 존재해야 함).

```bash
python scripts/validate_ids.py
```

## 2. DB 초기화와 적재 (임베딩)

```bash
python scripts/init_db.py
```

```bash
python scripts/load_chunks.py --method parent_child_300_60
```

- 다른 청킹 방식도 같은 방법으로 적재합니다 (`--method recursive_300_60` 등).
- `--dry-run`: API를 호출하지 않고 개수만 확인합니다. `--files 04_신용거래약관 glossary`: 일부 문서만 적재합니다.
- `--no-title`: 임베딩 입력에 제목 prefix를 붙이지 않습니다 (문맥 보존 실험용, experiment 이름 끝에 `_notitle`).
- 이미 저장된 `chunk_id`는 다시 임베딩하지 않습니다.

## 3. 검색 평가

```bash
python scripts/eval_retrieval.py
```

- 적재된 모든 experiment × 검색기(vector, bm25, hybrid, mmr)를 제공 positive 140문항으로 평가합니다.
- child 단계와 parent 단계의 Hit@k, Recall@k, Precision@k, nDCG@k, MRR을 PostgreSQL(`retrieval_eval_runs`, `retrieval_eval_cases`)과 `06_results/*.json`에 저장합니다.
- 질문 유형(용어형/상황형)별 비교: `python scripts/analyze_question_types.py`

## 4. RAG 실행

기본 RAG:

```bash
python scripts/run_rag.py --pipeline basic
```

Multi-Agent (최종 설정 v7이 기본값):

```bash
python scripts/run_rag.py --pipeline multi --tag v7
```

| 옵션 | 설명 |
|---|---|
| `--answer-style` | `parts_guide`(기본, 점검표+안내 규칙) / `parts` / `plain` |
| `--answer-model` | 답변 Agent 모델 (기본 `ANSWER_MODEL`) |
| `--review` | 답변 검토 Agent 추가 (실험 결과 미채택, 기본 꺼짐) |
| `--guards` | 문서 기준일 제공, 시점·모호성 판정 규칙, 근거 없는 단정 금지 (v8, 미채택) |
| `--parts-research` | 점검표에서 근거 없는 요소로 재검색 (v9, 미채택) |
| `--answers-dir` | 다른 기준 답안 폴더 (골든셋: `team_golden_set/03_answers`) |
| `--cases`, `--sets`, `--limit` | 일부 문항만 실행 |
| `--no-save` | 저장하지 않고 결과만 출력 |

실행 기록은 PostgreSQL(`rag_runs`, `rag_case_results`)과 `06_results/rag/<run_id>.jsonl`에 저장되고, 코드 기반 1차 채점(응답 유형 일치, 문맥·인용 근거 Recall)이 함께 출력됩니다.

## 5. 답변 채점 (LLM Judge)

```bash
python scripts/eval_judge.py --run <run_id>
```

- 채점 모델 `gemini-3.8-flash`, 항목: 정확성, 필수 항목 충족, 금지 내용 위반, 근거 충실성, 인용 적합성, 대응 적절성.
- 골든셋 실행을 채점할 때는 `--answers-dir team_golden_set/03_answers`를 함께 줍니다.
- 결과: `06_results/eval/<run_id>__judge.jsonl`, `__judge.summary.json`
- `--rubric judge_v2`: 완화 기준(질문이 직접 묻는 핵심만 정확성에 반영). 결과는 `__judge_v2.jsonl`로 따로 저장되고, 비교표는 `JUDGE=judge_v2 python scripts/compare_runs.py ...`
- `--guards`로 실행한 기록은 Judge 문맥에도 같은 문서 기준일을 넣어 채점합니다.
- 만점이 아닌 문항의 점검표: `python scripts/make_judge_audit.py --run <run_id> --answers-dir <기준 답안 폴더> --out docs/judge_audit.md`

여러 실행 비교표:

```bash
python scripts/compare_runs.py basic_rag v7_ans37flash v7_ans37flash_rep2
```

## 골든셋

골든셋은 `feature/golden-set` 브랜치의 `team_golden_set/`에 있습니다. 브랜치를 병합하지 않고 폴더만 꺼내 쓸 수 있습니다.

```bash
git fetch origin && git archive origin/feature/golden-set team_golden_set | tar -x -C /tmp
```

```bash
python scripts/run_rag.py --pipeline multi --answers-dir /tmp/team_golden_set/03_answers --tag golden
```
