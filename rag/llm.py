"""Gemini 생성 모델 호출 (구조화 출력)."""
from __future__ import annotations

import os
import threading

from dotenv import load_dotenv

from . import config

load_dotenv(config.ROOT / ".env")

_CLIENT = None
_LOCK = threading.Lock()


def client():
    """스레드가 동시에 만들면 버려진 클라이언트가 닫히며 다른 스레드의 요청이 실패한다. 하나만 만든다."""
    global _CLIENT
    with _LOCK:
        if _CLIENT is not None:
            return _CLIENT
        from google import genai
        from google.genai import types
        _CLIENT = genai.Client(
            api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"),
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=8, initial_delay=2.0, max_delay=60.0, exp_base=2, jitter=1.0)
            ),
        )
        return _CLIENT


class FatalLLMError(RuntimeError):
    """재시도해도 소용없는 오류(인증·결제·권한). 대체 경로로 숨기지 않고 실행을 멈춘다."""


FATAL_CODES = {401, 402, 403}
PARSE_ATTEMPTS = 2   # 구조화 출력 파싱 실패는 1회 다시 호출한다


def generate_structured(system: str, user: str, schema, model: str = config.GENERATION_MODEL,
                        temperature: float = 0.0):
    """(파싱된 결과, 사용량 dict)를 돌려준다. 파싱에 실패한 시도의 토큰도 사용량에 더한다."""
    from google.genai import errors, types

    usage = {"model_calls": 0, "input_tokens": 0, "output_tokens": 0}
    res = None
    for _ in range(PARSE_ATTEMPTS):
        try:
            res = client().models.generate_content(
                model=model, contents=user,
                config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                                   response_schema=schema, temperature=temperature),
            )
        except errors.APIError as e:
            if e.code in FATAL_CODES:   # 429·5xx는 SDK가 이미 재시도한다
                raise FatalLLMError(f"{e.code}: {e}") from e
            raise
        um = res.usage_metadata
        usage["model_calls"] += 1
        usage["input_tokens"] += um.prompt_token_count or 0
        usage["output_tokens"] += um.candidates_token_count or 0
        if res.parsed is not None:
            return res.parsed, usage
    raise ValueError(f"구조화 출력 파싱 실패: {(res.text or '')[:200]!r}")
