# 인수인계: 평가·개선 작업 현황 (2026-10-21 종료 시점)

> **2026-10-22 갱신**: 이 문서는 10-21 종료 시점 기준이다. 이후 P3·P3-b(평가 프롬프트, 코드에 남음), G1·G2(장애 대응), GR1·GR3(가드레일)이 추가되어 **코드는 더 이상 `dev`와 같지 않다.** 최신 상태는 [README 5장](../README.md), [eval_changes_log.md](./eval_changes_log.md) 5·6장, [guardrail_review_1021.md](./guardrail_review_1021.md)를 본다.

내일 "AI 에이전트 엔지니어 1회차" 계정의 새 Gemini API 키로 이어서 작업할 때 이 문서만 읽고 시작할 수 있게 정리했다. 프로젝트 전체 설명은 [README.md](../README.md), 설계는 [pipeline.md](./pipeline.md), 이전 인수인계는 [handoff.md](./handoff.md)(환경 준비 방법 포함)에 있다. 이 문서는 **오늘 평가·개선 작업**만 다룬다.

## 1. 한 줄 요약

`team_to_do_1021.md`의 8개 작업 중 1~4번은 끝냈고, 5번(한 번에 하나씩 수정 → 재실행 → 비교)은 **P2 계열과 P1을 시도했지만 모두 효과가 없어 되돌렸다.** 코드는 `dev`와 같은 기준선 상태다. 남은 일은 **D(표·그래프 정리), 6번(README 정리), 7번(guardrail 등 검토)**이다.

## 2. 위치와 상태

| 항목 | 값 |
|---|---|
| 저장소 | `snail5039-code/rag_mini_project` |
| 작업 브랜치 | `eval/1021-baseline` (`dev`에서 분기, 원격에 push됨. 나중에 `dev`와 병합 예정) |
| 로컬 작업 폴더 | `E:\rag_mini_project` (선생님 저장소 `aim-ai-agent`와 무관한 별도 clone) |
| 마지막 커밋 | `993a792` (P1 부분 확인 결과). 이 문서를 추가한 커밋이 그 뒤에 있다 |
| 코드 상태 | `rag/` 폴더가 `dev`와 **차이 0줄** (P2·P2-b·P2-c·P1 프롬프트 수정은 모두 되돌림). 수정된 것은 `scripts/run_rag.py`의 DB 연결 닫기(병렬 실행용)뿐 |
| 팀 골든셋 | `team_golden_set/` 90문항(ADD 30 + 가이드북 10 + 기본 positive 30 + 기본 negative 20). 사람 원문 확인 칸은 아직 비어 있음 |
| 지시서 | 팀 저장소 `feature/golden-set` 브랜치의 `team_to_do_1021.md` (작업 1~8번) |

## 3. 오늘 한 일

| 번호 | 작업 | 결과 | 문서 |
|---|---|---|---|
| 1 | 검색 평가 + 기본 RAG·Multi-Agent 실행 (제공 180 + 팀 90) | 완료 | README 5장 |
| 2 | LLM Judge · Ragas · 경로 평가 | 완료 | [eval_step2_1021.md](./eval_step2_1021.md) |
| 3 | 문제 유형 분석과 개선점 | 완료 | [eval_step3_problems_1021.md](./eval_step3_problems_1021.md) |
| 4 | 문제점·개선책 우선순위 | 완료 | [eval_step4_priority_1021.md](./eval_step4_priority_1021.md) |
| 5 | 수정 → 재실행 → 비교 (P2, P2-b, P2-c, P1) | 4번 시도, **전부 미채택·되돌림** | [eval_changes_log.md](./eval_changes_log.md) |
| 채점 보정(C) | 답할 수 없는 질문 제외 재집계, `must_include` 핵심/부가 분리 | 완료 | [eval_rescore_1021.md](./eval_rescore_1021.md) |
| 변동 측정(B) | 기준선 3회 반복 실행 | 완료 | eval_changes_log.md "B" |
| README | 평가의 한계점과 보완 방법 추가 | 완료 | README 5장 |

### 핵심 수치 (Multi-Agent 기준선 270문항, 기본 RAG는 괄호)

