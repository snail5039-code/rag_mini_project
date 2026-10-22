"""최종 성과 그림 4종(docs/images/final_*.png). 저장된 결과만 읽는다(LLM 호출 없음).

입력: 06_results/eval/agent_fixes_1022__*.json (scripts/compare_fixes.py),
      06_results/eval/failure_analysis_final.json (scripts/analyze_failures.py)
실행: PYTHONIOENCODING=utf-8 python scripts/make_final_figures.py
"""
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "06_results" / "eval"
OUT = ROOT / "docs" / "images"

# 검증된 범주형 팔레트 앞 3칸(최종=파랑, 개선 전=주황, 기본 RAG=청록). 청록은 대비가 낮아 막대에 값을 직접 적는다.
C_FINAL, C_BEFORE, C_BASIC = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

plt.rcParams.update({
    "font.family": "Malgun Gothic", "axes.unicode_minus": False,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "figure.dpi": 150, "savefig.bbox": "tight", "font.size": 10,
})


def load(name):
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


def stat(d, side, key, g="all"):
    return d[side][g][key]


MULTI, BASIC = load("agent_fixes_1022__multi.json"), load("agent_fixes_1022__basic.json")
STEPS = [("기준선", MULTI, "before_stats"), ("A~D\n구조 수정", MULTI, "after_stats"),
         ("개선 1\n강제 보류 끄기", load("agent_fixes_1022__step1.json"), "after_stats"),
         ("개선 2\n질문 분해 검색", load("agent_fixes_1022__step2.json"), "after_stats"),
         ("개선 3a\n점검표 답변", load("agent_fixes_1022__step3a.json"), "after_stats"),
         ("개선 3b\n답변 모델 교체", load("agent_fixes_1022__step3b.json"), "after_stats"),
         ("개선 4·5\n분해 조건·라벨", load("agent_fixes_1022__step45.json"), "after_stats")]
FINAL = STEPS[-1][1]


def progress():
    """단계별 Judge 정확성·만점 비율 (3회 평균, 세로선은 최소~최대)."""
    fig, ax = plt.subplots(figsize=(9.4, 4.2))
    xs = range(len(STEPS))
    for key, label, color in (("judge_correctness", "Judge 정확성", C_FINAL), ("judge_full", "정확성 만점 비율", C_BEFORE)):
        ss = [stat(d, side, key) for _, d, side in STEPS]
        mean = [s["mean"] for s in ss]
        lo = [s["mean"] - min(s["runs"]) for s in ss]
        hi = [max(s["runs"]) - s["mean"] for s in ss]
        ax.errorbar(xs, mean, yerr=[lo, hi], color=color, lw=2, marker="o", ms=8, capsize=4,
                    mec=SURFACE, mew=2, label=label)
        for x, m, s in zip(xs, mean, ss):   # 값은 최대값 막대 위에 적어 겹치지 않게 한다
            ax.annotate(f"{m:.3f}", (x, max(s["runs"])), textcoords="offset points", xytext=(0, 7),
                        ha="center", fontsize=9, color=INK)
    ax.axvspan(3.5, 5.5, color=C_FINAL, alpha=0.06, lw=0)
    ax.text(4.5, 0.53, "가장 큰 효과", ha="center", fontsize=9, color=INK2)
    ax.text(6, 0.53, "비용 절감", ha="center", fontsize=9, color=INK2)
    ax.set_xticks(list(xs), [s[0] for s in STEPS], fontsize=9)
    ax.set_ylim(0.5, 0.95)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("단계별 답변 정확도 (270문항, 3회 평균)", loc="left", fontsize=12, color=INK)
    fig.savefig(OUT / "final_01_progress.png")
    plt.close(fig)


