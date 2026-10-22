"""C. 경로(Trajectory) 평가 (Multi-Agent 실행 기록 대상)

C-1 코드 지표: 재검색률, 재검색 효과, 헛된 재검색, 검색 범위 준수, 검색어 중복, 보류·거절 문항의 불필요한 재검색
C-2 AgentEvals: graph_trajectory_strict_match(기대 경로와 노드 순서 일치) +
                create_graph_trajectory_llm_as_judge(경로가 논리적이고 효율적인가, 일부 문항만)

기대 경로 규칙(결과 파일에도 기록한다):
  - 기본: orchestrator → search → evaluate → answer (첫 검색으로 판단 가능)
  - 근거 ID가 3개 이상인 문항(여러 조항·쪽에 걸침)은 재검색 1회까지 허용:
    orchestrator → search → evaluate → feedback → improve → search → evaluate → answer

사용: python scripts/eval_trajectory.py --run <multi_agent run_id> [--llm-judge-n 50]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag import config  # noqa: E402
from scripts.run_rag import load_cases  # noqa: E402

RUN_DIR = config.ROOT / "06_results" / "rag"
OUT_DIR = config.ROOT / "06_results" / "eval"
JUDGE_MODEL = "gemini-3.8-flash"
DEFAULT_PATH = ["orchestrator", "search", "evaluate", "answer"]
RETRY1_PATH = ["orchestrator", "search", "evaluate", "feedback", "improve", "search", "evaluate", "answer"]
NON_ANSWER = ("abstain", "refuse", "ask_clarifying", "require_freshness", "flag_stale", "ignore_injection_and_refuse")


def scope_sizes() -> dict[str, int]:
    """질문 세트별 기대 검색 범위(파일 수). run_rag.py의 SCOPE_GROUPS와 청크 파일에서 계산한다."""
    method = config.BASELINE_EXPERIMENT.split("__")[0]
    files = defaultdict(set)
    for line in (config.CHUNK_DIR / f"{method}.parents.jsonl").read_text(encoding="utf-8").splitlines():
        p = json.loads(line)
        files[p["doc_group"]].add(p["file_name"])
    return {qs: len(set().union(*[files[g] for g in groups])) for qs, groups in config.SCOPE_GROUPS.items()}


def expected_paths(case: dict) -> list[list[str]]:
    n_ids = len(case.get("expected_source_ids") or [])
    return [DEFAULT_PATH, RETRY1_PATH] if n_ids >= 3 else [DEFAULT_PATH]


def code_metrics(rec: dict, case: dict, sizes: dict) -> dict:
    steps = [s for s in rec["trace"] if s["step"] == "search"]
    searched_more = rec["search_rounds"] > 1
    checks = rec["checks"]
    passed = bool(checks.get("behavior_strict")) and checks.get("context_recall", 1.0) == 1.0
    queries = rec["used_queries"]
    return {
        "re_searched": searched_more,
        "re_search_passed": passed if searched_more else None,
        "wasted_re_search": searched_more and (rec["stop_reason"] == "max_rounds" or any(s.get("new_parents", 1) == 0 for s in steps[1:])),
        "max_rounds_stop": rec["stop_reason"] == "max_rounds",
        "scope_ok": rec["scope_files"] == sizes[rec["question_set"]],
        "duplicate_queries": len(queries) != len(set(queries)),
        "unneeded_re_search": searched_more and case["expected_behavior"].startswith(NON_ANSWER),
    }


def graph_trajectory(rec: dict) -> dict:
    """agentevals GraphTrajectory. 단계 이름 뒤에 핵심 정보를 붙여 LLM Judge가 경로의 논리를 볼 수 있게 한다."""
    steps = []
    for s in rec["trace"]:
        extra = ""
        if s["step"] == "search":
            extra = f"(round={s['round']}, retriever={s['retriever']}, new_parents={s['new_parents']})"
        elif s["step"] == "evaluate":
            extra = f"({s['decision']}; missing={s.get('missing')})"
        elif s["step"] == "answer":
            extra = f"(response_type={s['response_type']}, stop={s['stop_reason']})"
        steps.append(s["step"] + extra)
    return {"inputs": [{"question": rec["question"]}], "results": [{"answer": rec["answer"][:600]}], "steps": [steps]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--llm-judge-n", type=int, default=50, help="경로 LLM Judge 대상 문항 수 (재검색 문항 우선)")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    from agentevals.graph_trajectory.strict import graph_trajectory_strict_match

    recs = [json.loads(l) for l in (RUN_DIR / f"{args.run}.jsonl").read_text(encoding="utf-8").splitlines()]
    cases = {(c["golden"], c["case_id"]): c for c in load_cases(["base", "negative", "life", "add"], ["provided", "team"])}
    sizes = scope_sizes()
    rows = []
    for rec in recs:
        case = cases[(rec["golden"], rec["case_id"])]
        names = [s["step"] for s in rec["trace"]]
        refs = expected_paths(case)
        matches = [graph_trajectory_strict_match(
            outputs={"inputs": None, "results": [{}], "steps": [names]},
            reference_outputs={"inputs": None, "results": [{}], "steps": [ref]})["score"] for ref in refs]
        rows.append({"run_id": rec["run_id"], "case_id": rec["case_id"], "golden": rec["golden"], "question_set": rec["question_set"],
                     "expected_behavior": case["expected_behavior"], "path": names, "n_expected_paths": len(refs),
                     "strict_match": bool(any(matches)), **code_metrics(rec, case, sizes)})

    # C-2 LLM Judge: 재검색 문항을 모두 + 나머지에서 무작위(seed 고정)로 채운다
    judge_rows = []
    if args.llm_judge_n:
        from agentevals.graph_trajectory.llm import create_graph_trajectory_llm_as_judge
        from langchain_google_genai import ChatGoogleGenerativeAI
        import os
        from dotenv import load_dotenv
        load_dotenv(config.ROOT / ".env")
        judge = create_graph_trajectory_llm_as_judge(
            judge=ChatGoogleGenerativeAI(model=JUDGE_MODEL, temperature=0, google_api_key=os.getenv("GEMINI_API_KEY")),
            feedback_key="graph_trajectory_accuracy", use_reasoning=True)
        by_id = {(r["golden"], r["case_id"]): r for r in recs}
        multi = [r for r in rows if len(r["path"]) > 4]
        rest = [r for r in rows if len(r["path"]) <= 4]
        random.Random(0).shuffle(rest)
        picked = (multi + rest)[:args.llm_judge_n]
        for r in picked:
            rec = by_id[(r["golden"], r["case_id"])]
            gt = graph_trajectory(rec)
            res = judge(inputs=gt["inputs"], outputs=gt)
            judge_rows.append({"case_id": r["case_id"], "golden": r["golden"], "re_searched": len(r["path"]) > 4,
                               "score": bool(res["score"]), "comment": res.get("comment", "")[:500]})
            r["llm_trajectory_ok"] = bool(res["score"])

    def rate(rs, key):
        xs = [r[key] for r in rs if r.get(key) is not None]
        return round(sum(xs) / len(xs), 3) if xs else None

    summary = {"run_id": args.run, "judge_model": JUDGE_MODEL,
               "expected_path_rule": "기본 4단계, 근거 ID 3개 이상 문항은 재검색 1회 경로도 허용",
               "scope_sizes": sizes, "groups": {}}
    for label, rs in (("all", rows), ("provided", [r for r in rows if r["golden"] == "provided"]),
                      ("team", [r for r in rows if r["golden"] == "team"])):
        summary["groups"][label] = {
            "n": len(rs), "strict_match": rate(rs, "strict_match"), "re_search_rate": rate(rs, "re_searched"),
            "re_search_passed": rate(rs, "re_search_passed"), "wasted_re_search": sum(r["wasted_re_search"] for r in rs),
            "max_rounds_stop": sum(r["max_rounds_stop"] for r in rs), "scope_ok": rate(rs, "scope_ok"),
            "duplicate_queries": sum(r["duplicate_queries"] for r in rs),
            "unneeded_re_search": sum(r["unneeded_re_search"] for r in rs),
            "llm_trajectory_ok": rate(rs, "llm_trajectory_ok"), "llm_judged": sum("llm_trajectory_ok" in r for r in rs)}
    summary["path_counts"] = {" > ".join(k): v for k, v in Counter(tuple(r["path"]) for r in rows).most_common()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.no_save:
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{args.run}__trajectory.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    (OUT_DIR / f"{args.run}__trajectory.summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if judge_rows:
        (OUT_DIR / f"{args.run}__trajectory_llm.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in judge_rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
