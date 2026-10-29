"""A bounded, chronological factor-mining round using the existing evaluator."""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from shared import FOURTH, LABELS, evaluate, load_context, score_signal, sha256
from factor import DEFAULTS, analyze, corr, hac_interval, save_result
from course import read_state, simulate
from engine import metrics

HERE = Path(__file__).resolve().parent
PROTOCOL = json.loads((HERE / "mining-protocol.json").read_text())
NEW_LABELS = {
    "reversal_20": "20日反转", "intraday_reversal_5": "5日日内反转",
    "intraday_reversal_20": "20日日内反转", "overnight_reversal_20": "20日隔夜反转",
    "amount_shock_reversal": "量能放大的5日反转", "reversal_low_amount": "反转+低成交额",
    "reversal_low_tradesize": "反转+低每笔金额", "reversal_low_vol60": "反转+60日低波动",
    "trend_pullback": "中期趋势+短期回撤", "range_low_amount": "区间低位+低成交额",
    "relative_amount_5_20": "近期相对缩量", "trade_count_shock": "近期成交笔数收缩"}


def by_adjust(pvalues):
    """BY correction accounts for arbitrary dependence, subject to valid p-values."""
    p = np.asarray(pvalues, dtype=float)
    result = np.full(p.shape, np.nan)
    valid = np.isfinite(p)
    m = int(valid.sum())
    if m:
        order = np.argsort(p[valid], kind="stable")
        adjusted = p[valid][order] * m * sum(1 / k for k in range(1, m + 1)) / np.arange(1, m + 1)
        adjusted = np.minimum(1., np.minimum.accumulate(adjusted[::-1])[::-1])
        locations = np.flatnonzero(valid)[order]
        result[locations] = adjusted
    return result


def positive_hac_p(series, horizon):
    values = np.asarray(series, dtype=float)
    mean = np.nanmean(values) if np.isfinite(values).any() else np.nan
    low, high = hac_interval(values, horizon)
    if not np.isfinite(low):
        return 1.
    se = (high - low) / 3.92
    return .5 * math.erfc(mean / (math.sqrt(2) * se)) if se > 1e-12 else 1.


def rank_correlation(scores, eligible, names):
    """Every day uses the same complete-case cross section for the whole matrix."""
    total = np.zeros((len(names), len(names)))
    counts = np.zeros_like(total)
    coverage = []
    for t in range(len(eligible)):
        values = np.array([scores[name][t] for name in names], dtype=float)
        common = eligible[t] & np.isfinite(values).all(axis=0)
        coverage.append({"row": t, "universe_count": int(eligible[t].sum()), "common_count": int(common.sum())})
        if common.sum() < 30:
            continue
        ranks = pd.DataFrame(values[:, common]).rank(axis=1).to_numpy()
        ranks -= ranks.mean(axis=1, keepdims=True)
        norm = np.sqrt((ranks * ranks).sum(axis=1, keepdims=True))
        standardized = np.divide(ranks, norm, out=np.zeros_like(ranks), where=norm > 0)
        current = standardized @ standardized.T
        valid = (norm > 0) & (norm.T > 0)
        total += np.where(valid, current, 0.)
        counts += valid
    matrix = np.divide(total, counts, out=np.full_like(total, np.nan), where=counts > 0)
    return pd.DataFrame(matrix, index=names, columns=names), pd.DataFrame(coverage)


def select_candidates(development, validation, correlation, new_names, rules):
    dev = development.set_index("factor")
    ranked = validation.sort_values(["rank_ic_ci_low", "rank_ic_mean", "factor"], ascending=[False, False, True])
    selected, decisions = [], []
    for row in ranked.to_dict("records"):
        name = row["factor"]
        reason = "selected"
        if name not in new_names:
            reason = "existing baseline"
        elif not (dev.loc[name, "rank_ic_mean"] > 0 and dev.loc[name, "spread_mean"] > 0):
            reason = "development direction/spread failed"
        elif not (row["rank_ic_mean"] > 0 and row["spread_mean"] > 0 and row["factor_coverage"] >= .8
                  and row["label_coverage"] >= .95 and row["by_q"] <= .1):
            reason = "validation evidence/coverage failed"
        elif any(not np.isfinite(correlation.loc[name, other]) or abs(correlation.loc[name, other]) >= rules["max_absolute_mutual_correlation"] for other in selected):
            reason = "redundant or unavailable correlation"
        elif len(selected) >= rules["max_new_candidates"]:
            reason = "predefined candidate limit"
        else:
            selected.append(name)
        decisions.append({"factor": name, "decision": reason})
    return selected, pd.DataFrame(decisions)


