"""RAG 파이프라인을 제공 질문 180개에 실행하고 실행 기록과 코드 기반 1차 채점을 저장한다.

  python scripts/run_rag.py                         # 기본 RAG, 180문항
  python scripts/run_rag.py --sets negative --limit 10 --no-save

저장: PostgreSQL rag_runs / rag_case_results, 06_results/rag/<run_id>.jsonl (agent_traces 형식)
1차 채점(코드): 응답 유형이 기대 행동과 맞는가, 인용한 문서가 정답 근거를 포함하는가, 인용 형식이 유효한가.
답변 내용의 정확성·완전성(LLM Judge, Ragas)은 별도 평가에서 한다.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg.types.json import Jsonb

from rag import config, db
from rag.basic_rag import BasicRAG
from rag.multi_agent import MultiAgentRAG
from rag.retrieval import BM25Retriever
from rag.embedding import CachedQueryEmbedder

FILES = {"base": "positive_cases.jsonl", "negative": "negative_cases.jsonl",
         "life": "positive_life_guide_cases.jsonl", "add": "additional_cases.jsonl"}
OUT_DIR = config.ROOT / "06_results" / "rag"


def allowed_types(expected: str) -> list[str]:
    """기대 행동 -> 허용 응답 유형. 첫 번째가 엄격 기준이다."""
    e = expected
    if e.startswith("ignore_injection_and_refuse"):
        return ["refuse", "abstain"]
    if e.startswith("ignore_injection_and_correct"):
        return ["correct", "answer"]
    if e.startswith("ignore_injection"):
        return ["answer", "correct"]
    if e.startswith("answer"):
        return ["answer", "correct"]
    if e.startswith("correct"):
        return ["correct", "answer"]
    if e == "ask_clarifying_question":
        return ["clarify"]
    if e.startswith("abstain_and_request"):
        return ["abstain", "clarify"]
    if e.startswith(("abstain", "require_freshness", "flag_stale")):
        return ["abstain"]
    if e.startswith("refuse"):
        return ["refuse", "abstain"]
    raise ValueError(f"매핑되지 않은 기대 행동: {e}")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def page_ids(item: dict) -> set[str]:
    """파일·쪽 범위 -> 페이지 형식 근거 ID. 골든셋은 용어집·약관 근거도 `{파일명}-pdf-{쪽}`으로 적는다."""
    if "file_name" not in item:
        return set()
    stem = item["file_name"].rsplit("/", 1)[-1].removesuffix(".pdf")
    prefix = config.LIFE_GUIDE_KEY if stem == "financial_life_guide" else stem
    return {f"{prefix}-pdf-{p}" for p in range(item["page_no"], item["page_end"] + 1)}


def check(case: dict, rec: dict) -> dict:
    allowed = allowed_types(case["expected_behavior"])
    gold = set(case.get("expected_source_ids") or [])
    cited = {sid for c in rec["citations"] for sid in c["source_ids"]} | {i for c in rec["citations"] for i in page_ids(c)}
    delivered = ({sid for p in rec["delivered_parents"] for sid in p["source_ids"]}
                 | {i for p in rec["delivered_parents"] for i in page_ids(p)})
    out = {
        "behavior_strict": rec["response_type"] == allowed[0],
        "behavior_lenient": rec["response_type"] in allowed,
        "invalid_citations": len(rec["invalid_citations"]),
    }
    if gold:
        out["context_recall"] = len(gold & delivered) / len(gold)
        out["citation_hit"] = bool(gold & cited)
        out["citation_recall"] = len(gold & cited) / len(gold)
    if case.get("must_include") and case["set"] == "positive":
        out["must_include_rate"] = sum(norm(m) in norm(rec["answer"]) for m in case["must_include"]) / len(case["must_include"])
    return out


def load_cases(sets: list[str], answers_dir: Path = config.ANSWERS_DIR) -> list[dict]:
    cases = []
    for qset in sets:
        for line in (answers_dir / FILES[qset]).read_text(encoding="utf-8").splitlines():
            cases.append({**json.loads(line), "question_set": qset})
    return cases


def summarize(results: list[dict]) -> dict:
    by = defaultdict(list)
    for r in results:
        if r.get("error"):
            continue
        by["all"].append(r)
        by[f"set:{r['case']['question_set']}"].append(r)
        by[f"kind:{r['case']['set']}"].append(r)   # 답할 수 있는 질문(positive) / 없는 질문(negative)
        if r["case"]["question_set"] == "negative":
            by[f"neg:{r['case']['category']}"].append(r)
    summary = {}
    for g, rs in by.items():
        keys = sorted({k for r in rs for k in r["checks"]})
        s = {"n": len(rs)}
        for k in keys:
            vals = [float(r["checks"][k]) for r in rs if k in r["checks"]]
            s[k] = sum(vals) / len(vals)
        s["response_types"] = dict(sorted(defaultdict(int, {}).items()))
        types = defaultdict(int)
        for r in rs:
            types[r["record"]["response_type"]] += 1
        s["response_types"] = dict(types)
        for k in ("model_calls", "search_calls", "input_tokens", "output_tokens", "elapsed_ms"):
            s[f"avg_{k}"] = sum(r["record"]["usage"][k] for r in rs) / len(rs)
        summary[g] = s
    summary["errors"] = sum(1 for r in results if r.get("error"))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", choices=["basic", "multi"], default="basic")
    ap.add_argument("--sets", nargs="+", default=list(FILES))
    ap.add_argument("--cases", nargs="+", help="특정 case_id만 실행")
    ap.add_argument("--answers-dir", type=Path, default=config.ANSWERS_DIR,
                    help="기준 답안 폴더 (골든셋: team_golden_set/03_answers)")
    ap.add_argument("--tag", default="", help="run_id 끝에 붙일 이름 (예: golden)")
    ap.add_argument("--answer-style", choices=["plain", "parts"], default="parts",
                    help="Multi-Agent 답변 방식 (parts: 질문 요소 점검표 후 답변)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    cases = load_cases(args.sets, args.answers_dir)
    if args.cases:
        cases = [c for c in cases if c["case_id"] in set(args.cases)]
    if args.limit:
        cases = cases[: args.limit]
    conn = db.connect()
    db.init_schema(conn)
    embedder = CachedQueryEmbedder()
    for c in cases:  # 질문 임베딩을 먼저 채워 두고(캐시) 스레드에서는 읽기만 한다
        embedder.embed_query(c["question"])

    bm25 = BM25Retriever(conn, config.BASELINE_EXPERIMENT) if args.pipeline == "multi" else None

    def make():
        if args.pipeline == "multi":
            return MultiAgentRAG(db.connect(), embedder, bm25, answer_style=args.answer_style)
        return BasicRAG(db.connect(), embedder)

    def work(case):
        local = make()
        try:
            rec = local.run(case["question"], case["question_set"])
            return {"case": case, "record": rec, "checks": check(case, rec)}
        except Exception as e:  # 한 문항 실패가 전체 실행을 멈추지 않게 기록한다
            return {"case": case, "error": f"{type(e).__name__}: {e}"}

    results = []
    with ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(work, c) for c in cases]
        for i, f in enumerate(as_completed(futures), 1):
            results.append(f.result())
            if i % 20 == 0 or i == len(cases):
                print(f"  {i}/{len(cases)}")
    results.sort(key=lambda r: r["case"]["case_id"])
    summary = summarize(results)
    pipeline = "multi_agent" if args.pipeline == "multi" else "basic_rag"
    params = {**make().params(), "answers_dir": str(args.answers_dir), "cases": len(cases)}

    print(f"\n문항 {len(results)}개, 오류 {summary['errors']}개")
    for r in [r for r in results if r.get("error")][:5]:
        print(f"  [오류] {r['case']['case_id']}: {r['error'][:200]}")
    print(f"{'group':34}{'n':>4}{'유형(엄격)':>10}{'유형(완화)':>10}{'문맥Rec':>9}{'인용Hit':>9}{'인용Rec':>9}{'must':>7}{'토큰':>7}{'ms':>7}")
    for g, s in summary.items():
        if not isinstance(s, dict):
            continue
        f = lambda k: f"{s[k]:.3f}" if k in s else "-"
        print(f"{g:34}{s['n']:>4}{f('behavior_strict'):>10}{f('behavior_lenient'):>10}{f('context_recall'):>9}"
              f"{f('citation_hit'):>9}{f('citation_recall'):>9}{f('must_include_rate'):>7}"
              f"{s['avg_input_tokens'] + s['avg_output_tokens']:>7.0f}{s['avg_elapsed_ms']:>7.0f}")

    if args.no_save:
        return
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}__{pipeline}" + (f"__{args.tag}" if args.tag else "")
    conn.execute("INSERT INTO rag_runs (run_id, pipeline, params, summary) VALUES (%s, %s, %s, %s)",
                 (run_id, pipeline, Jsonb(params), Jsonb(summary)))
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO rag_case_results (run_id, case_id, question_set, question, response_type, answer,
                   record, checks, error) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(run_id, r["case"]["case_id"], r["case"]["question_set"], r["case"]["question"],
              r.get("record", {}).get("response_type"), r.get("record", {}).get("answer"),
              Jsonb(r.get("record", {})), Jsonb(r.get("checks")), r.get("error")) for r in results],
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / f"{run_id}.jsonl", "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps({"run_id": run_id, "case_id": r["case"]["case_id"],
                                 "question_set": r["case"]["question_set"], "question": r["case"]["question"],
                                 **r.get("record", {}), "checks": r.get("checks"), "error": r.get("error")},
                                ensure_ascii=False) + "\n")
    (OUT_DIR / f"{run_id}.summary.json").write_text(
        json.dumps({"run_id": run_id, "params": params, "summary": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\n저장: run_id={run_id}  (PostgreSQL rag_runs/rag_case_results, {OUT_DIR})")


if __name__ == "__main__":
    main()
