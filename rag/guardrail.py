"""가드레일: 입력 검증(GR1)과 출력 검사(GR3, 기록만).

입력 검증은 LLM 호출 없이 빈 질문·과도하게 긴 질문을 안내 문구로 돌려보낸다.
출력 검사는 응답을 막지 않고 `guardrail_flags`에 기록만 한다. 실제 취약점이 측정된 항목만 나중에 차단한다(GR4).
"""
from __future__ import annotations

import re

MAX_QUESTION_CHARS = 2000

INPUT_MESSAGES = {
    "empty": "질문이 비어 있습니다. 궁금한 내용을 입력해 주세요.",
    "too_long": f"질문이 너무 깁니다. {MAX_QUESTION_CHARS}자 이하로 줄여서 다시 입력해 주세요.",
}


def validate_question(question: str | None) -> str | None:
    """문제가 있으면 사유('empty', 'too_long')를, 없으면 None을 돌려준다."""
    if question is None or not question.strip():
        return "empty"
    if len(question) > MAX_QUESTION_CHARS:
        return "too_long"
    return None


def input_rejection(reason: str, pipeline: str, elapsed_ms: int = 0) -> dict:
    """LLM·검색 없이 돌려주는 응답. run()의 반환과 같은 키를 갖는다."""
    return {
        "response_type": "clarify",
        "answer": INPUT_MESSAGES[reason],
        "reason": f"입력 검증: {reason}",
        "citations": [],
        "invalid_citations": [],
        "scope_files": 0,
        "search_rounds": 0,
        "stop_reason": "input_rejected",
        "used_queries": [],
        "evaluation": {"decision": "input_rejected", "reason": reason},
        "retrieved_children": [],
        "delivered_parents": [],
        "trace": [{"step": "guardrail_input", "reason": reason}],
        "usage": {"model_calls": 0, "search_calls": 0, "input_tokens": 0, "output_tokens": 0, "elapsed_ms": elapsed_ms},
        "guardrail_flags": [f"input_{reason}"],
        "degraded": False,
        "degraded_reasons": [],
    }


_PII = [
    ("pii_resident_id", re.compile(r"(?<!\d)\d{6}[- ]?[1-4]\d{6}(?!\d)")),
    ("pii_card_number", re.compile(r"(?<!\d)\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}(?!\d)")),
]
_ADVICE = re.compile(
    r"(매수|매도|가입|투자)\s*(하세요|하십시오|하시기\s*바랍니다|하시길\s*권|를\s*추천드립니다|을\s*추천드립니다)"
    r"|수익(을|이)?\s*(반드시|꼭|100%)\s*보장(합니다|됩니다|해\s*드립니다|하겠습니다)|반드시\s*(오릅니다|수익이\s*납니다)"
)


def check_output(response_type: str, answer: str, valid_citation_count: int) -> list[str]:
    """응답을 막지 않고 의심 신호를 목록으로 돌려준다."""
    flags = []
    if response_type in ("answer", "correct") and valid_citation_count == 0:
        flags.append("no_citation")
    for name, pat in _PII:
        if pat.search(answer or ""):
            flags.append(name)
    if response_type in ("answer", "correct") and _ADVICE.search(answer or ""):
        flags.append("advice_phrase")
    return flags
