"""G2 저하 모드 실제 확인: 평가 단계를 강제로 실패시켜 현재 문맥으로 바로 답변하는 경로를 25문항에서 돌린다.

    python scripts/analysis/run_degraded_check.py [--n 25] [--seed 7]
저장은 run_rag.py와 같은 형식이다. 이어서 eval_judge.py로 채점하고 compare_degraded.py로 비교한다.
degraded 응답은 run_rag.check에서 실패로 집계되므로, 점수 비교는 compare_degraded.py가 응답 유형으로 다시 계산한다.
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from rag import multi_agent  # noqa: E402
import scripts.run_rag as rr  # noqa: E402

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    ids = json.loads((rr.config.ROOT / "06_results" / "eval" / "subset150.json").read_text(encoding="utf-8"))["case_ids"]
    picked = sorted(random.Random(args.seed).sample(sorted(ids), args.n))
    print("문항:", " ".join(picked))

    orig = multi_agent.generate_structured


    def failing_evaluate(system, user, schema, *a, **k):
        if schema is multi_agent.Evaluation:
            raise ValueError("injected evaluate failure")
        return orig(system, user, schema, *a, **k)


    multi_agent.generate_structured = failing_evaluate
    sys.argv = ["run_rag.py", "--pipeline", "multi", "--golden", "both", "--workers", "16", "--cases", *picked]
    rr.main()


if __name__ == "__main__":
    main()
