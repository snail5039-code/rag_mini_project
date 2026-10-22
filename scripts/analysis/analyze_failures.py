"""3번: 실행 기록 + Judge + 경로 평가를 합쳐 문항별 실패 원인을 분류한다.

분류는 기획서의 실패 유형(추출·청킹·검색·답변·인용·Agent)에 맞춘다. 규칙은 위에서부터 처음 걸리는 하나를 주원인으로 정한다.
(문항에 여러 문제가 있어도 주원인은 하나, 플래그는 모두 남긴다.)

    python scripts/analysis/analyze_failures.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from rag import config  # noqa: E402
from scripts.common import jl  # noqa: E402
from scripts.run_rag import PARENT_PAGES, load_cases, page_ids  # noqa: E402

RUNS = {"기본 RAG": "20261021_115125__basic_rag__both_golden", "Multi-Agent": "20261021_120715__multi_agent__both_golden"}
OUT = config.ROOT / "06_results" / "eval"
ANSWER_PREFIX = ("answer", "correct", "ignore_injection_and_answer", "ignore_injection_and_correct")
# 알려진 추출 오류 후보 (README 1장): (파일 stem, 쪽)
EXTRACTION_SUSPECT = {("housing_policy_finance_2025", 21), ("retirement_pension_2025", 23), ("retirement_pension_2025", 17)}


def ids_of_parent(p):
    ids = set(p.get("source_ids", []))
    if p["parent_id"] in PARENT_PAGES:
        ids |= page_ids(*PARENT_PAGES[p["parent_id"]])
    return ids


def classify(rec, case, judge, traj):
    expected = case["expected_behavior"]
    answerable = expected.startswith(ANSWER_PREFIX)
    gold = set(case.get("expected_source_ids") or [])
    chk = rec["checks"]
    flags = []
    child_ids = set().union(*[ids_of_parent(c) for c in rec["retrieved_children"]]) if rec["retrieved_children"] else set()
    child_recall = len(gold & child_ids) / len(gold) if gold else None
    parent_recall = chk.get("context_recall")
    extraction = any((s.rsplit("-pdf-", 1)[0], int(s.rsplit("-pdf-", 1)[1])) in EXTRACTION_SUSPECT
                     for s in gold if "-pdf-" in s)
    judge_bad = (judge["correctness"] < 2 or judge["must_not_violation"] or judge["faithfulness"] < 2
                 or judge["citation_support"] < 2 or not judge["behavior_appropriate"])
    if not chk["behavior_lenient"]:
        flags.append("응답 유형 오류")
    elif not chk["behavior_strict"]:
        flags.append("응답 유형 경계(허용 유형)")
    if answerable and gold:
        if child_recall < 1:
            flags.append("child 단계 근거 누락")
        if child_recall == 1 and parent_recall < 1:
            flags.append("parent 단계 근거 잘림")
        if parent_recall == 1 and not chk.get("citation_hit"):
            flags.append("인용 누락")
    if judge["correctness"] < 2:
        flags.append("답변 불완전·부정확")
    if judge["must_not_violation"]:
        flags.append("must_not 위반")
    if judge["faithfulness"] < 2:
        flags.append("근거 없는 내용")
    if judge["citation_support"] < 2:
        flags.append("인용이 문장을 뒷받침 못함")
    if traj:
        if traj["wasted_re_search"]:
            flags.append("헛된 재검색")
        if traj["unneeded_re_search"]:
            flags.append("보류·거절 문항 불필요 재검색")
        if not traj["strict_match"]:
            flags.append("경로 불일치")

    # 주원인 (기획서 실패 유형)
    cause = None
    if "응답 유형 오류" in flags:
        cause = "Agent 실패: 응답 유형 판단"
    elif extraction and (child_recall or 0) < 1 and answerable:
        cause = "추출 실패"
    elif "child 단계 근거 누락" in flags:
        cause = "검색 실패: 근거를 child 단계에서 못 찾음"
    elif "parent 단계 근거 잘림" in flags:
        cause = "검색 실패: max_parents로 문맥 잘림"
    elif "인용 누락" in flags:
        cause = "인용 실패"
    elif judge_bad:
        cause = "답변 실패: " + ("내용 불완전·부정확" if judge["correctness"] < 2 else
                              "근거 없는 내용" if judge["faithfulness"] < 2 else
                              "인용 지지 부족" if judge["citation_support"] < 2 else "금지 내용·행동 부적절")
    return cause, flags, {"child_recall": child_recall, "parent_recall": parent_recall, "answerable": answerable}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", help="라벨=run_id 형식. 생략하면 기준선 두 실행")
    ap.add_argument("--out", default="failure_analysis.json")
    args = ap.parse_args()
    runs = dict(a.split("=", 1) for a in args.runs) if args.runs else RUNS
    cases = {(c["golden"], c["case_id"]): c for c in load_cases(["base", "negative", "life", "add"], ["provided", "team"])}
    result = {}
    for label, run in runs.items():
        recs = jl(OUT.parent / "rag" / f"{run}.jsonl")
        judge = {(j["golden"], j["case_id"]): j for j in jl(OUT / f"{run}__judge.jsonl")}
        traj = {}
        tp = OUT / f"{run}__trajectory.jsonl"
        if tp.exists():
            traj = {(t["golden"], t["case_id"]): t for t in jl(tp)}
        rows = []
        for rec in recs:
            k = (rec["golden"], rec["case_id"])
            cause, flags, info = classify(rec, cases[k], judge[k], traj.get(k))
            rows.append({"case_id": rec["case_id"], "golden": rec["golden"], "question_set": rec["question_set"],
                         "category": cases[k]["category"], "expected_behavior": cases[k]["expected_behavior"],
                         "response_type": rec["response_type"], "cause": cause, "flags": flags, **info,
                         "correctness": judge[k]["correctness"], "must_include_coverage": judge[k]["must_include_coverage"],
                         "tokens": rec["usage"]["input_tokens"] + rec["usage"]["output_tokens"],
                         "elapsed_ms": rec["usage"]["elapsed_ms"], "model_calls": rec["usage"]["model_calls"]})
        result[label] = rows
    (OUT / args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    for label, rows in result.items():
        print(f"\n===== {label}: 실패 {sum(1 for r in rows if r['cause'])}/{len(rows)}")
        for g in ("provided", "team"):
            rs = [r for r in rows if r["golden"] == g]
            c = Counter(r["cause"] for r in rs if r["cause"])
            print(f"  [{g}] 실패 {sum(c.values())}/{len(rs)}: " + "; ".join(f"{k} {v}" for k, v in c.most_common()))
        fc = Counter(f for r in rows for f in r["flags"])
        print("  플래그: " + "; ".join(f"{k} {v}" for k, v in fc.most_common()))


if __name__ == "__main__":
    main()
