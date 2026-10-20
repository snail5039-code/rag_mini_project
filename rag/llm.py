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


def generate_structured(system: str, user: str, schema, model: str = config.GENERATION_MODEL,
                        temperature: float = 0.0):
    """(파싱된 결과, 사용량 dict)를 돌려준다."""
    from google.genai import types

    res = client().models.generate_content(
        model=model, contents=user,
        config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                           response_schema=schema, temperature=temperature),
    )
    um = res.usage_metadata
    usage = {"model_calls": 1, "input_tokens": um.prompt_token_count or 0,
             "output_tokens": um.candidates_token_count or 0}
    if res.parsed is None:
        raise ValueError(f"구조화 출력 파싱 실패: {res.text[:200]!r}")
    return res.parsed, usage
