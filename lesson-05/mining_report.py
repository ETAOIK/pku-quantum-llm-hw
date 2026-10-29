"""Render measured factor research as a standalone GitHub report and figures."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mining import HERE, NEW_LABELS, PROTOCOL
from shared import LABELS

ROOT = HERE.parent


def number(value, digits=3):
    return "—" if pd.isna(value) else f"{value:.{digits}f}"


def percent(value, digits=2):
    return "—" if pd.isna(value) else f"{100 * value:.{digits}f}%"


def markdown_table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |",
                      *["| " + " | ".join(str(v) for v in row) + " |" for row in rows]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=HERE / "research-20261029")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/lesson-05")
    args = parser.parse_args()
    results, output = args.results, args.output
    output.mkdir(parents=True, exist_ok=True)
    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    selection = json.loads((results / "selection.json").read_text())["selected"]
    frame = pd.read_csv(results / "factors.csv")
    primary = frame[frame.horizon == 5]
    comparison = pd.read_csv(results / "backtests.csv")
    matrix = pd.read_csv(results / "validation-correlation.csv", index_col="factor")
    coverage = pd.read_csv(results / "correlation-coverage.csv")
    names = PROTOCOL["fixed_baselines"] + selection
    labels = {**LABELS, **NEW_LABELS, "equal_weight": "同条件动态等权"}
    colors = ["#0F4D92", "#3775BA", "#8BCF8B", "#B64342", "#CFCECE"]
    plt.rcParams.update({"font.family": ["Arial", "Helvetica", "DejaVu Sans"], "font.size": 12,
                         "axes.spines.right": False, "axes.spines.top": False, "axes.linewidth": 1.4,
                         "legend.frameon": False, "svg.fonttype": "none", "pdf.fonttype": 42})
    def save(fig, name):
        fig.tight_layout(pad=1.6)
        for suffix in ("png", "svg"):
            fig.savefig(figures / f"{name}.{suffix}", dpi=300, bbox_inches="tight", facecolor="white")
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 5))
    positions = np.arange(len(names))
    for i, (stage, stage_label) in enumerate((("development", "2025 H1: diagnostic"), ("validation", "2025 H2: selection"), ("followup", "2026 Jan-Sep: follow-up"))):
        values = primary[primary.stage == stage].set_index("factor").reindex(names)
        ax.bar(positions + (i - 1) * .24, values.rank_ic_mean, width=.23, color=colors[i], edgecolor="black", linewidth=.5, label=stage_label)
    ax.axhline(0, color="#777777", linewidth=.8)
    ax.set_xticks(positions, names, rotation=20, ha="right")
    ax.set_ylabel("Mean 5-day Rank IC")
    ax.set_title("5-day Rank IC by period: fixed direction", pad=42)
    ax.legend(fontsize=10, ncol=3, loc="lower left", bbox_to_anchor=(0, 1.01))
    save(fig, "factor-stability")

    shown = list(dict.fromkeys([*names, "reversal5_lowvol20", "momentum_20", "low_vol_20", "reversal_10", "range_reversal_20"]))
    values = matrix.loc[shown, shown]
    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(values, vmin=-1, vmax=1, cmap="RdBu_r")
    ax.set_xticks(np.arange(len(shown)), shown, rotation=50, ha="right")
    ax.set_yticks(np.arange(len(shown)), shown)
    for i in range(len(shown)):
        for j in range(len(shown)):
            value = values.iloc[i, j]
            ax.text(j, i, number(value, 2), ha="center", va="center", fontsize=9, color="white" if abs(value) > .65 else "black")
    ax.set_title("2025 H2: mean same-day Spearman correlation")
    fig.colorbar(im, ax=ax, shrink=.7, label="Correlation")
    save(fig, "factor-correlation")

    proxy_rows = []
    for name in names:
        raw = primary[(primary.stage == "followup") & (primary.factor == name)].iloc[0]
        residual = pd.read_csv(results / "proxy-residuals/followup" / name / "summary.csv")
        residual = residual[residual.horizon == 5].iloc[0]
        proxy_rows.append({"factor": name, "raw_rank_ic": raw.rank_ic_mean, "residual_rank_ic": residual.rank_ic_mean,
                           "raw_ci_low": raw.rank_ic_ci_low, "raw_ci_high": raw.rank_ic_ci_high,
                           "residual_coverage": residual.factor_coverage, "residual_ci_low": residual.rank_ic_ci_low,
                           "residual_ci_high": residual.rank_ic_ci_high})
    proxies = pd.DataFrame(proxy_rows)
    proxies.to_csv(results / "proxy-summary.csv", index=False, float_format="%.10g")
    fig, ax = plt.subplots(figsize=(12, 4.7))
    for i, (column, label) in enumerate((("raw_rank_ic", "Original score"), ("residual_rank_ic", "After price / amount / volatility proxies"))):
        prefix = "raw" if i == 0 else "residual"
        intervals = np.vstack([proxies[column] - proxies[f"{prefix}_ci_low"], proxies[f"{prefix}_ci_high"] - proxies[column]])
        ax.bar(positions + (i - .5) * .34, proxies[column], yerr=intervals, capsize=3, width=.32, color=colors[i], edgecolor="black", linewidth=.5, label=label)
        for k, value in enumerate(proxies[column]):
            if pd.isna(value):
                ax.annotate("undefined", (positions[k] + (i - .5) * .34, 0), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=9)
    ax.axhline(0, color="#777777", linewidth=.8)
    ax.set_xticks(positions, names, rotation=20, ha="right")
    ax.set_ylabel("2026 follow-up: mean 5-day Rank IC")
    ax.set_title("Proxy controls: mean Rank IC and approximate 95% HAC intervals", pad=42)
    ax.legend(fontsize=10, ncol=2, loc="lower left", bbox_to_anchor=(0, 1.01))
    save(fig, "proxy-controls")

    plotted = ["equal_weight", "low_amount_20", *selection]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw={"width_ratios": [1.3, 1]})
    for i, name in enumerate(plotted):
        daily = pd.read_csv(results / "backtests/base" / name / "daily.csv")
        axes[0].plot(pd.to_datetime(daily.date), daily.equity / 1e9, linewidth=2, label=name, color=colors[i])
    axes[0].set_ylabel("Net account value / initial CNY 1 billion")
    axes[0].set_title("2026 follow-up: fees, slippage and capacity")
    axes[0].tick_params(axis="x", rotation=25)
    axes[0].legend(fontsize=9)
    for i, scenario in enumerate(("base", "cost_stress")):
        sub = comparison[comparison.scenario == scenario].set_index("factor").reindex(plotted)
        axes[1].bar(np.arange(len(plotted)) + (i - .5) * .34, sub.total_return * 100, width=.32,
                    color=colors[i], edgecolor="black", linewidth=.5, label=scenario)
    axes[1].set_xticks(np.arange(len(plotted)), plotted, rotation=30, ha="right")
    axes[1].set_ylabel("Account return (%)")
    axes[1].set_title("Commission / slippage stress; tax fixed")
    axes[1].legend(fontsize=10)
    axes[1].axhline(0, color="#777777", linewidth=.8)
    save(fig, "net-performance")

    stability = primary.pivot(index="factor", columns="stage", values="rank_ic_mean")
    table_rows = []
    for name in names:
        val = primary[(primary.stage == "validation") & (primary.factor == name)].iloc[0]
        follow = primary[(primary.stage == "followup") & (primary.factor == name)].iloc[0]
        table_rows.append([labels[name], "本轮候选" if name in selection else "固定对照", number(stability.loc[name, "development"]),
                           number(val.rank_ic_mean), number(val.by_q, 4), number(follow.rank_ic_mean), percent(follow.spread_mean)])
    stability_table = markdown_table(["因子", "角色", "2025上半年 IC", "2025下半年 IC", "筛选期 BY q", "2026后续 IC", "2026高−低组毛收益"], table_rows)
    redundancy = []
    existing = primary[primary.family == "existing"].factor.unique().tolist()
    for name in selection:
        closest = matrix.loc[name, existing].abs().idxmax()
        redundancy.append([labels[name], labels[closest], number(matrix.loc[name, closest]),
                           "高度相近，不能称独立新因子" if abs(matrix.loc[name, closest]) >= .9 else "相关度较高，尚不能称独立新因子"])
    redundancy_table = markdown_table(["本轮候选", "最接近的既有因子", "筛选期相关性", "判断"], redundancy)
    proxy_table = markdown_table(["因子", "原 Rank IC", "代理控制后 Rank IC", "残差95%HAC区间", "控制后因子覆盖"],
                                  [[labels[row.factor], number(row.raw_rank_ic), number(row.residual_rank_ic), f"[{number(row.residual_ci_low)}, {number(row.residual_ci_high)}]", percent(row.residual_coverage)] for row in proxies.itertuples()])
    base = comparison[comparison.scenario == "base"].set_index("factor")
    net_table = markdown_table(["组合", "净收益", "相对等权 pp", "最大回撤", "配对年化算术超额95%区间", "期末持仓"],
                               [[labels[name], percent(base.loc[name, "total_return"]), number(base.loc[name, "total_excess_pp"], 2),
                                 percent(base.loc[name, "max_drawdown"]), f"[{percent(base.loc[name, 'excess_ci_low'])}, {percent(base.loc[name, 'excess_ci_high'])}]",
                                 int(base.loc[name, "terminal_positions"])] for name in ["equal_weight", *names]])
    sensitivity_table = markdown_table(["因子", "十亿元净收益", "佣金/滑点加倍", "一百万元净收益", "十亿元成交比例"],
                                       [[labels[name], percent(base.loc[name, "total_return"]),
                                         percent(comparison[(comparison.factor == name) & (comparison.scenario == "cost_stress")].iloc[0].total_return),
                                         percent(comparison[(comparison.factor == name) & (comparison.scenario == "small_cash")].iloc[0].total_return),
                                         percent(base.loc[name, "fill_fraction"])] for name in names])
    formulas = markdown_table(["候选", "公式", "直觉"], [[NEW_LABELS[name], f"`{formula}`", explanation] for (name, formula), explanation in zip(PROTOCOL["new_candidates"].items(), [
        "观察较长反转窗口", "偏好近期日内跌幅大的股票", "用较长日内窗口平滑噪声", "检验隔夜弱势是否回补",
        "近期量能放大时加强反转评分", "等权合并反转与低成交额排名", "合并反转与低平均每笔金额排名", "合并反转与较稳定的低波动排名",
        "中期相对强势但近期回撤", "历史价格区间低位与低成交额组合", "近期成交额相对历史水平收缩", "近期成交笔数相对历史水平收缩"])])
    selected_text = "、".join(labels[name] for name in selection) or "无新增候选通过规则"
    outperform = [name for name in selection if base.loc[name, "total_excess_pp"] > 0]
    ci_pass = [name for name in selection if base.loc[name, "excess_ci_low"] > 0]
    net_conclusion = ("本轮候选中，" + "、".join(labels[name] for name in outperform) + "的账面净收益高于同条件等权。") if outperform else "本轮筛出的新增候选均未在十亿元基准成本下跑赢同条件等权。"
    ci_conclusion = ("近似块自助区间下限为正的候选为：" + "、".join(labels[name] for name in ci_pass) + "；这仍不是独立未来验证。") if ci_pass else "新增候选的配对超额区间没有出现下限为正的证据。"
    content = f'''# 第五次作业：因子分析与有限候选挖掘

更新日期：2026-10-29。范围：课程日线数据、因子评价及同条件扣费回测。**全部属于回顾性研究，未证明可部署 Alpha。**

本报告独立保存在 GitHub 的 `reports/lesson-05/`。交易回测系统保留公式、评价、成交和账本功能，不承载作业报告。Issue 提交由学习者完成。

## 这轮做了什么，得到了什么

对原有 18 个因子和 12 个透明公式候选作同口径分析，共 30 个因子 × 3 段时间 × 3 个收益周期，保存 270 行汇总及完整逐日结果。按预先保存的规则选出：**{selected_text}**。

{net_conclusion}{ci_conclusion}候选是否重复、暴露于什么已知风格、以及 IC 和实际资金收益为何不同，分别在下文检验；不因结果不好而改方向或换候选。

本轮最有用的观察是：5日反转的Rank IC从筛选段约0.052变成后续约−0.001，说明效果会随时期变化；新增组合也与已有信号高度相关。代理控制后，两名候选的IC约为0.013和0.022，区间均包含零，暂不支持“独立新信号”的说法。低成交额对照在100万元/10亿元下约11.99%/1.69%的差异则提示，账户规模和成交约束不能由一个IC数字概括。下一步应固定候选，在新期间及更完整风险/成交数据上检验。

## 数据、时间与筛选方法

- 行情沿用第四课 7 份 Feather，2020-01-02 至 2026-10-16，5,451 证券；只读原 ZIP，使用历史非 ST/交易状态和原历史长度、价格、流动性门禁，不用期末存续名单筛历史。这里只分析 2025–2026，之前的数据作滚动窗口预热。
- 2025-01-02—06-30 作开发诊断；2025-07-01—12-31 作候选筛选；2026-01-01—09-30 只作本轮选择之后的检查。**这些历史此前均可见且已被研究，时间分段不会让它们重新变成独立留出。**
- 主指标事先固定为 5 日 Rank IC；1/20 日作为期限诊断，未用于挑方向。t 收盘评分，t+1 开盘进入，t+1+h 开盘退出；每段内要求退出不超过本段末日，避免跨段标签泄漏。先按当时分数分组，再配对未来收益，缺失标签不补零、不改变组成员。
- 先要求开发段 IC 和分组差为正；筛选段要求 IC/分组差为正、因子覆盖至少80%、标签覆盖至少95%、近似单侧 HAC p 的 BY 校正 q≤0.1。HAC 使用 Bartlett 权重、滞后5日；BY 的检验族为全部30个因子的5日主指标。相关候选排序取筛选段 IC 区间下限，最多两个，彼此绝对相关须小于0.9。没有通过者就不选。
- [方案](../../lesson-05/mining-protocol.json)先于实数据运行保存；[选择记录](../../lesson-05/research-20261029/selection.json)在计算2026指标之前写入。阈值是本项目教学选择，不是老师提供的通用投资标准。正态HAC p的小样本近似、BY和预定规则都不能消除已经看过数据的偏差。

## 1. 稳定性：IC 是否只在一段有效

本报告 IC 表格均指 **Rank IC（Spearman 排序相关）**，不是收益百分比。例如，因子排序与未来收益排序完全相同是 +1，相反是 −1；本系统还另存 Pearson IC。组间收益是最高组减最低组的平均5日**毛收益**，不是累计收益，也不将重叠5日收益复利。

{stability_table}

![不同时间段的因子稳定性](figures/factor-stability.png)

上表只突出固定对照和事先筛出的候选；[全部270行](../../lesson-05/research-20261029/factors.csv)、[全部筛选决定](../../lesson-05/research-20261029/selection-decisions.csv)保留其余候选及负结果。2026 其他因子的表现不用于重新选赢家。

## 2. 重复性：换一个公式是否只是同一个信号

逐日用30个因子均有分数的共同可投股票计算 Spearman，再按日期平均。共同截面平均 {coverage.common_count.mean():.0f} 只，最少 {coverage.common_count.min():.0f} 只；这一完整案例子集只用于相关性诊断，不改其他因子评价的股票池。

{redundancy_table}

![候选及既有因子的相关性](figures/factor-correlation.png)

组合公式是对既有信号的再组合，不声称新的经济机制。“彼此不重复”也不等于“与已有因子不重复”。更完整的[相关矩阵](../../lesson-05/research-20261029/validation-correlation.csv)与[共同截面覆盖](../../lesson-05/research-20261029/correlation-coverage.csv)可核对。

## 3. 风格敏感性：控制已知代理后还剩什么

每个信号日对因子及三个代理分别作1%/99%截面缩尾，以截距、标准化的原始股价对数、20日平均成交额对数和20日收益波动率作OLS，取残差评分。只用同日已知数据，没有用未来收益拟合。缺乏行业/市值，故这**只是有限代理控制，不是行业/市值中性化**。原股价不是市值，成交额也不是换手率。

{proxy_table}

![代理控制前后的 Rank IC](figures/proxy-controls.png)

“—”表示没有足够剩余变化或有效样本，不能将浮点残差噪声当成新信号。低成交额因子本身就是成交额对数的反向，控制它自己的主要解释变量后消失属于预期检查，不是发现错误。残差相关仍为正，也不能证明它独立于遗漏的行业/规模风险。详见[每日代理相关](../../lesson-05/research-20261029/proxy-exposures.csv.gz)与[残差结果](../../lesson-05/research-20261029/proxy-residuals/)；这里未把残差结果再用于选模。

## 4. 把评分交给实际现金账本

每组从2026第一个可用交易日开立新账户，初始10亿元，前50名等权、目标95%仓位、每5个交易日调仓、末20日渐进退出；沿用第四课非ST/成交约束及换股事件。首日可取前一交易日的评分，故成交日范围与上文信号日范围不同。成本为单边佣金1bps、滑点5bps、卖出税5bps，容量为前一日已知20日平均成交额的10%。这些是课程研究假设，不是完整真实费率或开盘成交保证。

同条件动态等权使用相同账户、成本、证券池与执行约束。所有组合均为只做多；分组差未被伪造成可执行做空。

{net_table}

![扣费净值及成本敏感性](figures/net-performance.png)

区间是同日期策略与等权日收益差的20日移动块自助法、1000次、固定种子；表示年化**算术平均日超额**，与累计收益差的单位不同，不是CAGR区间。对照按组合估值核算，期末有持仓时不能称为已全部变现。净收益、超额、回撤、残仓和容量必须一起看，不能用正 IC 替代。

{sensitivity_table}

“成本加倍”只加倍佣金和滑点，卖出税保持5bps；“成交比例”是成交名义额/请求名义额，包含容量、现金和开盘门禁共同影响，不能只归因于容量。小资金收益较高也不能反推十亿元容量已证实。所有场景和逐日账本见[回测结果](../../lesson-05/research-20261029/backtests.csv)与[各组合记录](../../lesson-05/research-20261029/backtests/)。等权基准的重复逐单/逐股快照约90MB，留在本地且不入Git，只公开逐日账本与配置，可用同一脚本重建。其他因子的压缩逐单/持仓随仓库公开。

## 本轮12个新增候选

所有方向和公式在运行前确定，不按2026表现翻转。`rank` 是当日可投池百分位排名；`amount` 是金额、`num_trades` 是笔数，不能当成交股数。新候选是本轮新增的测试表达式，不声称学术首创。

{formulas}

## 复现、检查及下一步

```bash
python3 -m pip install -r lesson-04/requirements.txt
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m pytest -q lesson-04/tests lesson-05/tests
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 lesson-05/mining.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 lesson-05/verify_mining.py
MPLCONFIGDIR=/tmp/lesson05-mpl python3 lesson-05/mining_report.py
```

行情和历史状态准备见[系统说明](../../lesson-05/README.md)，源行情、状态宽表和本机运行缓存不进入Git。完整结果在 `lesson-05/research-20261029/`，图和本报告在 `reports/lesson-05/`；运行校验及输入/代码指纹见[run.json](../../lesson-05/research-20261029/run.json)。本轮停止于这组固定公式，没有根据后续结果继续调参。

下一步应优先补行业、时点市值、完整退市/公司行为和真实成交约束，并在新的独立未来区间验证固定候选；对高相关组合，先与更简单的原因子做同条件比较。当前结果不能作为实盘交易推荐或可部署证明。此前[2026-10-23评价功能记录](evaluation-20261023.md)保留工程来历，本报告不重复堆砌测试清单。

方法参考（2026-10-29查阅）：[Alphalens](https://quantopian.github.io/alphalens/alphalens.html#alphalens.performance.factor_information_coefficient)、[HAC/Bartlett](https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_hac.html)、[BY多重检验](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html)、[Bailey等：回测过拟合](https://www.davidhbailey.com/dhbpapers/overfitting.pdf)。这里是自编透明实现，未调用Alphalens或把上述校正称为独立验证。
'''
    (output / "README.md").write_text(content)
    print(f"Wrote {output / 'README.md'}")


if __name__ == "__main__":
    main()
