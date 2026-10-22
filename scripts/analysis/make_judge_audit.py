"""Judge 검증용 점검표: 한 실행에서 Judge 정확성이 2점이 아닌 문항을 사람이 다시 확인할 수 있게 Markdown으로 만든다.

Judge가 지나치게 엄격했는지(맞는 답을 감점했는지)를 사람이 판정하기 위한 자료다. 시스템 튜닝에 쓰지 않는다.
'검토 포인트'는 감점 사유 문구를 기준으로 자동으로 붙인 분류일 뿐 판정이 아니다.

  python scripts/analysis/make_judge_audit.py --run <run_id> --answers-dir <기준 답안 폴더> --out docs/judge_audit.md
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from rag import config
from scripts.run_rag import load_cases

D = config.ROOT / "06_results"
SOFT_WORDS = ("구별", "구분", "일반화", "확인", "안내", "권고", "주의", "유의", "단정하지")


def hint(unmet: list[str]) -> str:
    if not unmet:
        return "필수 항목은 모두 충족 → 다른 사유로 감점"
    soft = [u for u in unmet if any(w in u for w in SOFT_WORDS)]
    if len(soft) == len(unmet):
        return "미충족 항목이 모두 주의·구별·안내 성격 → 엄격 채점 가능성 확인"
    return "사실·수치 항목 누락 포함 → 실제 누락 가능성 높음"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    cases = {c["case_id"]: c for c in load_cases(["base", "negative", "life", "add"], ["provided", "team"])}
    recs = {json.loads(l)["case_id"]: json.loads(l) for l in (D / "rag" / f"{args.run}.jsonl").read_text().splitlines()}
    judged = [json.loads(l) for l in (D / "eval" / f"{args.run}__judge.jsonl").read_text().splitlines()]
    rows = sorted([j for j in judged if j["correctness"] < 2], key=lambda j: (j["correctness"], j["case_id"]))

    out = [f"# Judge 검증 점검표 — `{args.run}`", "",
           f"Judge 정확성이 2점이 아닌 {len(rows)}문항입니다. 각 문항에서 **Judge 판정이 타당한지**를 사람이 표시합니다.",
           "", "- ☐ 타당: 답변이 실제로 요소를 빠뜨렸거나 틀렸다",
           "- ☐ 과함: 답변이 의미상 충족했는데 감점했다 (루브릭·must_include 수정 후보)",
           "- ☐ 기준 답안 문제: must_include가 질문과 무관하거나 과하게 세세하다", "",
           "'검토 포인트'는 감점 사유를 보고 자동으로 붙인 분류이며 판정이 아닙니다.", ""]
    summary = {}
    for j in rows:
        h = hint([i["item"] for i in j["must_include_items"] if not i["met"]])
        summary[h] = summary.get(h, 0) + 1
    out += ["| 검토 포인트 | 문항 수 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in summary.items()] + [""]
    for j in rows:
        c, r = cases[j["case_id"]], recs[j["case_id"]]
        unmet = [i["item"] for i in j["must_include_items"] if not i["met"]]
        out += [f"## {j['case_id']} — {j['correctness']}점 · 기대 `{c['expected_behavior']}` · 응답 `{j['response_type']}`"
                + (" · 금지 위반" if j["must_not_violation"] else ""), "",
                f"**질문** {c['question']}", "",
                f"**기준 답안** {c['reference_answer']}", "",
                f"**미충족 must_include** {unmet or '없음'}", "",
                f"**시스템 답변** {r['answer'].strip()}", "",
                f"**Judge 사유** {j['reason']}", "",
                f"**검토 포인트** {hint(unmet)}", "",
                "**판정** ☐ 타당 ☐ 과함 ☐ 기준 답안 문제 — 메모:", ""]
    args.out.write_text("\n".join(out), encoding="utf-8")
    print(f"{len(rows)}문항 → {args.out}", summary)


if __name__ == "__main__":
    main()
