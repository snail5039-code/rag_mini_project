"""tag로 실행 기록과 Judge 결과를 모아 비교표를 출력한다.

  python scripts/compare_runs.py v4_parts v4_parts_rep2 v5_guide v5_guide_rep2
"""
import glob
import json
import os
import sys

D = os.path.join(os.path.dirname(__file__), "..", "06_results")


def latest(tag: str) -> str:
    paths = glob.glob(f"{D}/rag/*__{tag}.jsonl") or glob.glob(f"{D}/rag/*{tag}.jsonl")
    return sorted(os.path.basename(p)[:-6] for p in paths)[-1]


def main() -> None:
    print(f"{'tag':16}{'정확성':>7}{'완전':>7}{'필수':>7}{'충실':>7}{'인용':>7}{'금지':>7}{'답가능':>7}{'답불가':>7}"
          f"{'base':>7}{'life':>7}{'add':>7}{'유형':>7}{'무오류':>7}{'호출':>6}{'토큰':>7}{'초':>6}")
    for tag in sys.argv[1:]:
        r = latest(tag)
        s = json.load(open(f"{D}/eval/{r}__judge.summary.json"))["summary"]
        a = s["all"]
        q = {k.split(":")[-1]: v["correctness"] for k, v in s.items() if "qset" in k}
        rows = [json.loads(l) for l in open(f"{D}/rag/{r}.jsonl")]
        judged = [json.loads(l) for l in open(f"{D}/eval/{r}__judge.jsonl")]
        # 치명적 오류 없음: Judge 정확성 1점 이상이고 금지 내용 위반이 없는 비율 (보조 지표)
        no_critical = sum(j["correctness"] >= 1 and not j["must_not_violation"] for j in judged) / len(judged)
        avg = lambda f: sum(f(x) for x in rows) / len(rows)
        print(f"{tag:16}{a['correctness']:7.3f}{a['correct_full']:7.3f}{a['must_include_coverage']:7.3f}"
              f"{a['faithfulness']:7.3f}{a['citation_support']:7.3f}{a['must_not_violation_rate']:7.3f}"
              f"{s['provided:set:positive']['correctness']:7.3f}{s['provided:set:negative']['correctness']:7.3f}"
              f"{q.get('base', 0):7.3f}{q.get('life', 0):7.3f}{q.get('add', 0):7.3f}"
              f"{avg(lambda x: x['checks']['behavior_lenient']):7.3f}{no_critical:7.3f}{avg(lambda x: x['usage']['model_calls']):6.1f}"
              f"{avg(lambda x: x['usage']['input_tokens'] + x['usage']['output_tokens']):7.0f}"
              f"{avg(lambda x: x['usage']['elapsed_ms']) / 1000:6.1f}")


if __name__ == "__main__":
    main()
