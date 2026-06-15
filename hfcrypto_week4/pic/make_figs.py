# -*- coding: utf-8 -*-
"""week4 报告配图：白底、专业、克制。两张图。
Fig1 信号层：单 120 MLP 尾部 edge 完胜 reg / 108。
Fig2 执行层：taker 撞成本墙（waterfall）+ 多日 OOS net 归零。
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

# ---- 中文字体 ----
FONT = "/home/samson/.fonts/NotoSansCJKsc-Regular.otf"
fm.fontManager.addfont(FONT)
_name = fm.FontProperties(fname=FONT).get_name()
plt.rcParams["font.sans-serif"] = [_name]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 11
plt.rcParams["axes.facecolor"] = "white"
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["savefig.facecolor"] = "white"

OUT = os.path.dirname(os.path.abspath(__file__))

C_WIN = "#2a7ab9"   # 主蓝
C_REF = "#9aa7b4"   # 灰（基准）
C_BAD = "#c0392b"   # 红（成本/负）
C_POS = "#2e8b57"   # 绿（正）


def grid(ax):
    ax.grid(True, axis="y", color="#dfe4ea", lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#b0b0b0")


# ============ Fig 1：信号层 —— 单 120 MLP 尾部 edge 完胜 ============
fig, (axA, axB) = plt.subplots(1, 2, figsize=(12.4, 4.9))

# Panel A: top0.5% net edge 逐步复原（68d OOS, 成本 1.001bp/单边）
labelsA = ["reg\n(reg_d11)", "108-MLP\n(砍7坏因子)", "115fix-MLP\n(修复值)", "120-MLP\n(最终上线候选)"]
netA = [0.663, 0.683, 1.052, 1.101]
pnlA = [None, 1.11, 2.54, 2.73]
colsA = [C_REF, C_REF, C_WIN, C_WIN]
x = np.arange(len(labelsA))
bars = axA.bar(x, netA, color=colsA, width=0.62, zorder=3, edgecolor="white")
for i, (b, v, p) in enumerate(zip(bars, netA, pnlA)):
    txt = f"+{v:.3f}"
    if p is not None:
        txt += f"\n(\${p:.2f}/天)"
    axA.text(b.get_x() + b.get_width() / 2, v + 0.025, txt,
             ha="center", va="bottom", fontsize=9.5,
             color="#1b3b56" if colsA[i] == C_WIN else "#5a6570")
axA.set_xticks(x)
axA.set_xticklabels(labelsA, fontsize=9.3)
axA.set_ylabel("top0.5% net edge (bp/笔)")
axA.set_ylim(0, 1.32)
axA.set_title("(A) 修因子 + 单 120 MLP：尾部 edge 复原并超 reg/108", fontsize=11.5, pad=10)
grid(axA)

# Panel B: MLP vs reg 跨 gate（net edge, 68d）
gates = ["top1%", "top0.5%"]
reg_g = [0.400, 0.663]
mlp_g = [0.638, 1.101]
xb = np.arange(len(gates)); w = 0.34
b1 = axB.bar(xb - w/2, reg_g, w, label="reg (reg_d11)", color=C_REF, zorder=3, edgecolor="white")
b2 = axB.bar(xb + w/2, mlp_g, w, label="MLP_120", color=C_WIN, zorder=3, edgecolor="white")
for bars, vals in [(b1, reg_g), (b2, mlp_g)]:
    for b, v in zip(bars, vals):
        axB.text(b.get_x()+b.get_width()/2, v+0.02, f"+{v:.3f}", ha="center", va="bottom", fontsize=9.5,
                 color="#5a6570" if bars is b1 else "#1b3b56")
# 提升标注
for i, (r, m) in enumerate(zip(reg_g, mlp_g)):
    axB.annotate(f"+{(m/r-1)*100:.0f}%", xy=(xb[i]+w/2, m+0.13), ha="center", fontsize=10.5,
                 color=C_POS, fontweight="bold")
axB.set_xticks(xb); axB.set_xticklabels(gates)
axB.set_ylabel("net edge (bp/笔)")
axB.set_ylim(0, 1.34)
axB.set_title("(B) 整体 IC 几乎一样，尾部 MLP 明显占优", fontsize=11.5, pad=10)
axB.legend(frameon=False, fontsize=9.8, loc="upper left")
grid(axB)

fig.suptitle("图 1　信号层：单 120 MLP = SOL 1s taker 最强 alpha（优势集中在真正下单的尾部）",
             fontsize=13, y=1.005, x=0.5, fontweight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.96])
fig.savefig(os.path.join(OUT, "fig1_alpha_tail.png"), dpi=160, bbox_inches="tight")
plt.close(fig)


# ============ Fig 2：执行层 —— taker 撞成本墙 ============
fig, (axA, axB) = plt.subplots(1, 2, figsize=(12.4, 4.9))

# Panel A: 成本墙 waterfall（per-RT，统一到 gate +1.78 口径）
steps = ["gross@mid\n(信号)", "− 穿价\n(spread+edge)", "− 手续费\n(0.5bp/side)", "= net"]
vals = [2.61, -2.20, -1.00, None]
cum = 0.0
bottoms, heights, colors = [], [], []
for i, v in enumerate(vals):
    if v is None:  # net 总计
        net = 2.61 - 2.20 - 1.00
        bottoms.append(0); heights.append(net); colors.append(C_BAD if net < 0 else C_POS)
    elif v >= 0:
        bottoms.append(cum); heights.append(v); colors.append(C_WIN); cum += v
    else:
        bottoms.append(cum + v); heights.append(-v); colors.append(C_BAD); cum += v
xw = np.arange(len(steps))
axA.bar(xw, heights, bottom=bottoms, color=colors, width=0.6, zorder=3, edgecolor="white")
# 数值标注（统一放在每根 bar 顶端上方/底端下方）
ann = ["+2.61", "−2.20", "−1.00", "= −0.59"]
ann_col = ["#1b3b56", C_BAD, C_BAD, C_BAD]
for i, (a, c) in enumerate(zip(ann, ann_col)):
    top = bottoms[i] + heights[i]
    axA.text(xw[i], top + 0.12, a, ha="center", va="bottom",
             fontsize=10.8, fontweight="bold", color=c)
axA.axhline(0, color="#444", lw=1.0, zorder=4)
axA.axhline(1.78, color=C_POS, lw=1.3, ls="--", zorder=2)
axA.text(3.45, 1.80, "gate 理想上界 +1.78", ha="right", va="bottom", fontsize=9, color=C_POS)
axA.set_xticks(xw); axA.set_xticklabels(steps, fontsize=9.3)
axA.set_ylabel("bp / 来回(RT，单腿口径)")
axA.set_ylim(-1.4, 3.0)
axA.set_title("(A) 信号没问题（+2.61>1.78），穿价+费 3.20 把它吃成负", fontsize=11.3, pad=10)
grid(axA)

# Panel B: 多日 OOS net 均值 ± std（24 天，自然触发无硬门）
models = ["单 120 MLP\n(t=0.36)", "reg (reg_d11)\n(t=−0.02)"]
means = [0.180, -0.027]
stds = [2.47, 5.63]
colsB = [C_WIN, C_REF]
xb = np.arange(len(models))
axB.bar(xb, means, yerr=stds, color=colsB, width=0.5, zorder=3, edgecolor="white",
        error_kw=dict(ecolor="#566", elinewidth=1.6, capsize=8, capthick=1.6))
axB.axhline(0, color="#444", lw=1.1, zorder=4)
for i, (m, s) in enumerate(zip(means, stds)):
    axB.text(xb[i], m + s + 0.25, f"均值 {m:+.2f}\n±{s:.2f}", ha="center", va="bottom",
             fontsize=10, color="#1b3b56" if i == 0 else "#5a6570")
axB.set_xticks(xb); axB.set_xticklabels(models, fontsize=9.6)
axB.set_ylabel("逐日 net (bp/名义)，24 天 OOS")
axB.set_ylim(-6.6, 7.2)
axB.set_title("(B) 多日均值统计 = 0：两者都不赚钱，MLP 仅更稳(std 小 2.3×)", fontsize=11.0, pad=10)
grid(axB)
axB.text(0.5, -5.9, "成本墙(穿价1.1+fee0.5≈1.61bp)是 reg/MLP 共同死结 → 只有 maker 能破",
         ha="center", fontsize=9, color=C_BAD, transform=axB.get_xaxis_transform()
         if False else axB.transData)

fig.suptitle("图 2　执行层：taker 撞成本墙——单日正收益全是噪声，多日 OOS 净收益 = 0",
             fontsize=13, y=1.005, fontweight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.96])
fig.savefig(os.path.join(OUT, "fig2_cost_wall.png"), dpi=160, bbox_inches="tight")
plt.close(fig)

print("OK figs written to", OUT)
