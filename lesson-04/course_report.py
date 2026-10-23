"""Generate the concise submission from saved Issue #8 ledgers."""
import json
import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE / "assignment"


def main():
    summary = json.loads((ROOT / "summary.json").read_text())
    selected, baseline = summary["selected"], summary["equal_weight"]
    daily = pd.read_csv(ROOT / "selected_daily.csv")
    comparison = pd.read_csv(ROOT / "equal_weight_daily.csv")
    orders = pd.read_csv(ROOT / "selected_orders.csv.gz")
    signed = orders.notional.where(orders.side == "BUY", -orders.notional)
    cash_flow = (-signed - orders.fee).groupby(orders.date).sum().reindex(daily.date, fill_value=0).to_numpy()
    actual_cash_flow = np.diff(np.r_[1e9, daily.cash])
    fee_expected = orders.notional * np.where(orders.side == "SELL", .0006, .0001)
    quantities = orders.adjusted_units.where(orders.side == "BUY", -orders.adjusted_units)
    inventory = orders.assign(quantity=quantities).pivot_table(index="date", columns="symbol", values="quantity", aggfunc="sum").reindex(daily.date, fill_value=0).fillna(0).cumsum()
    with zipfile.ZipFile(HERE / "data/feathers.zip") as archive:
        panels = {name: pd.read_feather(io.BytesIO(archive.read(f"feathers/{name}.feather")),
                                        columns=["date", *inventory.columns]).set_index("date")
                  for name in ("close", "cumadj", "amt")}
    marked = (panels["close"] * panels["cumadj"]).where(panels["amt"] > 0).ffill().fillna(0).reindex(pd.to_datetime(daily.date))
    reconstructed = daily.cash.to_numpy() + (inventory.to_numpy() * marked.to_numpy()).sum(axis=1)
    capacity = panels["amt"].where(panels["amt"] > 0).rolling(20, min_periods=20).mean() * .1
    limits = capacity.to_numpy()[capacity.index.get_indexer(pd.to_datetime(orders.signal_date)), capacity.columns.get_indexer(orders.symbol)]
    status = pd.read_parquet(HERE / "data/status.parquet", columns=["date", "symbol", "isST", "tradestatus"])
    buys = orders[(orders.side == "BUY") & (orders.notional > 0)].copy()
    buys["date"] = pd.to_datetime(buys.date)
    known = buys.merge(status, on=["date", "symbol"], how="left", validate="many_to_one")
    checks = {**summary["checks"], "cash_ledger_reconciles": bool(np.allclose(cash_flow, actual_cash_flow, atol=1e-5)),
              "fees_match_1bp_plus_sell_5bp": bool(np.allclose(orders.fee, fee_expected)),
              "signals_before_execution": bool((pd.to_datetime(orders.signal_date) < pd.to_datetime(orders.date)).all()),
              "no_negative_cash_beyond_roundoff": bool(daily.cash.min() > -1e-6),
              "terminal_cash_equals_equity": bool(np.isclose(daily.cash.iloc[-1], daily.equity.iloc[-1])),
              "capacity_uses_previous_20days": bool(((orders.filled_reference_notional.to_numpy() == 0) | (orders.filled_reference_notional.to_numpy() <= limits + .01)).all()),
              "inventory_never_short": bool(inventory.to_numpy().min() > -1e-7),
              "terminal_inventory_from_fills_is_zero": bool(np.abs(inventory.iloc[-1]).max() < 1e-6),
              "daily_equity_rebuilt_from_fills_and_prices": bool(np.allclose(reconstructed, daily.equity, rtol=0, atol=1e-4)),
              "buy_status_independently_joined_to_provider": bool(((known.isST == "0") & (known.tradestatus == "1")).all())}
    assert all(checks.values()), checks
    provenance = json.loads((HERE / "data/status-source.json").read_text())
    provenance["known_price_coverage"] = summary["status_known_price_coverage"]
    assert provenance["errors"] == []
    assert provenance["status_sha256"] == summary["status_sha256"]
    (ROOT / "checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    (ROOT / "status-source.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n")
    text = f"""# 把交易想法写进网页：十亿元低波动实验

更新：2026-10-23。来源：[课程要求与数据](https://github.com/aslan9/pku_quantllm/issues/8)、[实际汇总](summary.json)、[账本检查](checks.json)。

这次我检验的直觉是：优先买入过去波动较小的股票，能否在控制回撤的同时获得较好的收益？我把这个想法做成可重复运行的网页：输入选股评分与条件，设置资金和交易成本，运行后查看净值、回撤、每笔成交及现金账本，也可以导出 CSV。

按老师要求采用 **10 亿元**初始资金，**2025-01-02 首日开盘开始建仓，至 2026-09-30，共 424 个交易日**；买卖佣金各万一，卖出印花税万五，另加单边 5 bps 滑点。信号仅使用前一日收盘及以前数据。历史 ST/*ST、停牌按逐日状态筛选，未知状态不新增买入；原包没有 ST 字段，不能用当前股票名称替代历史状态。

网页中的表达式是 `-ts_std(returns(close, 1), 60)`。其中 `returns` 计算复权日收益，`ts_std` 计算过去 60 日波动，负号使波动较小的股票排名靠前。每 5 日取前 50 只等权，目标仓位 95%。这个评分沿用此前用 2023–2024 年验证数据从 18 个候选中选出的结果；原始方案、候选和失败结论均保留在仓库，没有按本期收益重新挑赢家。

行情来自课程 7 份 Feather（1,643 日 × 5,451 只证券）。可投池还要求至少 120 个有效观察、近 20 日连续有效、股价≥2 元、20 日均成交额≥2,000 万元。每只每日成交额上限为前 20 日均额的 10%；4.8% 方向跳空保护是额外的日线近似。为满足结束日离场，末 20 日逐步降低目标仓位、不再买入，卖出仍受原有约束。

**10 亿元最后变为 {selected['final_cash']/1e8:.6f} 亿元现金。**累计净收益 **{selected['total_return']:.2%}**，年化 **{selected['cagr']:.2%}**，最大回撤 **{selected['max_drawdown']:.2%}**，夏普 **{selected['sharpe']:.3f}**。首笔成交发生在 2025-01-02，期末股票为 **0 只**，ST 买入成交为 **0**。佣金及印花税合计 {selected['fees']/1e4:,.2f} 万元，滑点成本 {selected['slippage_cost']/1e4:,.2f} 万元；滑点已计入成交价。平均实际仓位 {selected['mean_exposure']:.2%}，年化按 252 日、无风险利率按 0 计算。

这次最值得保留的发现有两点。第一，**赚到钱并不等于选股有效**：同池等权估值收益为 {baseline['total_return']:.2%}，低波动落后 {(baseline['total_return']-selected['total_return'])*100:.2f} 个百分点。这个等权组合是自建对照，期末尚有 {baseline['terminal_positions']} 笔、约 {(baseline['final_equity']-baseline['final_cash'])/1e4:.2f} 万元残仓，其收益仍含未变现估值。第二，**目标仓位降到零与实际卖完是两回事**：检查中发现末几日才退出会留下残仓，因而把退出安排提前到 20 日，最后通过成交和现金账本核对清仓。这个修订是在查看结果后完成的，不能把修订后的表现称为全新独立样本外证据。

本次运行有 40 项自动测试、{len(checks)} 项账本检查通过。历史 ST 状态由 [fetch_status.py](../fetch_status.py) 直接查询 BaoStock 的 `isST` 和 `tradestatus`，共请求 {provenance['requested_symbols']:,} 只证券、取得 {provenance['rows']:,} 条记录，查询错误为 0；本区间有价格单元的状态覆盖率 {summary['status_known_price_coverage']:.2%}。[状态说明](status-source.json) 保存接口、时间和哈希。原始行情及状态宽表不重复上传。

采用小数复权份额而非真实整手，缺完整分红到账与涨跌停盘口；每日状态和复权因子在开盘可用、日线有效价格可成交均为研究假设。补充海通证券、中国重工换股事件，等权账本实际触发；[海通新增股上市公告](https://www.hkexnews.hk/listedco/listconews/sehk/2025/0313/2025031301549_c.pdf)、[中国船舶公告](https://static.cninfo.com.cn/finalpage/2025-09-12/1224653316.PDF)。其他公司行为尚不完整，停牌期间沿用最后有效价格，未用估值归零伪造清仓。既有测试区间已被观察，本次不是全新独立样本外验证，更不代表实盘容量或盈利保证。

下面两张是实际网页截图：第一张是作业结果，第二张是可编辑策略。运行方法见 [系统说明](../README.md)。

![本次实验记录网页](experiment.jpg)

![可编辑策略公式](strategy-editor.jpg)

[逐日资金](selected_daily.csv) · [逐单委托](selected_orders.csv.gz) · [持仓快照](selected_holdings.csv.gz) · [本次代码](../course.py) · [原始候选比较](../results/candidates.csv)。
"""
    (ROOT / "REPORT.md").write_text(text)
    nav = np.r_[1., daily.equity.to_numpy() / 1e9]
    base = np.r_[1., comparison.equity.to_numpy() / 1e9]
    dd = nav / np.maximum.accumulate(nav) - 1
    def path(values, bottom, top, y, height):
        x = np.linspace(45, 1060, len(values))
        z = y + height * (top - values) / (top - bottom)
        return " ".join(f"{a:.2f},{b:.2f}" for a, b in zip(x, z))
    top = float(max(nav.max(), base.max()) * 1.025)
    bottom = float(min(nav.min(), base.min()) * .975)
    ticks = np.linspace(bottom, top, 4)
    grid = "".join(f'<path d="M45 {24+253*(top-v)/(top-bottom):.1f}H1060"/><text x="0" y="{28+253*(top-v)/(top-bottom):.1f}">{v:.2f}</text>' for v in ticks)
    html = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>十亿元低波动实验 · 第四讲</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f7f5ef;color:#252a2a;font:16px -apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif}}main{{max-width:1160px;margin:34px auto;padding:0 28px}}header{{display:flex;justify-content:space-between;border-bottom:2px solid #252a2a;padding-bottom:12px;font-size:13px;letter-spacing:2px}}h1{{font-size:44px;letter-spacing:-2px;margin:26px 0 14px;font-weight:600}}p{{line-height:1.85;color:#5e6462}}.opening{{display:grid;grid-template-columns:1.3fr 1fr;gap:48px}}.big{{font-size:76px;letter-spacing:-4px;color:#286f6b;font-weight:500;line-height:1.15}}.caption{{font-size:13px;color:#6a716d}}.result{{border-left:1px solid #cacdc4;padding-left:32px;display:grid;grid-template-columns:1fr 1fr;gap:18px;align-content:center}}.result b{{font-size:25px;font-weight:500;display:block;margin-top:7px}}.figure{{margin-top:26px;border-top:1px solid #bbbfb6;padding-top:18px}}.figure h2{{font-size:18px;font-weight:500;margin:0}}svg{{width:100%;height:auto}}.lesson{{display:grid;grid-template-columns:1fr 1fr;gap:40px;border-top:1px solid #bbbfb6;padding-top:20px}}.lesson span{{font:12px monospace;color:#a27144}}.lesson h3{{font-size:19px;font-weight:500;margin:10px 0}}.lesson p{{font-size:14px;margin:0}}code{{background:#ecebe3;padding:5px 8px;color:#286f6b}}a{{color:#286f6b}}footer{{margin:25px 0;border-top:1px solid #bbbfb6;padding-top:12px;font-size:12px;line-height:1.8;color:#7b817b}}@media(max-width:700px){{.opening,.lesson{{grid-template-columns:1fr;gap:20px}}h1{{font-size:32px}}.big{{font-size:56px}}.result{{border-left:0;padding:0}}}}</style><main>
<header><span>课堂实验 / 04</span><span>2026.10.23 · 实际运行记录</span></header>
<h1>让十亿元走一遍低波动策略</h1>
<div class="opening"><section><p>把“买波动较小的股票”写成一条公式，<br>再让资金、费用和成交约束给出答案。</p><div class="big">{selected['total_return']:+.2%}</div><p class="caption">累计净收益 · 10 亿元 → {selected['final_cash']/1e8:.6f} 亿元现金<br>2025-01-02 建仓 → 2026-09-30 清仓 · 424 个交易日</p></section>
<section class="result"><div><span class="caption">最大回撤</span><b>{selected['max_drawdown']:.2%}</b></div><div><span class="caption">夏普 / 无风险利率 0</span><b>{selected['sharpe']:.3f}</b></div><div><span class="caption">年化收益 / 252 日</span><b>{selected['cagr']:.2%}</b></div><div><span class="caption">期末持仓 / ST 买入</span><b>0 / 0</b></div></section></div>
<section class="figure"><h2>资金在历史中如何变化</h2><p class="caption" style="margin:5px 0">青色：低波动策略　赭色：同池等权估值对照 {baseline['total_return']:.2%}（对照尚余 {baseline['terminal_positions']} 笔残仓）</p>
<svg viewBox="0 0 1100 435" role="img" aria-label="实际净值与回撤曲线"><g fill="#899087" font-size="13" stroke="#dfdfd4" stroke-width=".6">{grid}</g><polyline points="{path(base,bottom,top,24,253)}" fill="none" stroke="#b78e65" stroke-width="2"/><polyline points="{path(nav,bottom,top,24,253)}" fill="none" stroke="#286f6b" stroke-width="3"/><text x="45" y="310" fill="#899087" font-size="13">低波动策略回撤 · 0% 至 −16%</text><path d="M45 324H1060" stroke="#dfdfd4"/><polyline points="{path(dd,-.16,0,324,70)}" fill="none" stroke="#286f6b" stroke-width="2"/><g fill="#899087" font-size="13"><text x="45" y="426">2025-01-02</text><text x="950" y="426">2026-09-30</text></g></svg></section>
<section class="lesson"><article><span>01 / 一个可以重复提问的工具</span><h3>输入规则，运行，核对每笔账。</h3><p><code>-ts_std(returns(close, 1), 60)</code><br>网页允许修改评分、条件和参数。历史非 ST 池，每 5 日取 50 只，95% 目标仓位；前日信号、次日开盘执行。佣金万一、卖出税万五，另计单边 5 bps 滑点。</p></article><article><span>02 / 这次实验留下的认识</span><h3>盈利之后，还要检查超额与退出。</h3><p>本策略跑输等权对照，尚无正超额证据。末 20 日逐步退出后，实际库存和现金账本才确认清仓。40 项自动测试、{len(checks)} 项账本检查通过；日线撮合、复权份额和公司行为仍有限制。</p></article></section>
<footer><a href="REPORT.md">阅读简报</a>　<a href="selected_daily.csv">查看逐日资金</a>　<a href="checks.json">核对检查结果</a>　<a href="/">打开可编辑工作台 →</a><br>历史状态由本次直接查询 BaoStock 获得；原始行情指纹 {summary['data_sha256'][:16]}…　结果用于课程研究，未证明实盘有效。</footer></main></html>"""
    (ROOT / "report.html").write_text(html)
    print(json.dumps({"checks": checks, "direct_status_rows": provenance["rows"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
