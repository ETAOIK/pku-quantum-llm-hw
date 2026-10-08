"""One fixed round: 16 gap factors, train selection, validation gate, sealed holdout."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from factors import DESCRIPTIONS, compute

HERE = Path(__file__).resolve().parent
FACTORS = list(DESCRIPTIONS)
PRODUCTS = ("RB", "AG", "AU")


def load_panel(plan):
    lock = json.loads((HERE / "data-lock.json").read_text())
    all_bars, audit = [], []
    for entry in lock["contracts"]:
        symbol = entry["symbol"]
        path = HERE / "data" / f"{symbol}.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], symbol
        bars = pd.DataFrame(json.loads(path.read_text())).rename(columns={
            "d": "date", "o": "open", "h": "high", "l": "low", "c": "close",
            "v": "volume", "p": "hold", "s": "settle"})
        bars.date = pd.to_datetime(bars.date)
        for key in ("open", "high", "low", "close", "volume", "hold", "settle"):
            bars[key] = pd.to_numeric(bars[key], errors="raise")
        bars = bars.sort_values("date").reset_index(drop=True)
        if bars.date.duplicated().any():
            raise ValueError(f"Duplicate contract dates: {symbol}")
        prices = bars[["open", "high", "low", "close"]]
        valid = (np.isfinite(prices).all(axis=1) & (prices>0).all(axis=1)
                 & (bars.high >= prices.max(axis=1)) & (bars.low <= prices.min(axis=1))
                 & (bars.volume >= 0) & (bars.hold >= 0))
        audit.append({"symbol": symbol, "rows": len(bars), "invalid_rows": int((~valid).sum())})
        # Preserve date slots: removing bad rows would manufacture multi-day gaps.
        bars.loc[~valid, ["open", "high", "low", "close", "volume", "hold"]] = np.nan
        bars = bars[bars.date <= plan["holdout"][1]].copy()
        bars[FACTORS] = compute(bars)
        bars["symbol"], bars["product"] = symbol, symbol[:2]
        bars["entry_date"] = bars.date.shift(-1)
        bars["target"] = bars.close.shift(-1)/bars.open.shift(-1)-1
        bars["delivery_cutoff"] = pd.Timestamp(2000+int(symbol[2:4]), int(symbol[4:6]), 1)-pd.Timedelta(days=30)
        all_bars.append(bars)
    panel = pd.concat(all_bars, ignore_index=True)
    calendar = pd.DatetimeIndex(sorted(panel.date.unique()))
    next_day = pd.Series(calendar[1:].to_numpy(), index=calendar[:-1])
    panel["expected_entry"] = panel.date.map(next_day)
    eligible = ((panel.volume >= plan["min_signal_volume"])
                & (panel.hold >= plan["min_signal_hold"])
                & (panel.expected_entry < panel.delivery_cutoff)
                & panel[FACTORS].notna().all(axis=1))
    # Selection uses signal-day information, never next-day volume or return.
    chosen = (panel[eligible].sort_values(["date","product","volume","symbol"], ascending=[True,True,False,True])
              .drop_duplicates(["date","product"]).copy())
    missing_next = chosen.entry_date != chosen.expected_entry
    chosen.loc[missing_next, "target"] = np.nan
    chosen.entry_date = chosen.expected_entry
    chosen = chosen[(chosen.entry_date >= plan["train"][0]) & (chosen.entry_date <= plan["holdout"][1])]
    audit_summary = {"contracts": len(audit), "raw_rows": sum(e["rows"] for e in audit),
                     "invalid_rows": sum(e["invalid_rows"] for e in audit),
                     "missing_next_selected": int(missing_next.sum()),
                     "selected_samples": len(chosen), "by_product": chosen.groupby("product").size().to_dict(),
                     "contract_audit": audit}
    return chosen.reset_index(drop=True), calendar, audit_summary


def segment(panel, plan, name):
    start, end = plan[name]
    return panel[(panel.entry_date >= start) & (panel.entry_date <= end)].copy()


def thresholds(train, factor):
    return {product: float(train.loc[train["product"]==product, factor].abs().quantile(0.7))
            for product in PRODUCTS}


def evaluate(panel, calendar, factor, limits, cost):
    frame = panel[["entry_date","date","product","symbol","target",factor]].copy()
    value = frame[factor]
    active = (value.abs() >= frame["product"].map(limits)) & value.ne(0) & frame.target.notna()
    frame["position"] = np.sign(value).where(active, 0)
    frame["gross"] = frame.position*frame.target.fillna(0)
    frame["net"] = frame.gross-frame.position.abs()*cost/10000
    daily = frame.groupby("entry_date")[["gross","net"]].sum().reindex(calendar,fill_value=0)/3
    sd = daily.net.std(ddof=1)
    ic = {}
    for product, rows in frame.groupby("product"):
        clean = rows[[factor,"target"]].dropna()
        ic[product] = float(clean[factor].rank().corr(clean.target.rank())) if clean[factor].nunique()>1 else None
    mean_ic = float(np.mean([v for v in ic.values() if v is not None]))
    equity = (1+daily.net).cumprod()
    peak = equity.cummax().clip(lower=1)
    metrics = {"factor":factor, "cost_bps":cost, "samples":len(frame),
               "trades":int(active.sum()), "rank_ic":mean_ic, "ic_by_product":ic,
               "mean_net_bps":float(daily.net.mean()*10000),
               "sharpe":float(np.sqrt(252)*daily.net.mean()/sd) if sd>0 else 0.0,
               "total_return":float(equity.iloc[-1]-1),
               "max_drawdown":float((equity/peak-1).min()),
               "active_win_rate":float((frame.loc[active,"net"]>0).mean()) if active.any() else None}
    return metrics, daily, frame


def passes(metrics, min_trades):
    return metrics["trades"] >= min_trades and metrics["rank_ic"] > 0 and metrics["mean_net_bps"] > 0


def block_interval(daily):
    """Descriptive 5-day block bootstrap; not a multiple-testing adjusted p-value."""
    x = daily.net.to_numpy()
    rng = np.random.default_rng(20261008)
    means = []
    for _ in range(2000):
        starts = rng.integers(0,len(x),size=(len(x)+4)//5)
        indices = (starts[:,None]+np.arange(5)) % len(x)
        means.append(x[indices.ravel()[:len(x)]].mean()*10000)
    return np.quantile(means,[0.025,0.975]).tolist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE/"round-01")
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("Output exists; choose a new path to reproduce without overwriting evidence")
    plan = json.loads((HERE/"plan.json").read_text())
    panel, calendar, audit = load_panel(plan)
    parts = {name:segment(panel,plan,name) for name in ("train","validation","holdout")}
    days = {name:calendar[(calendar>=plan[name][0]) & (calendar<=plan[name][1])] for name in parts}
    for name, part in parts.items():
        assert len(part)>200 and len(days[name])>100, f"Too little {name} data"
    limits, train_metrics = {}, []
    for factor in FACTORS:
        limits[factor] = thresholds(parts["train"],factor)
        metrics,_,_ = evaluate(parts["train"],days["train"],factor,limits[factor],plan["primary_cost_bps"])
        train_metrics.append(metrics)
    eligible = [m for m in train_metrics if passes(m,100)]
    eligible.sort(key=lambda m:(-m["sharpe"],m["factor"]))
    selected = eligible[0]["factor"] if eligible else None
    summary = {"round":1, "candidate_count":len(FACTORS), "max_rounds":4,
               "selected_on_train":selected, "train_eligible":len(eligible),
               "thresholds":limits, "validation_passed":False, "holdout_opened":False,
               "holdout_passed":False, "status":"no_train_candidate"}
    args.output.mkdir(parents=True)
    pd.DataFrame([{"factor":key,"formula":value} for key,value in DESCRIPTIONS.items()]).to_csv(args.output/"candidates.csv",index=False)
    pd.DataFrame([{k:v for k,v in m.items() if k!="ic_by_product"} for m in train_metrics]).to_csv(args.output/"train-metrics.csv",index=False)
    train = parts["train"]
    train[FACTORS].corr(method="pearson").to_csv(args.output/"train-factor-correlation.csv")
    audit["segments"] = {name:{"samples":len(part),"days":len(days[name]),
                                "by_product":part.groupby("product").size().to_dict()} for name,part in parts.items()}
    (args.output/"data-audit.json").write_text(json.dumps(audit,indent=2)+"\n")
    if selected:
        for name in ("train","validation","holdout"):
            if name=="holdout" and not summary["validation_passed"]:
                break
            metrics, daily, trades = evaluate(parts[name],days[name],selected,limits[selected],plan["primary_cost_bps"])
            metrics["mean_net_bps_block95"] = block_interval(daily)
            metrics["cost_sensitivity"] = [evaluate(parts[name],days[name],selected,limits[selected],c)[0]
                                            for c in plan["roundtrip_cost_bps"]]
            summary[name] = metrics
            daily.to_csv(args.output/f"selected-{name}-daily.csv",index_label="entry_date")
            trades.to_csv(args.output/f"selected-{name}-observations.csv",index=False)
            if name=="validation":
                summary["validation_passed"] = passes(metrics,50)
                summary["status"] = "validation_passed" if summary["validation_passed"] else "validation_failed_stop"
            elif name=="holdout":
                summary["holdout_opened"] = True
                summary["holdout_passed"] = passes(metrics,50)
                summary["status"] = "holdout_passed_provisional" if summary["holdout_passed"] else "holdout_failed_stop"
    summary["artifacts_sha256"] = {file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(args.output.glob("*.csv"))}
    summary["inputs_sha256"] = {name:hashlib.sha256((HERE/name).read_bytes()).hexdigest()
                                for name in ("plan.json","data-lock.json","factors.py","run.py")}
    (args.output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    print(json.dumps({key:summary[key] for key in ("candidate_count","selected_on_train","status","holdout_opened")},ensure_ascii=False))


if __name__ == "__main__":
    main()
