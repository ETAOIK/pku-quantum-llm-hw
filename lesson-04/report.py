"""Chinese report and portable figures, generated from saved accounting results."""
import base64
import html

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def write_report(root, config, audit, comparison, curves, summary, checks, coverage):
    figures = root / "figures"
    figures.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": ["Arial", "Helvetica", "DejaVu Sans"], "font.size": 12,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "legend.frameon": False, "svg.fonttype": "none"})

    def save(fig, name):
        fig.tight_layout(pad=2)
        for ext in ("png", "svg", "pdf"):
            fig.savefig(figures / f"{name}.{ext}", dpi=300)
        plt.close(fig)

    names = {"selected": summary["selected"], "equal_weight": "Eligible-universe equal weight",
             "liquid_50": "50 most liquid stocks"}
    colors = ["#0F4D92", "#767676", "#42949E"]
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    for (key, label), color in zip(names.items(), colors):
        curve = curves[key]
        nav = curve.equity / config["initial_cash"]
        peak = np.maximum.accumulate(np.r_[1., nav])[1:]
        axes[0].plot(curve.index, nav, label=label, color=color, lw=1.8)
        axes[1].plot(curve.index, (nav / peak - 1) * 100, color=color, lw=1.4)
        axes[2].plot(curve.index, curve.exposure * 100, color=color, lw=1.2)
    axes[0].set(title="Frozen final test | net of costs | synthetic adjusted units", ylabel="NAV (initial = 1)")
    axes[0].legend(fontsize=10)
    axes[1].set_ylabel("Drawdown (%)")
    axes[2].set_ylabel("Exposure (%)")
    axes[2].set_ylim(0, 105)
    save(fig, "final-test")
    val = comparison[comparison.stage == "validation"].sort_values("sharpe")
    fig, ax = plt.subplots(figsize=(11, 8))
    ax.barh(val.candidate, val.sharpe, color=["#0F4D92" if x == summary["selected"] else "#CFCECE" for x in val.candidate], edgecolor="#4D4D4D", linewidth=.5)
    ax.axvline(0, color="#4D4D4D", lw=.8)
    ax.set(title="18 frozen candidates | validation 2023-2024 only", xlabel="Net Sharpe (risk-free = 0)")
    save(fig, "validation-candidates")
    keys = ["selected_zero_cost", "selected", "selected_stress", "equal_weight", "equal_weight_stress"]
    labels = ["Selected: zero cost", "Selected: base", "Selected: 2x costs", "Equal weight: base", "Equal weight: 2x costs"]
    fig, ax = plt.subplots(figsize=(11, 5))
    values = [summary["metrics"][k]["total_return"] * 100 for k in keys]
    bars = ax.barh(labels, values, color=["#AADCA9", "#0F4D92", "#B64342", "#767676", "#CFCECE"])
    for bar, value in zip(bars, values):
        ax.text(value, bar.get_y() + bar.get_height() / 2, f" {value:.1f}%", va="center", ha="left" if value >= 0 else "right")
    ax.axvline(0, color="#4D4D4D", lw=.8)
    ax.margins(x=.2)
    ax.set(title="Final-test cost sensitivity | no parameter reselection", xlabel="Total return (%)")
    save(fig, "cost-sensitivity")
    fig, ax = plt.subplots(figsize=(11, 4))
    for key, label, color in [("close_nonmissing", "Close", "#0F4D92"), ("num_trades_nonmissing", "Trade count", "#B64342"), ("positive_amount", "Positive amount", "#767676")]:
        ax.plot(coverage.index, coverage[key], label=label, color=color, lw=1.3)
    ax.set(title="Source coverage by date | no end-date universe filtering", ylabel="Securities")
    ax.legend()
    save(fig, "data-coverage")
    selected = summary["metrics"]["selected"]
    baseline = summary["metrics"]["equal_weight"]
    ci = summary["bootstrap"]["ci_95"]
    verdict = "满足预设统计门槛（受数据和成交假设限制）" if summary["statistical_gate_passed"] else "未通过预设策略验证门槛"
    rows = []
    for key in keys + ["liquid_50"]:
        m = summary["metrics"][key]
        rows.append(f"| {key} | {m['total_return']:.2%} | {m['cagr']:.2%} | {m['sharpe']:.2f} | {m['max_drawdown']:.2%} | {m['annual_one_way_turnover']:.1f} |")
    table = "| 测试方案 | 总收益 | 年化收益 | 夏普 | 最大回撤 | 年化单边换手 |\n| --- | ---: | ---: | ---: | ---: | ---: |\n" + "\n".join(rows)
    content = f"""# 第四节课：回测系统与策略验证实测报告

更新日期：2026-10-16。状态：本地实现、全量运行与工程检查完成；教师验收待确认。来源：[原始数据审计](results/data_audit.json)、[冻结方案](protocol.json)、[选择记录](results/selection.json)、[完整汇总](results/summary.json)。

## 结果

**{verdict}。** 验证期按扣费夏普选中 `{summary['selected']}`，最终测试为 2025-01-01 至 {audit['last_date']}，共 {selected['days']} 个交易日。测试扣费总收益 {selected['total_return']:.2%}，年化 {selected['cagr']:.2%}，夏普 {selected['sharpe']:.2f}，最大回撤 {selected['max_drawdown']:.2%}。同期可投股票池等权基准总收益 {baseline['total_return']:.2%}，两者总收益差 {selected['benchmark_excess_total_return']:.2%}（百分点差，非相对收益率）。2026 是截至数据末日的部分年度。

{table}

策略与等权基准的逐日净收益配对差，20 日循环块自助法 2,000 次，年化算术平均超额的 95% 区间为 [{ci[0]:.2%}, {ci[1]:.2%}]。这不是年化复合超额，也不是 18 个候选的多重检验校正；候选只用 2023–2024 选择，最终测试未用于改方向、参数或赢家。区间仍依赖平稳性假设，未调整股票行业、市值或风格暴露。

![最终测试净值、回撤与仓位](figures/final-test.png)

## 数据与发现

- 原文件只读，{audit['rows']} 个日期 × {audit['securities']} 个代码，{audit['first_date']} 至 {audit['last_date']}；7 个真实成员分别留 SHA-256。macOS 元数据排除。
- 最新日期成交笔数非空数为 {audit['fields']['num_trades']['last_date_nonmissing']}；`num_trades` 表示笔数的解释来自文件名，不能当作股数。相关特征不前填。
- 有 {audit['present_before_2025_absent_since_2025']} 个代码在 2025 年前出现而之后完全缺失，采用当时可观察历史和流动性过滤，没有要求股票活到末日。供应商的初始证券覆盖和退市样本完整性仍未知。
- `raw * cumadj` 后绝对单日收益超过 40% 的单元从 {audit['raw_abs_return_above_40pct']} 减到 {audit['adjusted_abs_return_above_40pct']}，支持累计复权因子的暂定解释；仍有极端值，未凭收益删点或截断。供应商定义、修订时点和权益分派未独立核实。

![数据覆盖](figures/data-coverage.png)

## 策略挖掘与验证

固定 18 个候选（公式见 [代码与说明](README.md)）。每 5 个交易日选前 50 个，等权目标 95%，其余现金。过去至少 120 个有效观察、最近 20 日连续可观察、收盘价至少 2 元、20 日平均成交额至少 2,000 万元。成交额单位暂按人民币元解释。全部筛选只用前一日或更早数据。

2020–2022 为开发诊断，2023–2024 选唯一候选，2025 起测试所选候选、等权与高流动性 50 股票基准。所有开发和验证结果保存在 [候选表](results/candidates.csv) 和 [逐日收益](results/candidate_daily_returns.csv)。最终测试没有计算或排序其余候选；零成本和双倍成本是事先固定的敏感性检查。

![验证期全部候选](figures/validation-candidates.png)

![成本敏感性](figures/cost-sensitivity.png)

门槛逐项：[汇总 JSON](results/summary.json) 中的 `gate_conditions`。工程完整性 {len(checks)-1} 项通过，与策略有效性分开判断；工程测试另见 [单元测试](tests/test_backtest.py)。通过某个统计门槛也不能称为可部署或稳定盈利。

## 账本与成交假设

信号 t 收盘后形成，t+1 开盘以目标比例模拟；每个开盘先卖隔夜份额再买入，现金不可负、不可做空，无同日买后卖。使用连续复权份额，允许小数。初始 100 万元；每边佣金假设 3 bps、滑点假设 5 bps；卖出印花税在 2023-08-28 前按 10 bps，之后按 5 bps 建模。未含最低佣金、过户及其他规费、分红税。双倍成本同时放大上述费率和滑点。

每单名义额上限为前 20 日平均成交额的 1%，不把当日全日成交额用于容量。日线成交额为零的旧价 bar 视为无真实开盘成交，以当日全日金额是否为零作为事后停牌/不可成交代理。该代理有当日信息边界，无法证明开盘集合竞价能成交；正的日成交额也不能证明开盘有足够深度。开盘价观察后按同一开盘成交是日线近似，没有撮合延迟。

复权开盘跳空 ≥4.8% 时不买、≤−4.8% 时不卖，是固定保守风控代理，并非历史涨跌停规则；未读取当日最高/最低来挑选开盘成交。因缺历史 ST、板块与涨跌停价，不能严格复现限价可成交性。未成交量不消失，在订单日志保留，下次计划调仓才重新计算；初始资金不足时买单按比例缩减。

持仓缺价先用最后已见价格；连续 20 个交易日无有效观测则估值归零，份额留在账上，复牌可恢复估值，不虚构卖出或现金。这个保守压力假设会误伤长期停牌，既非真实退市回收也非分红明细。期末按市值估值，没有强行卖出，未计期末清仓成本。

`cumadj` 只支持暂定的总回报研究份额，无法分解实际送股、现金分红、配股成本和再投资；本系统不声称复原真实原始股数、整手限制或券商交割单。还缺证券名称、历史状态、行业、市值、基准指数及供应商证明；下一步应补齐这些元数据与开盘成交数据，再作独立后续期间复测，不据本次测试调参后重复称为独立测试。

## 官方规则核查（2026-10-16）

核查到 [深交所 2026 年交易规则](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf) 第 3.1.4–3.1.5 条的交收前卖出及回转限制，第 3.3.8 条的买入申报单位；[上交所现行规则发布页](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml) 载明 2026-07-06 生效。这里只用于确认研究原型的缺口，没有把 2026 规则套用于整个历史。税率切换参考 [税务总局证券交易印花税减半说明](https://shanghai.chinatax.gov.cn/tax/zcfw/rdwd/202309/t468612.html) 与 [税务总局历史单边征收说明](https://www.chinatax.gov.cn/chinatax/n810219/n810780/c5211220/content.html)；佣金和滑点是研究假设。

## 复现与证据

运行入口、安装和公式见 [README](README.md)。[完整性核对](results/integrity_checks.json)、[运行环境与代码哈希](results/run_manifest.json)、[选中策略逐单记录](results/test_selected_orders.csv)、[持仓](results/test_selected_holdings.csv)、[逐日现金与净值](results/test_selected_daily.csv)、[分年度收益](results/test_yearly_returns.csv)。原数据不复制入仓库、不推送外部服务。
"""
    (root / "REPORT.md").write_text(content)
    # Self-contained HTML for local review; raw evidence stays in adjacent CSV/JSON.
    metric_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{m['total_return']:.2%}</td><td>{m['cagr']:.2%}</td><td>{m['sharpe']:.2f}</td><td>{m['max_drawdown']:.2%}</td></tr>" for k, m in summary["metrics"].items())
    images = "".join(f'<figure><img alt="{name}" src="data:image/png;base64,{base64.b64encode((figures / (name + ".png")).read_bytes()).decode()}"></figure>' for name in ("final-test", "validation-candidates", "cost-sensitivity", "data-coverage"))
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>第四节课 · 回测与策略验证</title>
<style>body{{max-width:1150px;margin:40px auto;padding:0 24px;color:#172738;background:#f5f7fa;font:16px/1.7 -apple-system,BlinkMacSystemFont,sans-serif}}h1{{font-size:32px}}.card,figure{{background:white;border:1px solid #d8e0e8;border-radius:12px;padding:24px;margin:20px 0}}img{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;border-bottom:1px solid #d8e0e8;text-align:right}}td:first-child,th:first-child{{text-align:left}}a{{color:#0F4D92}}code{{background:#e8edf4;padding:2px 5px}}</style>
<h1>第四节课 · 回测系统与策略验证</h1><p>2026-10-16 · 只读原始数据 · 冻结时间划分 · 本地研究原型</p>
<div class="card"><h2>{verdict}</h2><p>验证期选中 <code>{summary['selected']}</code>。最终测试 {curves['selected'].index[0].date()} 至 {curves['selected'].index[-1].date()}；净收益 {selected['total_return']:.2%}，最大回撤 {selected['max_drawdown']:.2%}。相对等权基准总收益差 {selected['benchmark_excess_total_return']:.2%}。</p><p>年化算术平均超额的块自助法 95% 区间：{ci[0]:.2%} 至 {ci[1]:.2%}。</p><p><strong>复权份额研究账本；分红/送股、真实开盘撮合、历史 ST/涨跌停和整手限制尚未验证。不能据此声称可部署。</strong></p><p><a href="REPORT.md">完整中文报告与假设</a> · <a href="README.md">运行方法与策略公式</a> · <a href="results/summary.json">指标与验证门槛</a> · <a href="results/test_selected_orders.csv">逐单账本</a></p></div>
<div class="card"><table><thead><tr><th>方案</th><th>总收益</th><th>年化收益</th><th>夏普</th><th>最大回撤</th></tr></thead><tbody>{metric_rows}</tbody></table></div>{images}
<p>全部开发/验证候选在 <a href="results/candidates.csv">candidates.csv</a>。最终测试未据结果重新选择候选。2026 为不完整年度。</p></html>"""
    (root / "report.html").write_text(page)
