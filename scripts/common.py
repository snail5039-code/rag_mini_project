"""분석·비교 스크립트가 함께 쓰는 작은 도구."""
from __future__ import annotations

import json
from pathlib import Path


def jl(path) -> list[dict]:
    """JSONL 파일을 읽어 한 줄당 dict 하나로 돌려준다."""
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
