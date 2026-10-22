"""질문 유형별 검색 분석: 정확한 용어를 묻는 질문 vs 상황을 풀어 쓴 질문에서 검색기별 성능 비교.

질문 유형은 LLM으로 한 번 분류해 06_results/question_types.json에 저장하고(다시 실행하면 재사용),
검색 성능은 이미 저장된 retrieval_eval_cases(Parent-Child, 검색기 4종)에서 읽는다. 추가 검색 호출은 없다.

  python scripts/analyze_question_types.py
"""
import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, Field

from rag import config, db
from rag.llm import generate_structured

FILES = ["positive_cases.jsonl", "positive_life_guide_cases.jsonl", "additional_cases.jsonl"]
OUT = config.ROOT / "06_results" / "question_types.json"

PROMPT = """금융 문서 검색 질문을 두 유형 중 하나로 분류하세요.
- term     : 특정 용어·제도·조항의 정의나 내용을 직접 묻는 질문. 질문에 찾을 용어나 제도명이 그대로 들어 있다.
             예) "휴면성 증권계좌는 어떤 계좌인가요?", "DB형 퇴직연금의 급여는 어떻게 정해지나요?"
- situation: 사용자의 상황·사례·오해를 풀어 쓰고 판단을 묻는 질문. 문서의 용어와 다른 일상 표현이 많다.
             예) "인증번호를 지인에게 알려준 뒤 휴대전화를 잃어버렸는데 회사가 배상하나요?" """


class Label(BaseModel):
    qtype: Literal["term", "situation"]
    reason: str = Field(description="한 문장")


def classify(cases: list[dict]) -> dict[str, str]:
    cached = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    todo = [c for c in cases if c["case_id"] not in cached]

    def work(c):
        out, _ = generate_structured(PROMPT, c["question"], Label)
        return c["case_id"], out.qtype

    with ThreadPoolExecutor(8) as ex:
        for cid, qtype in ex.map(work, todo):
            cached[cid] = qtype
    OUT.write_text(json.dumps(cached, ensure_ascii=False, indent=1), encoding="utf-8")
    return cached


def main() -> None:
    cases = [json.loads(l) for f in FILES for l in (config.ANSWERS_DIR / f).read_text(encoding="utf-8").splitlines()]
    labels = classify(cases)
    counts = defaultdict(int)
    for c in cases:
        counts[labels[c["case_id"]]] += 1
    print("질문 유형:", dict(counts))

    conn = db.connect()
    runs = conn.execute(
        """SELECT DISTINCT ON (retriever) run_id, retriever FROM retrieval_eval_runs
           WHERE experiment_id LIKE 'parent\\_child\\_300\\_60\\_\\_%' ORDER BY retriever, created_at""").fetchall()
    keys = ["child_hit@1", "child_hit@5", "child_recall@5", "child_mrr"]
    print(f"\n{'검색기':8}{'유형':11}{'n':>4}" + "".join(f"{k.replace('child_', ''):>11}" for k in keys))
    result = {}
    for run_id, retriever in runs:
        rows = conn.execute("SELECT case_id, metrics FROM retrieval_eval_cases WHERE run_id = %s", (run_id,)).fetchall()
        by = defaultdict(list)
        for cid, m in rows:
            by[labels.get(cid, "?")].append(m)
        for qtype in ("term", "situation"):
            ms = by[qtype]
            avg = {k: sum(m[k] for m in ms) / len(ms) for k in keys}
            result[f"{retriever}:{qtype}"] = {"n": len(ms), **avg}
            print(f"{retriever:8}{qtype:11}{len(ms):>4}" + "".join(f"{avg[k]:11.3f}" for k in keys))
    (config.ROOT / "06_results" / "question_type_retrieval.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
