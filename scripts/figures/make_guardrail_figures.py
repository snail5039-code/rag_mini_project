"""P3 계열, 안전 문항, 적대적 문항, 저하 모드 결과를 docs/images/eval_07~10_*.png로 만든다. LLM 호출 없음.

실행: PYTHONIOENCODING=utf-8 python scripts/figures/make_guardrail_figures.py
"""
import glob
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
EVAL = ROOT / "06_results" / "eval"
RAG = ROOT / "06_results" / "rag"
OUT = ROOT / "docs" / "images"

import scripts.run_rag as rr  # noqa: E402

C_BASIC, C_MULTI, C_NEW = "#8a9bb0", "#d9822b", "#3f7fb5"
C_GOOD, C_BAD, C_NEUTRAL = "#3f8f5f", "#c4493d", "#b9bdc4"

plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 150, "savefig.bbox": "tight"})


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def save(fig, name):
    fig.savefig(OUT / name)
    plt.close(fig)
    print("saved", name)


def label(ax, bars, fmt="{:.3f}", dy=0.004):
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + dy, fmt.format(b.get_height()), ha="center", va="bottom", fontsize=8)


# ⑦ P3 계열: 정확성은 변동 범위 안, 비용만 감소
def fig7():
    p3a, p3b_ = load(EVAL / "p3_subset150_compare.json"), load(EVAL / "p3_rep_subset150_compare.json")
    p3c = load(EVAL / "p3b_subset150_compare.json")
    st = p3a["groups"]["all"]["stats"]
    panels = [("응답 유형 완화", "behavior_lenient", "{:.3f}"), ("Judge 정확성", "judge_correctness", "{:.3f}"),
              ("평균 토큰 / 문항", "avg_tokens", "{:,.0f}")]
    names = ["기준선\n(3회 평균)", "P3\n(1회)", "P3\n(2회)", "P3-b"]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.4))
    for ax, (title, key, fmt) in zip(axes, panels):
        s = st[key]
        vals = [s["base_mean"], s["new"], p3b_["groups"]["all"]["stats"][key]["new"], p3c["groups"]["all"]["stats"][key]["new"]]
        ax.axhspan(s["base_min"], s["base_max"], color=C_NEUTRAL, alpha=0.45, label="기준선 3회 변동 범위")
        bars = ax.bar(names, vals, color=[C_BASIC, C_MULTI, C_MULTI, C_NEW], width=0.55)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, fmt.format(v), ha="center", va="bottom", fontsize=8)
        lo, hi = min(vals + [s["base_min"]]), max(vals + [s["base_max"]])
        pad = (hi - lo) * 0.6 + 1e-9
        ax.set_ylim(lo - pad, hi + pad)
        ax.set_title(title, fontsize=10)
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    base_t, new_t = st["avg_tokens"]["base_mean"], p3c["groups"]["all"]["stats"]["avg_tokens"]["new"]
    fig.suptitle(f"P3 계열(평가 프롬프트 수정): 정확성은 변동 범위 안, 토큰은 {abs(new_t / base_t - 1) * 100:.1f}% 감소", fontsize=12)
    fig.text(0.01, -0.03, "150문항 부분 집합(어려운 문항 비중 높음, 270문항 점수와 직접 비교 불가). y축은 잘려 있음.", fontsize=8, color="#555")
    save(fig, "eval_07_p3_effect.png")


# ⑧ 안전 문항(되묻기·거절) 통과율
def fig8():
    ids = load(EVAL / "subset_guard.json")["case_ids"]
    tg = {"ADD-RP06", "POS055", "ADD-RP10"}
    guard = [c for c in ids if c not in tg]

    def ld(p):
        return {json.loads(l)["case_id"]: json.loads(l) for l in open(p, encoding="utf-8")}

    base = [ld(glob.glob(str(RAG / f"*{t}__multi_agent__both_golden.jsonl"))[0]) for t in ["120715", "165034", "165515"]]
    p3 = [ld(RAG / "20261022_090412__multi_agent__both_golden.jsonl"), ld(RAG / "20261022_090925__multi_agent__both_golden.jsonl")]
    new = [ld(RAG / f"{r}__multi_agent__both_golden.jsonl") for r in ("20261022_100244", "20261022_100403", "20261022_100518")]
    cases = {c["case_id"]: c for c in rr.load_cases(list(rr.FILES), ["provided", "team"])}

    def ok(r, c):
        return r[c]["response_type"] in rr.allowed_types(cases[c]["expected_behavior"])

    rate = lambda rs, cs: sum(ok(r, c) for r in rs for c in cs) / (len(rs) * len(cs))
    in_p3 = [c for c in guard if c in p3[0]]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4), gridspec_kw={"width_ratios": [1, 1.5]})
    ax = axes[0]
    vals = [rate(base, guard), rate(p3, in_p3), rate(new, guard)]
    bars = ax.bar([f"기준선\n({len(guard)}문항×3회)", f"P3\n({len(in_p3)}문항×2회)", f"P3-b\n({len(guard)}문항×3회)"], vals,
                  color=[C_BASIC, C_MULTI, C_NEW], width=0.55)
    label(ax, bars, dy=0.01)
    ax.set_ylim(0, 1.1)
    ax.set_title("안전 문항(되묻기·거절 등) 완화 통과율", fontsize=10)
    ax = axes[1]
    focus = ["NEG046", "NEG047", "NEG013", "NEG052"]
    x = range(len(focus))
    w = 0.38
    b1 = ax.bar([i - w / 2 for i in x], [sum(ok(r, c) for r in base) / 3 for c in focus], w, color=C_BASIC, label="기준선 (3회)")
    b2 = ax.bar([i + w / 2 for i in x], [sum(ok(r, c) for r in new) / 3 for c in focus], w, color=C_NEW, label="P3-b (3회)")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.02, f"{round(b.get_height() * 3)}/3", ha="center", fontsize=9)
    p3_txt = {c: f"{sum(ok(r, c) for r in p3 if c in r)}/2" for c in focus if c in p3[0]}
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{c}\n(P3: {p3_txt.get(c, '미실행')})" for c in focus], fontsize=9)
    ax.set_ylim(0, 1.2)
    ax.set_ylabel("통과 비율")
    ax.set_title("문항별: 되묻기 퇴보는 복구, NEG052만 미복구", fontsize=10)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    fig.suptitle("P3-b 보강: P3에서 무너진 안전 문항을 기준선 이상으로 회복", fontsize=12)
    fig.text(0.01, -0.03, "NEG052는 평가 판정이 기준선과 같고 답변 단계에서 갈리는, 기준선에서도 흔들리던 문항.", fontsize=8, color="#555")
    save(fig, "eval_08_safety_cases.png")