def compare():
    """기본 RAG / Multi-Agent 개선 전 / 최종의 주요 지표."""
    rows = [("judge_correctness", "Judge 정확성"), ("judge_full", "정확성 만점 비율"),
            ("must_include_coverage", "필수 항목 충족"), ("behavior_lenient", "응답 유형 적합")]
    series = [("기본 RAG", BASIC, "after_stats", C_BASIC), ("Multi-Agent 개선 전", MULTI, "before_stats", C_BEFORE),
              ("Multi-Agent 최종", FINAL, "after_stats", C_FINAL)]
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    h = 0.26
    for i, (name, d, side, color) in enumerate(series):   # 범례와 같은 순서로 위에서부터 쌓는다
        ys = [r + (i - 1) * (h + 0.03) for r in range(len(rows))]
        vals = [stat(d, side, k)["mean"] for k, _ in rows]
        ax.barh(ys, vals, height=h, color=color, label=name)
        for y, v in zip(ys, vals):
            ax.text(v + 0.01, y, f"{v:.3f}", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(range(len(rows)), [r[1] for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, 1.1)
    ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, fontsize=9)
    ax.set_title("최종 성능 비교 (270문항, Multi-Agent는 3회 평균)", loc="left", fontsize=12, color=INK, pad=28)
    fig.savefig(OUT / "final_02_compare.png")
    plt.close(fig)


CAUSES = [("내용 불완전", "답변 실패: 내용 불완전"), ("검색 누락", "검색 실패"),
          ("응답 유형 판단", "Agent 실패"), ("기타", None)]


def failures():
    """실행당 실패 원인 건수 (기준선 3회 평균 vs 최종 3회 평균)."""
    fa = load("failure_analysis_final.json")

    def avg(prefix):
        labs = [k for k in fa if k.startswith(prefix)]
        total = Counter()
        for lab in labs:
            for r in fa[lab]:
                if not r["cause"]:
                    continue
                key = next((n for n, p in CAUSES if p and r["cause"].startswith(p)), "기타")
                total[key] += 1
        return {n: total[n] / len(labs) for n, _ in CAUSES}

    before, after = avg("기준선"), avg("최종")
    fig, ax = plt.subplots(figsize=(8.6, 3.8))
    h = 0.36
    for i, (name, vals, color) in enumerate((("Multi-Agent 개선 전", before, C_BEFORE), ("Multi-Agent 최종", after, C_FINAL))):
        ys = [r + (i - 0.5) * (h + 0.03) for r in range(len(CAUSES))]
        xs = [vals[n] for n, _ in CAUSES]
        ax.barh(ys, xs, height=h, color=color, label=name)
        for y, v in zip(ys, xs):
            ax.text(v + 1, y, f"{v:.0f}", va="center", fontsize=9, color=INK)
    ax.set_yticks(range(len(CAUSES)), [n for n, _ in CAUSES])
    ax.invert_yaxis()
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("실행당 실패 문항 수 (270문항 중)")
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    tb, ta = sum(before.values()), sum(after.values())
    ax.set_title(f"실패 원인 (실패 {tb:.0f}건 → {ta:.0f}건)", loc="left", fontsize=12, color=INK)
    fig.savefig(OUT / "final_03_failures.png")
    plt.close(fig)


def cost():
    """문항당 평균 토큰과 응답 시간 (단위가 달라 두 칸으로 나눔)."""
    series = [("기본 RAG", BASIC, "after_stats", C_BASIC), ("개선 전", MULTI, "before_stats", C_BEFORE),
              ("최종", FINAL, "after_stats", C_FINAL)]
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.2))
    for ax, key, title, fmt in ((axes[0], "avg_tokens", "문항당 평균 토큰", "{:,.0f}"),
                                (axes[1], "avg_seconds", "문항당 평균 응답 시간(초)", "{:.1f}")):
        vals = [stat(d, side, key)["mean"] for _, d, side, _ in series]
        ax.bar(range(3), vals, color=[c for *_, c in series], width=0.6)
        for x, v in enumerate(vals):
            ax.text(x, v * 1.02, fmt.format(v), ha="center", fontsize=9, color=INK)
        ax.set_xticks(range(3), [s[0] for s in series])
        ax.set_yticks([])
        ax.spines["bottom"].set_color(GRID)
        ax.set_title(title, loc="left", fontsize=11, color=INK)
        ax.set_ylim(0, max(vals) * 1.18)
    fig.savefig(OUT / "final_04_cost.png")
    plt.close(fig)


if __name__ == "__main__":
    progress()
    compare()
    failures()
    cost()
    print("저장:", ", ".join(sorted(p.name for p in OUT.glob("final_*.png"))))