| 지표 | 값 |
|---|---|
| 응답 유형 엄격 / 완화 | 0.830 / 0.959 (0.730 / 0.941) |
| Judge 정확성 / 만점 비율 | 0.789 / 0.589 (0.763 / 0.567) |
| 만점 비율 (핵심 항목 기준 보정, 추정) | 약 0.785 (0.767) |
| 충실성 / 문맥 Recall | 0.998 / 0.935 (0.998 / 약 0.916) |
| 평균 토큰 / 총 토큰 | 7,606 / 2,053,492 (3,179 / 858,374) |
| 인용 Hit (답할 수 있는 문항만, 팀 세트) | 1.000 (0.952) |

실행 ID: 기본 RAG `20261021_115125__basic_rag__both_golden`, Multi-Agent `20261021_120715__multi_agent__both_golden`.

### 실행 간 변동 (같은 코드 3회: `120715`, `165034`, `165515`)
응답 유형 엄격 ±0.02, 완화 ±0.004, Judge 정확성 ±0.03, 만점 비율 ±0.07(팀 ±0.11), 토큰 ±1%, 충실성 ±0.004. 응답 유형이 3회 같은 문항 233/270.
**단일 실행에서 효과가 있다고 볼 최소 변화**: 엄격 +0.03, 완화 +0.01, Judge 정확성 +0.03, 만점 비율 +0.08.

### 수정 시도 요약 (모두 되돌림)
| 시도 | 변경 | 결과 |
|---|---|---|
| P2 | 답변 프롬프트의 보류 판단 기준 | 보류 대상 8문항 중 6개 고침, 과보류 0→3. 순이득 미미 |
| P2-b | 위 문구를 좁힘 | 5/8, 과보류 3. 미채택 |
| P2-c | 평가 단계에서 값의 근거 문장을 먼저 인용 | 6/8, 과보류 5, 토큰 +6.6%. 미채택 |
| P1 | 답변 프롬프트에 하위 질문·단서 포함 지시 | 62문항 부분 확인. 부가 항목 충족률 0.103→0.123, 문항 선택 편향 수준. 미채택 |

**교훈**: 프롬프트 한 줄 수정은 오류를 다른 곳으로 옮길 뿐 순이득이 없었다(변동 폭과 비슷한 크기). 보류 판단은 평가 단계와 답변 단계 두 곳에서 일어나 한쪽만 고쳐서는 한계가 있다. 과보류 원인 중 일부는 평가 단계의 `out_of_scope` 오판이다.

## 4. 내일 시작 체크리스트 (새 계정·새 API 키)

1. 새 Gemini API 키를 **직접** `E:\rag_mini_project\.env`의 `GEMINI_API_KEY`에 넣는다. 키는 채팅에 붙여 넣지 않고 git에도 올리지 않는다(`.env`는 git 제외).
2. 새 키로 한 번 호출해 본다:
   ```bash
   cd /e/rag_mini_project && python -c "
   from google import genai; from dotenv import dotenv_values
   c=genai.Client(api_key=dotenv_values('.env')['GEMINI_API_KEY'])
   print(c.models.generate_content(model='gemini-3.8-flash',contents='안녕이라고만 답해').text)"
   ```
3. 새 계정에서 아래 모델을 쓸 수 있는지 확인한다: 답변 `gemini-3.6-flash`, Judge/Ragas `gemini-3.8-flash`, 임베딩 `gemini-embedding-2`(차원 1536). 모델이 다르면 비교 가능성이 깨지므로 같은 모델을 써야 한다. 임베딩은 **DB에 이미 적재**되어 있어 다시 만들 필요가 없고, 질문 임베딩만 호출한다.
4. PostgreSQL 서비스(`postgresql-x64-17`)가 켜져 있고 `rag` DB에 청크가 적재되어 있는지 확인한다(`scripts/dev/check_retrieval.py` 또는 다음 쿼리). `.env`에 `POSTGRES_DB=rag`여야 한다.
   ```bash
   cd /e/rag_mini_project && python -c "
   import psycopg,os; from dotenv import load_dotenv; load_dotenv('.env')
   from rag import db; c=db.connect(); print(c.execute('select count(*) from chunks').fetchone(), c.execute('select count(*) from parent_chunks').fetchone())"
   ```
   기대값은 child 3,041, parent 965.
