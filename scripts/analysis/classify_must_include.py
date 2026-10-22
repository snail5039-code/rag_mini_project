"""C-1: 골든셋의 must_include 항목을 핵심(core)과 부가(extra)로 나눈다 (LLM 분류, 결과는 사람이 검토할 수 있게 파일로 저장).

핵심: 질문이 직접 묻는 결론·수치·조건 등 이게 빠지면 답이 틀리거나 쓸모없어지는 항목
부가: 단서·한계·참고·일반 주의처럼 있으면 좋지만 빠져도 핵심 답은 성립하는 항목

    python scripts/analysis/classify_must_include.py
출력: 06_results/eval/must_include_core.json  {golden:case_id: [{item, level, reason}]}
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from rag import config, llm  # noqa: E402
from scripts.run_rag import load_cases  # noqa: E402

MODEL = "gemini-3.8-flash"
OUT = config.ROOT / "06_results" / "eval" / "must_include_core.json"


class Item(BaseModel):
    item: str
    level: Literal["core", "extra"]
    reason: str


class Result(BaseModel):
    items: list[Item]


SYSTEM = """당신은 금융 질의응답 골든셋의 검수자입니다. must_include 항목 각각이 이 질문의 답에서 '핵심(core)'인지 '부가(extra)'인지 나눕니다.
- core: 질문이 직접 묻는 결론·수치·조건·행동이거나, 빠지면 답이 틀리거나 오해를 주는 항목.
- extra: 단서·한계·참고·일반 주의처럼 있으면 더 좋지만 빠져도 핵심 답은 성립하는 항목.
보류·거절·되묻기 질문이면 그 행동 자체(문서에 없음, 거절, 무엇을 되물을지)와 확인할 곳 안내는 core이고, 부연 설명은 extra입니다.
항목 원문(item)은 입력과 똑같이 그대로 돌려줍니다. 항목마다 한 문장으로 이유를 적습니다."""


def classify(case: dict) -> list[dict]:
    user = (f"질문: {case['question']}\n기대 행동: {case['expected_behavior']}\n기준 답안: {case['reference_answer']}\n"
            f"must_include: {json.dumps(case.get('must_include', []), ensure_ascii=False)}")
    out, _ = llm.generate_structured(SYSTEM, user, Result, model=MODEL, temperature=0.0)
    got = {i.item: i for i in out.items}
    res = []
    for m in case.get("must_include", []):
        i = got.get(m)
        res.append({"item": m, "level": i.level if i else "core", "reason": i.reason if i else "분류 누락 → core로 처리"})
    return res


def main() -> None:
    cases = load_cases(["base", "negative", "life", "add"], ["provided", "team"])
    cases = [c for c in cases if c.get("must_include")]
    result, errors = {}, []

    def work(c):
        try:
            return f"{c['golden']}:{c['case_id']}", classify(c)
        except Exception as e:  # noqa: BLE001
            errors.append((c["case_id"], repr(e)[:150]))
            return None

    with ThreadPoolExecutor(16) as ex:
        for r in ex.map(work, cases):
            if r:
                result[r[0]] = r[1]
    if not result:
        raise SystemExit(f"분류 결과가 없어 저장하지 않습니다. 오류 {len(errors)}건 {errors[:2]}")
    OUT.write_text(json.dumps({"model": MODEL, "items": result}, ensure_ascii=False, indent=1), encoding="utf-8")
    n_items = sum(len(v) for v in result.values())
    n_core = sum(i["level"] == "core" for v in result.values() for i in v)
    print(f"문항 {len(result)}개, 항목 {n_items}개 (core {n_core}, extra {n_items - n_core}), 오류 {len(errors)}건 {errors[:3]}")


if __name__ == "__main__":
    main()