def residualize(score, controls, eligible):
    output = np.full(score.shape, np.nan, dtype=np.float32)
    for t in range(len(score)):
        x = np.array([control[t] for control in controls], dtype=float).T
        y = score[t].astype(float)
        valid = eligible[t] & np.isfinite(y) & np.isfinite(x).all(axis=1)
        if valid.sum() < 30:
            continue
        x = x[valid]
        x = np.clip(x, np.quantile(x, .01, axis=0), np.quantile(x, .99, axis=0))
        scale = x.std(axis=0)
        x = np.divide(x - x.mean(axis=0), scale, out=np.zeros_like(x), where=scale > 1e-12)
        design = np.column_stack([np.ones(len(x)), x])
        y = y[valid]
        y = np.clip(y, np.quantile(y, .01), np.quantile(y, .99))
        residual = y - design @ np.linalg.lstsq(design, y, rcond=None)[0]
        if residual.std() > max(1e-8, y.std() * 1e-5):
            output[t, valid] = residual
    return output


def block_excess(strategy, benchmark, block_days, repetitions, seed):
    """Paired moving-block resampling; never fill a missing trading-day return."""
    a, b = np.asarray(strategy), np.asarray(benchmark)
    if a.shape != b.shape or not (np.isfinite(a) & np.isfinite(b)).all():
        raise ValueError("Bootstrap needs aligned, finite paired daily returns")
    if len(a) < block_days:
        raise ValueError("Not enough days for the fixed block length")
    delta = a - b
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(delta) - block_days + 1, size=(repetitions, math.ceil(len(delta) / block_days)))
    indices = (starts[..., None] + np.arange(block_days)).reshape(repetitions, -1)[:, :len(delta)]
    values = delta[indices].mean(axis=1) * 252
    return {"annual_arithmetic_excess": float(delta.mean() * 252),
            "excess_ci_low": float(np.quantile(values, .025)), "excess_ci_high": float(np.quantile(values, .975))}