5. 브랜치 확인: `git checkout eval/1021-baseline && git pull`.
6. 환경 정보: 이 PC에는 pgvector 0.8.1을 직접 빌드해 설치했다(VS Build Tools 설치, `E:\build_tmp\pgvector`). Ragas는 충돌 때문에 `E:\rag_mini_project\.venv_ragas`(git 제외)에서만 실행한다. 다른 PC에서 이어갈 때는 [handoff.md](./handoff.md) 3장을 따른다.

## 5. 남은 작업 (우선순위 순)

### D. 결과 표와 시각화 (LLM 호출 없음, 비용 0원) ← 내일 가장 먼저
저장된 결과만으로 만들 수 있다. 사용자에게 보여 줄 5번 작업 결과 정리이기도 하다.
- 그림(예, `docs/images/eval_*.png`, matplotlib + 한글 폰트 Malgun Gothic): ① 기본 RAG vs Multi-Agent 대표 지표 막대, ② 실패 원인 구성비 원형 차트(`failure_analysis.json`), ③ 평균 토큰·응답 시간 비교, ④ 시도별(P2, P2-b, P2-c, P1) 점수 변화와 변동 폭 오차 막대(`variance_baseline.json`), ⑤ 정확성 만점 비율의 원래 vs 핵심 기준 보정(`rescore_core.json`), ⑥ 개선·악화·동일 문항 수(`*_compare.json`).
- 대표 정답률 지표를 사용자와 정한다. 후보: 응답 유형 완화(행동이 맞는가), Judge 정확성 보정 만점 비율(내용이 맞는가).
- 비용 표: 단계별 토큰(아래 7장).

### 6번. README에 과정 정리
README 5장에 "평가·개선 과정" 절 추가: 1~4번 결과, 시도(P2 계열, P1)와 결과, 변동 폭, 한계점(이미 있음), 시각화 그림. 상세는 `docs/`의 각 문서로 링크한다.

### 7번. guardrail · fault tolerance · fallback 검토
필요한지 파악하고 필요하면 방식·막을 문제·평가 방법을 정리해 알려 준다(사용자가 하나씩 추가하며 재평가할 예정). 현재 코드 사실: 인젝션 무시 규칙(`COMMON_RULES`)과 보류·거절 응답 유형은 있고, 입력/출력 검증, 검색기 대체 경로, LLM 오류 대응(`google-genai` 재시도 8회 설정 외)은 별도 구현이 없다. 어떤 문제를 막는지는 한계점·3번 분석의 문제 유형과 연결해 정리한다.

### 선택·후순위
- **사람 보정**: `06_results/eval/judge_calibration_sample.md` 30문항에 사람 판단을 채워 Judge 일치율을 낸다. `must_include_core.json`(LLM 분류)도 사람이 검토한다.
- **팀 골든셋 사람 검수**: `team_golden_set/verification/*.md`의 원문 확인 칸.
- **시스템 개선 후보**(비용이 들어 사용자 승인과 크레딧 확인 후): 평가 단계의 `out_of_scope` 오판 교정, 헛된 재검색 종료 조건(P5, 토큰의 약 14%), 검색 양(P6, `max_parents` 5→7 → `child_k` 8→12), 답변 후 누락 점검 단계(완전성, 토큰 증가). 변경 전에는 반드시 **문구·코드를 사용자에게 먼저 보여 주고 승인**을 받는다.
- P1 전체 270문항 실행은 **하지 않기로 함**(효과 증거를 더하지 못함).
- 추출 오류 후보 재검증(ADD-RP14 등, README 1장), `dev` → `main` PR.

## 6. 자주 쓰는 명령 (모두 `E:\rag_mini_project`에서)