# ⑨ 적대적 문항
def fig9():
    d = load(EVAL / "gr2_adversarial.json")
    fig, ax = plt.subplots(figsize=(11, 4.6))
    names = list(d["Multi-Agent"]["by_group"].keys())
    short = [n.split(" ", 1)[0] + "\n" + n.split(" ", 1)[1] for n in names]
    x = range(len(names))
    w = 0.38
    for off, key, color in ((-w / 2, "기본 RAG", C_BASIC), (w / 2, "Multi-Agent", C_MULTI)):
        g = d[key]["by_group"]
        vals = [g[n]["lenient"] / g[n]["n"] for n in names]
        bars = ax.bar([i + off for i in x], vals, w, color=color, label=key)
        for b, n in zip(bars, names):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.02, f"{round(b.get_height() * g[n]['n'])}/{g[n]['n']}", ha="center", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(short, fontsize=9)
    ax.set_ylim(0, 1.2)
    ax.set_ylabel("기대 행동 충족(완화) 비율")
    ax.legend(frameon=False, loc="lower right", ncol=2)
    ax.set_title("적대적 문항 36개: 지시 준수 0건, 비밀·개인정보 유출 0건, must_not 위반 0건", fontsize=11)
    fig.text(0.01, -0.07, "C(개인정보)의 낮은 막대는 안전 문제가 아니라 기대 라벨 불일치: 내용상 올바르게 거절했지만 기대 행동이 abstain만 허용해 실패로 집계됨.\n"
             "B(내부 정보)는 완화 기준 6/6이지만 엄격 기준은 2/6: 비밀은 지켰으나 '비공개' 대신 '문서에 정보 없음'으로 답함. 결과를 본 뒤 문항을 고치면 측정이 오염되므로 그대로 둠. 36문항이라 방향성만.",
             fontsize=8, color="#555")
    save(fig, "eval_09_adversarial.png")


# ⑩ 저하 모드
def fig10():
    d = load(EVAL / "g2_degraded_check.json")["rows"]
    order = ["저하 모드(평가 강제 실패)", "기본 RAG", "정상 Multi-Agent(3회 평균)"]
    colors = [C_BAD, C_BASIC, C_MULTI]
    specs = [("응답 유형 완화", "lenient", "{:.2f}"), ("Judge 정확성", "judge", "{:.2f}"), ("평균 토큰 / 문항", "tokens", "{:,.0f}")]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2))
    for ax, (title, key, fmt) in zip(axes, specs):
        vals = [d[n][key] for n in order]
        bars = ax.bar(["저하 모드", "기본 RAG", "정상\nMulti-Agent"], vals, color=colors, width=0.55)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v * 1.01, fmt.format(v), ha="center", va="bottom", fontsize=9)
        ax.set_ylim(0, max(vals) * 1.18)
        ax.set_title(title, fontsize=10)
    fig.suptitle("평가 단계가 고장 나도 응답은 계속: 기본 RAG 수준(비용도 같음)으로 저하", fontsize=12)
    fig.text(0.01, -0.03, "같은 25문항. 저하 모드·기본 RAG의 차이(문항 1개 = 0.04)는 노이즈 범위. 저하 모드에서는 되묻기·거절이 답변 프롬프트에만 의존.", fontsize=8, color="#555")
    save(fig, "eval_10_degraded_mode.png")


if __name__ == "__main__":
    fig7(); fig8(); fig9(); fig10()
