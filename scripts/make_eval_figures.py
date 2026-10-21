"""저장된 평가 결과(06_results/)만 읽어 docs/images/eval_*.png 6종을 만든다. LLM 호출 없음.

실행: PYTHONIOENCODING=utf-8 python scripts/make_eval_figures.py
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "06_results"
EVAL = RES / "eval"
OUT = ROOT / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

BASIC = "20261021_115125__basic_rag__both_golden"
MULTI = "20261021_120715__multi_agent__both_golden"

C_BASIC, C_MULTI = "#8a9bb0", "#d9822b"
C_GOOD, C_BAD, C_NEUTRAL = "#3f8f5f", "#c4493d", "#b9bdc4"

plt.rcParams.update({
    "font.family": "Malgun Gothic",
    "axes.unicode_minus": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 150,
    "savefig.bbox": "tight",
})


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def metrics(run_id):
    """실행 한 개의 전체(270) 대표 지표."""
    run = load(RES / "rag" / f"{run_id}.summary.json")["summary"]["all"]
    judge = load(EVAL / f"{run_id}__judge.summary.json")["summary"]["all"]
    ragas_path = EVAL / f"{run_id}__ragas.summary.json"
    return {
        "strict": run["behavior_strict"],
        "lenient": run["behavior_lenient"],
        "context_recall": run["context_recall"],
        "avg_tokens": run["avg_input_tokens"] + run["avg_output_tokens"],
        "avg_ms": run["avg_elapsed_ms"],
        "calls": run["avg_model_calls"],
        "judge_correct": judge["correctness"],
        "judge_full": judge["correct_full"],
        "faith": judge["faithfulness"],
        "must_include": judge["must_include_coverage"],
    }


def save(fig, name):
    path = OUT / name
    fig.savefig(path)
    plt.close(fig)
    print("saved", path.relative_to(ROOT))


def label_bars(ax, bars, fmt="{:.3f}", dy=0.01):
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + dy, fmt.format(b.get_height()),
                ha="center", va="bottom", fontsize=8)


NOTE = "단일 실행 값. 같은 코드 3회 실행의 변동: 엄격 ±0.02, Judge 정확성 ±0.03, 만점 비율 ±0.07"


# ① 기본 RAG vs Multi-Agent
def fig1():
    b, m = metrics(BASIC), metrics(MULTI)
    core = load(EVAL / "rescore_core.json")
    keys = [
        ("응답 유형\n엄격", "strict"),
        ("응답 유형\n완화", "lenient"),
        ("Judge\n정확성", "judge_correct"),
        ("만점 비율\n(원래 기준)", "judge_full"),
        ("충실성", "faith"),
        ("문맥\nRecall", "context_recall"),
    ]
    bv = [b[k] for _, k in keys]
    mv = [m[k] for _, k in keys]
    # 핵심 항목 기준 보정 만점 비율을 네 번째 뒤에 추가
    keys.insert(4, ("만점 비율\n(핵심 기준 보정)", None))
    bv.insert(4, core["기본 RAG"]["all"]["judge_full_adjusted"])
    mv.insert(4, core["Multi-Agent"]["all"]["judge_full_adjusted"])

    fig, ax = plt.subplots(figsize=(11, 4.8))
    x = range(len(keys))
    w = 0.38
    b1 = ax.bar([i - w / 2 for i in x], bv, w, label="기본 RAG", color=C_BASIC)
    b2 = ax.bar([i + w / 2 for i in x], mv, w, label="Multi-Agent", color=C_MULTI)
    label_bars(ax, b1)
    label_bars(ax, b2)
    ax.set_xticks(list(x))
    ax.set_xticklabels([k for k, _ in keys], fontsize=9)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("점수 (270문항)")
    ax.set_title("기본 RAG vs Multi-Agent: 대표 지표")
    ax.legend(frameon=False, loc="upper left", ncol=2)
    fig.text(0.01, -0.03, NOTE + "\n'핵심 기준 보정'은 필수 항목 중 핵심 항목만 충족해도 만점으로 본 추정치(LLM 분류).", fontsize=8, color="#555")
    save(fig, "eval_01_basic_vs_multi.png")


# ② 실패 원인 구성비
def fig2():
    fa = load(EVAL / "failure_analysis.json")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
    palette = ["#c4493d", "#d9822b", "#e0b341", "#6a9fb5", "#8a9bb0", "#9b7fb8", "#7a8a5a"]
    for ax, (name, rows) in zip(axes, fa.items()):
        counts = {}
        for r in rows:
            if r["cause"] is not None:
                counts[r["cause"]] = counts.get(r["cause"], 0) + 1
        items = sorted(counts.items(), key=lambda kv: -kv[1])
        labels = [k for k, _ in items]
        vals = [v for _, v in items]
        ax.pie(vals, colors=palette[: len(vals)], startangle=90, counterclock=False,
               autopct=lambda p: f"{p:.0f}%" if p >= 4 else "", pctdistance=0.78,
               wedgeprops={"width": 0.45, "edgecolor": "white"}, textprops={"fontsize": 9})
        total = sum(vals)
        ax.set_title(f"{name}: 실패 {total}건 / 270문항", fontsize=11)
        ax.legend([f"{l} ({v})" for l, v in items], loc="upper center", bbox_to_anchor=(0.5, 0.02),
                  frameon=False, fontsize=8, ncol=1)
    fig.suptitle("실패 원인 구성비 (failure_analysis.json, 원인이 없는 통과 문항 제외)", fontsize=12)
    save(fig, "eval_02_failure_causes.png")


# ③ 토큰·응답 시간
def fig3():
    b, m = metrics(BASIC), metrics(MULTI)
    specs = [
        ("평균 토큰 / 문항", "avg_tokens", "{:,.0f}"),
        ("평균 응답 시간 (초)", "avg_ms", "{:.1f}"),
        ("평균 모델 호출 수", "calls", "{:.2f}"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(11, 4))
    for ax, (title, k, fmt) in zip(axes, specs):
        scale = 1000 if k == "avg_ms" else 1
        vals = [b[k] / scale, m[k] / scale]
        bars = ax.bar(["기본 RAG", "Multi-Agent"], vals, color=[C_BASIC, C_MULTI], width=0.55)
        label_bars(ax, bars, fmt, dy=max(vals) * 0.015)
        ax.set_title(title, fontsize=10)
        ax.set_ylim(0, max(vals) * 1.18)
    ratio = m["avg_tokens"] / b["avg_tokens"]
    fig.suptitle(f"비용 비교: Multi-Agent는 토큰 약 {ratio:.1f}배 (총 토큰 858,374 → 2,053,492)", fontsize=12)
    save(fig, "eval_03_cost.png")


# ④ 시도별 점수 변화 + 변동 폭
def fig4():
    var = load(EVAL / "variance_baseline.json")["stats"]["all"]
    attempts = [
        ("기준선", load(EVAL / "p2_compare.json")["groups"]["all"]["base"]),
        ("P2", load(EVAL / "p2_compare.json")["groups"]["all"]["new"]),
        ("P2-b", load(EVAL / "p2b_vs_base_compare.json")["groups"]["all"]["new"]),
        ("P2-c", load(EVAL / "p2c_vs_base_compare.json")["groups"]["all"]["new"]),
    ]
    panels = [
        ("응답 유형 엄격", "behavior_strict", "behavior_strict"),
        ("Judge 정확성", "judge_correctness", "judge_correctness"),
        ("만점 비율 (원래 기준)", "judge_correct_full", "judge_full"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.4))
    for ax, (title, ck, vk) in zip(axes, panels):
        v = var[vk]
        ax.axhspan(v["min"], v["max"], color=C_NEUTRAL, alpha=0.45,
                   label="기준선 3회 변동 범위")
        ax.axhline(v["mean"], color="#666", lw=0.8, ls="--")
        vals = [a[ck] for _, a in attempts]
        colors = [C_BASIC] + [C_MULTI] * 3
        bars = ax.bar([n for n, _ in attempts], vals, color=colors, width=0.55)
        label_bars(ax, bars, "{:.3f}", dy=0.003)
        lo = min(min(vals), v["min"]) - 0.04
        hi = max(max(vals), v["max"]) + 0.04
        ax.set_ylim(lo, hi)
        ax.set_title(title, fontsize=10)
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle("수정 시도별 점수 vs 기준선의 실행 간 변동 범위: 변화가 모두 회색 띠 안팎", fontsize=12)
    fig.text(0.01, -0.03, "P1은 62문항 부분 확인이라 여기에 포함하지 않음(부가 항목 충족률 0.103→0.123, 효과 없음). y축은 잘려 있음.",
             fontsize=8, color="#555")
    save(fig, "eval_04_attempts_variance.png")


# ⑤ 만점 비율: 원래 vs 핵심 기준 보정
def fig5():
    core = load(EVAL / "rescore_core.json")
    groups = [("all", "전체 270"), ("provided", "제공 180"), ("team", "팀 90")]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    for ax, (sys_name, color) in zip(axes, [("기본 RAG", C_BASIC), ("Multi-Agent", C_MULTI)]):
        x = range(len(groups))
        w = 0.38
        o = [core[sys_name][g]["judge_full_original"] for g, _ in groups]
        a = [core[sys_name][g]["judge_full_adjusted"] for g, _ in groups]
        b1 = ax.bar([i - w / 2 for i in x], o, w, color=color, alpha=0.55, label="원래 기준")
        b2 = ax.bar([i + w / 2 for i in x], a, w, color=color, label="핵심 항목 기준 보정")
        label_bars(ax, b1)
        label_bars(ax, b2)
        ax.set_xticks(list(x))
        ax.set_xticklabels([n for _, n in groups])
        ax.set_ylim(0, 1.05)
        ax.set_title(sys_name, fontsize=11)
        ax.legend(frameon=False, fontsize=8, loc="upper left")
    axes[0].set_ylabel("정확성 만점 비율")
    fig.suptitle("채점 기준이 엄격해서 낮게 나온 부분: 부가 항목만 놓친 문항을 만점으로 본 보정", fontsize=12)
    fig.text(0.01, -0.03, "보정값은 must_include를 핵심/부가로 나눈 LLM 분류에 기반한 추정치(사람 검토 전).", fontsize=8, color="#555")
    save(fig, "eval_05_full_rate_adjusted.png")


# ⑥ 개선·악화 문항 수
def fig6():
    cmp = [
        ("P2", load(EVAL / "p2_compare.json")),
        ("P2-b", load(EVAL / "p2b_vs_base_compare.json")),
        ("P2-c", load(EVAL / "p2c_vs_base_compare.json")),
    ]
    metrics_ = [("응답 유형 엄격", "strict_gained", "strict_lost"),
                ("응답 유형 완화", "lenient_gained", "lenient_lost"),
                ("Judge 정확성", "judge_up", "judge_down")]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), sharey=True)
    for ax, (title, g, l) in zip(axes, metrics_):
        gains = [len(c["flips"][g]) for _, c in cmp]
        losses = [len(c["flips"][l]) for _, c in cmp]
        names = [n for n, _ in cmp]
        b1 = ax.bar(names, gains, color=C_GOOD, width=0.5, label="좋아진 문항")
        b2 = ax.bar(names, [-x for x in losses], color=C_BAD, width=0.5, label="나빠진 문항")
        for bar, v in zip(b1, gains):
            ax.text(bar.get_x() + bar.get_width() / 2, v + 0.5, str(v), ha="center", fontsize=9)
        for bar, v in zip(b2, losses):
            ax.text(bar.get_x() + bar.get_width() / 2, -v - 0.5, str(v), ha="center", va="top", fontsize=9)
        for i, (gv, lv) in enumerate(zip(gains, losses)):
            ax.text(i, 29, f"순증 {gv - lv:+d}", ha="center", fontsize=9, color="#333")
        ax.axhline(0, color="#444", lw=0.8)
        ax.set_ylim(-32, 33)
        ax.set_title(title, fontsize=10)
    axes[0].legend(frameon=False, fontsize=8, loc="lower left")
    axes[0].set_ylabel("기준선 대비 문항 수")
    fig.suptitle("기준선 대비 좋아진/나빠진 문항: 얻은 만큼 잃어서 순증이 작다", fontsize=12)
    fig.text(0.01, -0.03, "엄격 지표에는 answer↔correct 라벨만 바뀐 문항(기준선 반복에서도 28개)이 섞여 있음.", fontsize=8, color="#555")
    save(fig, "eval_06_case_flips.png")


if __name__ == "__main__":
    fig1(); fig2(); fig3(); fig4(); fig5(); fig6()
