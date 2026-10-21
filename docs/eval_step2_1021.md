# 2번 평가 결과 (2026-10-21): LLM Judge · Ragas · 경로 평가

대상: 1번에서 실행한 두 기록 (제공 180 + 팀 90 = 270문항, 기준 설정 Parent-Child 300/60 + Vector, 답변 모델 gemini-3.6-flash).
Judge·Ragas 모델은 답변 모델과 다른 `gemini-3.8-flash`(temperature 0). 결과 파일은 `06_results/eval/`.

| 평가 | 스크립트 | 결과 파일 |
|---|---|---|
| A. 커스텀 LLM Judge | `scripts/eval_judge.py` | `*__judge.jsonl`, `*__judge.summary.json` |
| B. Ragas 교차 확인(48문항) | `scripts/eval_ragas.py` (`.venv_ragas`에서 실행) | `*__ragas.jsonl`, `*__ragas.summary.json` |
| C. 경로 평가 | `scripts/eval_trajectory.py` | `*__trajectory*.jsonl`, `*__trajectory.summary.json` |
| 사람 보정 표본 30문항 | - | `judge_calibration_sample.md` (사람 판단 칸 비어 있음) |

## A. LLM Judge (0~1로 환산, 정확성은 0/1/2 ÷ 2)

| 지표 | 기본 RAG 전체 | Multi-Agent 전체 | 기본 제공 | MA 제공 | 기본 팀 | MA 팀 |
|---|---:|---:|---:|---:|---:|---:|
| 정확성 | 0.763 | **0.789** | 0.792 | **0.822** | 0.706 | **0.722** |
| 정확성 만점 비율 | 0.567 | **0.589** | 0.622 | **0.656** | 0.456 | 0.456 |
| must_include 충족 | 0.771 | **0.802** | 0.790 | **0.833** | 0.733 | **0.742** |
| must_not 위반율 | 0.015 | 0.015 | 0.011 | 0.006 | 0.022 | 0.033 |
| 충실성 | 0.998 | 0.998 | 1.000 | 1.000 | 0.994 | 0.994 |
| 인용 지지 | 0.963 | **0.989** | 0.972 | **0.992** | 0.944 | **0.983** |
| 행동 적절 | 0.944 | **0.952** | 0.956 | **0.967** | 0.922 | 0.922 |

- Judge 토큰: 기본 RAG 입력 859,847 / 출력 68,635, Multi-Agent 입력 922,829 / 출력 68,887.
- 지어낸 내용(충실성)은 거의 없고, 점수를 깎는 쪽은 **기준 답안의 핵심 항목 누락**(must_include)이다.

## B. Ragas (같은 48문항, answer/correct 기대 문항만)

| 지표 | 기본 RAG | Multi-Agent |
|---|---:|---:|
| Faithfulness | 0.915 | 0.874 |
| FactualCorrectness | 0.529 | 0.499 |
| ContextRecall | 0.831 | 0.859 |

- Judge와의 상관: 정확성 0.28(기본), -0.30(MA). 일치하지 않는다. Ragas의 FactualCorrectness는 주장 단위 F1이라 기준 답안이 짧은 제공 positive에서 낮게 나온다(제공 0.30~0.41, 팀 0.64~0.70).
- 따라서 Ragas는 절대 점수보다 **Judge 점수가 크게 어긋나는 문항을 찾는 교차 확인**으로만 쓴다.

## C. 경로 평가 (Multi-Agent 270문항)

| 지표 | 값 |
|---|---:|
| 기대 경로 일치(strict) | 0.930 (제공 0.944 / 팀 0.900) |
| 재검색률 | 0.081 (22문항) |
| 재검색한 문항의 최종 통과율 | 0.455 |
| 헛된 재검색(max_rounds 또는 새 문맥 0) | 13 |
| 보류·거절 문항의 불필요한 재검색 | 10 (팀 9) |
| 검색 범위 준수 / 검색어 중복 | 1.000 / 0건 |
| LLM 경로 Judge(50문항) | 1.000 |

- 기대 경로: 기본 `orchestrator → search → evaluate → answer`, 근거 ID 3개 이상이면 재검색 1회 경로도 허용.
- LLM 경로 Judge는 헛된 재검색 문항에도 모두 통과를 줘서 변별력이 없다. 코드 지표(C-1)를 주 지표로 본다.

## 주의

- Judge 사람 보정은 아직 하지 않았다. `judge_calibration_sample.md` 30문항에 사람 판단을 채워야 Judge 신뢰도가 확정된다.
- Judge 표본 확인에서 NEG056처럼 `must_not_include`를 과하게 위반으로 보는 경우가 있었다.
