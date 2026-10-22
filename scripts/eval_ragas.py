"""B. Ragas 교차 확인: A(커스텀 Judge)의 충실성·정확성·문맥 재현율이 일반 RAG 지표와 어긋나지 않는지 확인한다.

ragas 0.4.3은 이 PC의 base 환경과 충돌해 별도 가상환경(.venv_ragas)에서 실행한다.
    .venv_ragas/Scripts/python.exe scripts/eval_ragas.py --run <run_id> --n 50

대상: 기대 행동이 answer/correct 계열인 문항만 (보류·거절·되묻기 문항은 Ragas 지표가 맞지 않음).
세트(제공/팀 × base/life/add/negative)별로 고르게 n개를 뽑는다. 두 실행(기본 RAG, Multi-Agent)에 같은 문항을 쓴다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
RAGAS_MODEL = "gemini-3.8-flash"
FILES = {"base": "positive_cases.jsonl", "negative": "negative_cases.jsonl",
         "life": "positive_life_guide_cases.jsonl", "add": "additional_cases.jsonl"}
GOLDEN_DIRS = {"provided": ROOT / "03_answers", "team": ROOT / "team_golden_set" / "03_answers"}
ANSWER_PREFIX = ("answer", "correct", "ignore_injection_and_answer", "ignore_injection_and_correct")


def load_cases() -> dict:
    cases = {}
    for golden, d in GOLDEN_DIRS.items():
        for qset, fn in FILES.items():
            for line in (d / fn).read_text(encoding="utf-8").splitlines():
                c = json.loads(line)
                cases[(golden, c["case_id"])] = {**c, "golden": golden, "question_set": qset}
    return cases


def pick(recs: list[dict], cases: dict, n: int) -> list[dict]:
    eligible = [r for r in recs if cases[(r["golden"], r["case_id"])]["expected_behavior"].startswith(ANSWER_PREFIX)]
    groups: dict[tuple, list] = {}
    for r in sorted(eligible, key=lambda r: r["case_id"]):
        groups.setdefault((r["golden"], r["question_set"]), []).append(r)
    per = max(1, n // len(groups))
    out = []
    for g in sorted(groups):
        rs = groups[g]
        step = max(1, len(rs) // per)
        out += rs[::step][:per]
    return out[:n]


async def main_async(args) -> None:
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import ContextRecall, FactualCorrectness, Faithfulness

    # ragas 0.4의 구글 어댑터는 비동기를 지원하지 않아, 같은 API 키로 Gemini의 OpenAI 호환 엔드포인트를 쓴다.
    client = AsyncOpenAI(api_key=os.getenv("GEMINI_API_KEY"),
                         base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
    llm = llm_factory(RAGAS_MODEL, client=client, temperature=0, max_tokens=8192)
    faith, fact, recall = Faithfulness(llm=llm), FactualCorrectness(llm=llm), ContextRecall(llm=llm)

    method = "parent_child_300_60"
    parents = {}
    for line in (ROOT / "05_chunks" / f"{method}.parents.jsonl").read_text(encoding="utf-8").splitlines():
        p = json.loads(line)
        parents[p["parent_id"]] = p["content"]

    cases = load_cases()
    recs = [json.loads(l) for l in (ROOT / "06_results" / "rag" / f"{args.run}.jsonl").read_text(encoding="utf-8").splitlines()]
    chosen = pick(recs, cases, args.n)
    print(f"{args.run}: {len(chosen)}문항 (세트별 균등)")
    sem = asyncio.Semaphore(args.workers)

    async def one(rec):
        c = cases[(rec["golden"], rec["case_id"])]
        ctxs = [parents[p["parent_id"]] for p in rec["delivered_parents"] if p["parent_id"] in parents]
        row = {"run_id": rec["run_id"], "case_id": rec["case_id"], "golden": rec["golden"],
               "question_set": rec["question_set"], "response_type": rec["response_type"]}
        async with sem:
            for name, coro in (
                ("faithfulness", lambda: faith.ascore(user_input=rec["question"], response=rec["answer"], retrieved_contexts=ctxs)),
                ("factual_correctness", lambda: fact.ascore(response=rec["answer"], reference=c["reference_answer"])),
                ("context_recall", lambda: recall.ascore(user_input=rec["question"], retrieved_contexts=ctxs, reference=c["reference_answer"])),
            ):
                try:
                    row[name] = float((await coro()).value)
                except Exception as e:  # noqa: BLE001
                    row[name] = None
                    row.setdefault("errors", {})[name] = repr(e)[:160]
        return row

    rows = await asyncio.gather(*[one(r) for r in chosen])
    out_dir = ROOT / "06_results" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.run}__ragas.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    def mean(key, rs):
        xs = [r[key] for r in rs if r.get(key) is not None]
        return round(sum(xs) / len(xs), 3) if xs else None
    summary = {"run_id": args.run, "ragas_version": "0.4.3", "llm": RAGAS_MODEL, "n": len(rows), "groups": {}}
    for label, rs in (("all", rows), ("provided", [r for r in rows if r["golden"] == "provided"]),
                      ("team", [r for r in rows if r["golden"] == "team"])):
        summary["groups"][label] = {"n": len(rs), **{k: mean(k, rs) for k in ("faithfulness", "factual_correctness", "context_recall")}}
    summary["errors"] = sum(1 for r in rows if r.get("errors"))
    (out_dir / f"{args.run}__ragas.summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--workers", type=int, default=4)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