def backtests(panels, market, config, score_factory, selected, output, protocol):
    names = ["equal_weight", *protocol["fixed_baselines"], *selected]
    scenarios = [("base", 1e9, 1.), ("cost_stress", 1e9, 2.), ("small_cash", 1e6, 1.)]
    state = read_state(FOURTH / "data/status.parquet", market["dates"], market["symbols"])
    rows, ledgers, checks = [], {}, {}
    for scenario, cash, multiplier in scenarios:
        for name in names:
            print(f"Backtest {scenario}: {name}", flush=True)
            cfg = {**config, "test": protocol["splits"]["followup"], "initial_cash": cash,
                   "commission_bps": protocol["backtest"]["commission_bps"] * multiplier,
                   "slippage_bps": protocol["backtest"]["slippage_bps"] * multiplier}
            score = np.zeros(market["eligible"].shape, dtype=np.float32) if name == "equal_weight" else score_factory(name)
            daily, orders, holdings, conversions = simulate(market, score, state, cfg, panels["cumadj"], broad=name == "equal_weight")
            path = output / "backtests" / scenario / name
            path.mkdir(parents=True, exist_ok=True)
            daily.to_csv(path / "daily.csv", index_label="date")
            orders.to_csv(path / "orders.csv.gz", index=False, float_format="%.10g")
            holdings.to_csv(path / "holdings.csv.gz", index=False, float_format="%.10g")
            (path / "settings.json").write_text(json.dumps({"config": cfg, "factor": name, "conversions": conversions}, ensure_ascii=False, indent=2) + "\n")
            result = metrics(daily, cash)
            requested = orders.requested_reference_notional.sum()
            result.update(scenario=scenario, factor=name, terminal_positions=int(daily.holdings.iloc[-1]),
                          terminal_cash=float(daily.cash.iloc[-1]),
                          fill_fraction=float(orders.filled_reference_notional.sum() / requested) if requested else np.nan)
            ledgers[(scenario, name)] = daily
            checks[f"{scenario}/{name}"] = bool((orders.signal_date < orders.date).all() and daily.cash.min() >= -1e-6)
            rows.append(result)
            del orders, holdings, score
    for row in rows:
        daily = ledgers[(row["scenario"], row["factor"])]
        baseline = ledgers[(row["scenario"], "equal_weight")]
        assert daily.index.equals(baseline.index)
        benchmark_return = next(other["total_return"] for other in rows if other["scenario"] == row["scenario"] and other["factor"] == "equal_weight")
        row["total_excess_pp"] = (row["total_return"] - benchmark_return) * 100
        row.update(block_excess(daily["return"], baseline["return"], **protocol["bootstrap"]))
    pd.DataFrame(rows).to_csv(output / "backtests.csv", index=False, float_format="%.10g")
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "research-20261029")
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    protocol = json.loads((HERE / "mining-protocol.json").read_text())
    (output / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
    panels, market, config = load_context(FOURTH / "data/feathers.zip", FOURTH / "data/status.parquet")
    existing = [name for name in LABELS if name != "custom"]
    names = existing + list(protocol["new_candidates"])
    def score_factory(name):
        return evaluate(protocol["new_candidates"][name], panels, market) if name in protocol["new_candidates"] else score_signal(name, panels, market)
    settings = {**DEFAULTS, "horizons": protocol["diagnostic_horizons"]}
    summaries, cached = [], {}
    for stage in ("development", "validation"):
        start, end = protocol["splits"][stage]
        for name in names:
            print(f"Evaluate {stage}: {name}", flush=True)
            result = analyze(score_factory(name), market, {**settings, "start": start, "end": end})
            meta = {"factor": name, "formula": protocol["new_candidates"].get(name), "stage": stage, "start": start, "end": end,
                    "mode": protocol["mode"], "name": NEW_LABELS.get(name, LABELS.get(name)), "horizons": settings["horizons"]}
            save_result(output / "evaluations" / stage / name, result, meta)
            summary = result["summary"].assign(factor=name, stage=stage, family="new" if name in protocol["new_candidates"] else "existing")
            summary["hac_p_one_sided"] = [positive_hac_p(result["daily"].loc[(result["daily"].horizon == h) & result["daily"].label_mature, "rank_ic"], h) for h in summary.horizon]
            summaries.append(summary)
    summary = pd.concat(summaries, ignore_index=True)
    summary["by_q"] = np.nan
    for stage in ("development", "validation"):
        primary = (summary.stage == stage) & (summary.horizon == protocol["primary_horizon"])
        summary.loc[primary, "by_q"] = by_adjust(summary.loc[primary, "hac_p_one_sided"])
    dates = market["dates"]
    val_mask = (dates >= protocol["splits"]["validation"][0]) & (dates <= protocol["splits"]["validation"][1])
    for name in names:
        cached[name] = score_factory(name)[val_mask]
    correlation, coverage = rank_correlation(cached, market["eligible"][val_mask], names)
    correlation.to_csv(output / "validation-correlation.csv", index_label="factor")
    coverage.assign(date=dates[val_mask].strftime("%Y-%m-%d")).to_csv(output / "correlation-coverage.csv", index=False)
    dev = summary[(summary.stage == "development") & (summary.horizon == 5)]
    val = summary[(summary.stage == "validation") & (summary.horizon == 5)]
    selected, decisions = select_candidates(dev, val, correlation, protocol["new_candidates"], protocol["selection"])
    selection = {"selected": selected, "stage": "validation", "followup_not_used_for_selection": True,
                 "mode": protocol["mode"], "rules": protocol["selection"]}
    (output / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n")
    decisions.to_csv(output / "selection-decisions.csv", index=False)
    del cached
    # Selection is on disk before the subsequent interval is scored.
    for name in names:
        print(f"Evaluate followup: {name}", flush=True)
        start, end = protocol["splits"]["followup"]
        result = analyze(score_factory(name), market, {**settings, "start": start, "end": end})
        save_result(output / "evaluations/followup" / name, result, {"factor": name, "start": start, "end": end, "mode": protocol["mode"]})
        summaries.append(result["summary"].assign(factor=name, stage="followup", family="new" if name in protocol["new_candidates"] else "existing"))
    summary = pd.concat([summary, *summaries[2 * len(names):]], ignore_index=True)
    summary.to_csv(output / "factors.csv", index=False, float_format="%.10g")
    controls = [np.log(panels["close"].where(panels["close"] > 0)).to_numpy(),
                np.log(market["amount20"]).to_numpy(), market["close"].pct_change(fill_method=None).rolling(20).std().to_numpy()]
    exposure_rows = []
    for name in list(dict.fromkeys(protocol["fixed_baselines"] + selected)):
        print(f"Proxy controls: {name}", flush=True)
        score = score_factory(name)
        residual = residualize(score, controls, market["eligible"])
        for j, proxy in enumerate(protocol["proxy_controls"]):
            for t in np.flatnonzero((dates >= "2025-01-02") & (dates <= "2026-09-30")):
                valid = market["eligible"][t]
                exposure_rows.append({"factor": name, "proxy": proxy, "date": str(dates[t].date()),
                                      "rank_correlation": corr(np.where(valid, score[t], np.nan), controls[j][t], rank=True, minimum=30)})
        for stage in protocol["splits"]:
            start, end = protocol["splits"][stage]
            result = analyze(residual, market, {**settings, "start": start, "end": end})
            save_result(output / "proxy-residuals" / stage / name, result, {"factor": name, "stage": stage, "controls": protocol["proxy_controls"]})
    pd.DataFrame(exposure_rows).to_csv(output / "proxy-exposures.csv.gz", index=False, float_format="%.10g")
    checks = backtests(panels, market, config, score_factory, selected, output, protocol)
    checks.update(source_unchanged=sha256(FOURTH / "data/feathers.zip") == panels["source"]["sha256"],
                  all_30_factors_saved=summary.factor.nunique() == 30,
                  all_270_summary_rows=len(summary) == 270,
                  selection_written_before_followup=True)
    run = {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
           "source_sha256": panels["source"]["sha256"], "status_sha256": sha256(FOURTH / "data/status.parquet"),
           "protocol_sha256": sha256(HERE / "mining-protocol.json"),
           "code_sha256": {str(p.relative_to(HERE.parent)): sha256(p) for p in [HERE / "mining.py", HERE / "factor.py", FOURTH / "data.py", FOURTH / "signals.py", FOURTH / "formula.py", FOURTH / "course.py"]},
           "checks": checks, "deployment_validated": False, "mode": protocol["mode"]}
    (output / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    if not all(checks.values()):
        raise RuntimeError(f"Research checks failed: {checks}")
    print(json.dumps(selection, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
