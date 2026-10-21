# 팀 작업 지시서 (2026-10-21)

Claude Code에 지시할 내용입니다. 번호 순서대로 진행하며, 4번 이후에는 사용자가 단계별로 다시 지시합니다.

## 용어

| 이름 | 위치 | 설명 |
|---|---|---|
| 제공 골든셋 | `rag_mini_project/02_questions`, `rag_mini_project/03_answers` | 선생님이 만들어 주신 골든셋 |
| 팀 골든셋 | `rag_mini_project/team_golden_set` | 우리 팀이 새로 만든 골든셋 (ADD 30 + 가이드북 10 + 기본 positive 30 + 기본 negative 20) |

## 작업 목록

### 1. RAG 검색 평가와 RAG Agent 검색 평가 실행
- 제공 골든셋과 팀 골든셋, 두 골든셋으로 **RAG 검색 평가**와 **RAG Agent 검색 평가**를 실행한다.

### 2. LLM judge · RAGAS · agenteval로 평가
- 1번 실행 결과를 기준으로 **LLM judge, RAGAS, agenteval**을 사용해 RAG의 **검색 · 답변 · 경로** 평가를 실행한다.

### 3. 문제점 파악과 개선점 제시
- 2번 평가 결과를 바탕으로 문제점이 어디에 있는지 파악하고 개선점을 제시한다.
- 문제점의 유형은 [`dev` 브랜치 README.md의 "5. 평가"](https://github.com/snail5039-code/rag_mini_project/tree/dev)를 읽으면 알 수 있다.

### 4. 문제점·개선책을 중요도 순으로 정리
- 3번의 문제점과 개선책을 **중요한 순서대로** 정리한다.
- 이후 사용자가 "**한 번에 하나씩만 수정해서, 같은 질문으로 재실행하고, 다시 RAG와 RAG Agent를 평가**"하라고 지시할 것이다.

### 5. 재실행 결과 정리와 시각화
4번에서 재실행한 결과를 바탕으로 다음을 정리해 보여준다.
- 정답률의 변화
- 이전과 비교해 개선된 부분의 원인 분석
- 결과
- 이 과정에서 사용된 token 비용 등
- 그래프, 원형 차트 등 적절한 시각화 도구를 사용해 시각화

### 6. README.md 정리
- 위 일련의 과정을 `README.md`에 정리해서 올린다.

### 7. (추가 작업) guardrail · fault tolerance · fallback 검토
- guardrail, fault tolerance, fallback이 우리 RAG Agent의 성능을 올리는 데 **필요한지** 파악한다.
- 필요하다면 **어떤 방식으로, 어떤 문제를 방지하고 개선할 수 있는지** 정리해서 알려준다.
- 이후 사용자가 **하나씩 추가**하면서 다시 RAG 평가와 RAG Agent 평가를 실행할 것이다.

### 8. 브랜치 작업
- 이런 작업 도중에 **새 branch를 만들어** commit, push한다.
- 나중에 `dev`와 병합할 예정이다.