```bash
# 실행 (병렬 16개, 270문항 약 5분). 진행률은 끝나야 로그에 나온다
PYTHONIOENCODING=utf-8 python scripts/run_rag.py --pipeline multi --golden both --workers 16
# 특정 문항만 (저장 안 함)
PYTHONIOENCODING=utf-8 python scripts/run_rag.py --pipeline multi --golden both --no-save --cases POS120 ADD-PF15
# Judge (실행 ID는 06_results/rag/에 있음, 병렬 16개로 약 4분)
PYTHONIOENCODING=utf-8 python scripts/eval_judge.py --run <run_id> --workers 16
# 경로 평가 (LLM 경로 Judge는 --llm-judge-n 0 이면 호출 없음)
PYTHONIOENCODING=utf-8 python scripts/eval_trajectory.py --run <run_id> --llm-judge-n 0
# 실패 원인 분류 / 두 실행 비교 / 변동 폭 / 재채점
PYTHONIOENCODING=utf-8 python scripts/analysis/analyze_failures.py --runs "라벨=run_id" ... --out <파일명>.json
PYTHONIOENCODING=utf-8 python scripts/analysis/compare_runs.py --base <run_id> --new <run_id> --name <이름>
PYTHONIOENCODING=utf-8 python scripts/analysis/variance.py
PYTHONIOENCODING=utf-8 python scripts/analysis/rescore_core.py      # 핵심/부가 기준 재채점 (LLM 없음)
PYTHONIOENCODING=utf-8 python scripts/analysis/rescore_nonllm.py    # 답할 수 없는 질문 제외 재집계 (LLM 없음)
# Ragas (별도 가상환경)
.venv_ragas/Scripts/python.exe scripts/eval_ragas.py --run <run_id> --n 50
# 크레딧이 끊겨 일부 문항이 오류(402)로 실패했을 때: 실패 문항만 다시 돌려 합치기
python scripts/analysis/merge_retry.py --run <원래 run_id> --retry <재실행 run_id> --keep-dir 06_results/eval/<폴더>
```

주의: PowerShell이 아니라 Git Bash에서 실행한 명령이다. Windows 콘솔에서 한글이 깨지면 `PYTHONIOENCODING=utf-8`을 붙인다. 사용자 계정의 셸 환경변수에 `POSTGRES_DB` 같은 값이 있으면 `.env`보다 우선하므로(`load_dotenv`는 덮어쓰지 않음) 다른 `.env`를 `source`한 셸에서 실행하지 않는다.

## 7. 비용 기록과 주의

- **오늘 사용량(추정)**: 약 24M 토큰. 내역(대략): 1·2번과 Ragas·검색 평가 약 6M, P2 계열 3회 약 11M, 핵심/부가 분류 0.3M, 기준선 반복 6M, P1 부분 확인 0.7M.
- **단가(대략)**: 100만 토큰당 약 2,000~2,500원 수준으로 보인다(사용량과 충전액으로 역산한 값이라 정확하지 않다). 270문항 실행 1회 약 2.1M 토큰 + Judge 약 0.93M 토큰이 한 번의 재평가 비용이다.
- **크레딧 화면은 늦게 반영된다.** 오늘 잔액이 15,386원에서 36,549원으로 보였다가 실제로는 4,830원이었다(표시 지연). 큰 실행 전에는 잔액을 새로고침해서 확인하고, 사용 비용 그래프는 믿지 않는다. 크레딧이 소진되면 `402 RESOURCE_EXHAUSTED`가 나고 스크립트는 오류 문항을 기록하고 계속 진행하므로 `merge_retry.py`로 복구한다.
- **비용 절약 원칙**: 수정이 영향을 주는 문항만 먼저 부분 확인 → 효과가 있을 때만 전체 실행, 기본 RAG는 수정과 무관하면 기준선 재사용, 큰 실행 전에 사용자에게 잔액 확인 요청, LLM이 필요 없는 일(D, 재집계)을 먼저 한다.

## 8. 작업 방식 (사용자 선호)

- 수정은 **한 번에 하나씩**, 구체적인 문구·코드를 **먼저 보여 주고 승인**을 받은 뒤 한다.
- 단계가 끝날 때마다 사용자에게 **결과를 보고**한다(표, 원인, 비용, 판정).
- 모든 시도는 `docs/eval_changes_log.md`에 남기고(되돌린 것 포함), 커밋·push는 `eval/1021-baseline`에 한다. **선생님 저장소(`jun-yu-edu/aim-ai-agent`)에는 절대 push하지 않는다.**
- 점수를 읽을 때는 실행 간 변동 폭(3장)과 채점 기준의 엄격함(한계점)을 함께 설명한다.
