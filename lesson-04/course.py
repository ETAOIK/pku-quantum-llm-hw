"""Issue #8 protocol, kept separate from the original frozen experiment."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_data, prepare
from engine import metrics
from signals import score_signal

HERE = Path(__file__).resolve().parent
EVENTS = [
    ("2025-03-17", "600837.SH", "601211.SH", .62),
    ("2025-09-16", "601989.SH", "600150.SH", .1339),
]


def read_state(path, dates, symbols):
    """Build a dated mask from our direct provider queries."""
    frame = pd.read_parquet(path)
    frame["state"] = pd.to_numeric(frame.isST) * 2 + pd.to_numeric(frame.tradestatus)
    wide = frame.pivot(index="date", columns="symbol", values="state")
    return wide.reindex(index=dates, columns=symbols).fillna(-1).to_numpy(dtype=np.int8)


def simulate(market, score, state, config, factors, broad=False, events=EVENTS):
    dates, symbols = market["dates"], market["symbols"]
    indices = np.flatnonzero((dates >= config["test"][0]) & (dates <= config["test"][1]))
    units = np.zeros(len(symbols))
    weights = units.copy()
    cash = previous = config["initial_cash"]
    curve, orders, snapshots, conversions = [], [], [], []
    amount = market["amount20"].to_numpy()
    for day, t in enumerate(indices):
        for date, old, new, ratio in events:
            if dates[t] == pd.Timestamp(date) and old in symbols and new in symbols:
                a, b = symbols.get_loc(old), symbols.get_loc(new)
                old_factor = factors.iloc[:t + 1, a].dropna().iloc[-1]
                new_factor = factors.iloc[t, b]
                converted = units[a] * old_factor * ratio / new_factor
                if units[a] > 0:
                    conversions.append(dict(date=date, old=old, new=new, ratio=ratio,
                                            old_adjusted_units=units[a], new_adjusted_units=converted))
                units[b] += converted
                units[a] = 0
        opening = market["open"][t]
        previous_mark = market["mark"][t - 1]
        valuation = np.where(np.isfinite(opening), opening, previous_mark)
        open_equity = cash + units @ valuation
        # First-day opening is explicitly anchored; all ranks use yesterday's close.
        rebalance = day % config["rebalance_every"] == 0
        winding = day >= len(indices) - config["liquidation_days"]
        if rebalance and not winding:
            eligible = market["eligible"][t - 1] & (state[t - 1] == 1) & np.isfinite(score[t - 1])
            selected = np.flatnonzero(eligible)
            if not broad:
                selected = selected[np.argsort(-score[t - 1, selected], kind="stable")[:config["top_n"]]]
            weights[:] = 0
            if len(selected):
                weights[selected] = config["invested_fraction"] / len(selected)
        # A dated ST change removes the target and triggers an attempted exit.
        target = weights.copy()
        target[state[t] != 1] = 0
        if winding:
            target *= (len(indices) - day - 1) / config["liquidation_days"]
        fees = traded = slippage = 0.
        if rebalance or winding or np.any((units > 0) & (state[t] >= 2)):
            delta = target * open_equity - units * valuation
            capacity = np.nan_to_num(amount[t - 1], nan=0.) * config["participation"]
            for side in ("SELL", "BUY"):
                if winding and side == "BUY":
                    continue
                chosen = np.flatnonzero(delta < -.01 if side == "SELL" else delta > .01)
                valid = np.isfinite(opening[chosen]) & (opening[chosen] > 0) & (state[t, chosen] % 2 == 1) & (state[t, chosen] >= 0)
                gap = market["gap"][t, chosen]
                valid &= np.isfinite(gap) & ((gap > -config["open_gap_guard"]) if side == "SELL" else (gap < config["open_gap_guard"]))
                if side == "BUY":
                    valid &= state[t, chosen] == 1
                requested = np.abs(delta[chosen])
                fill = np.minimum(requested, capacity[chosen])
                fill[~valid] = 0
                slip = config["slippage_bps"] / 10000
                rate = (config["commission_bps"] + (5 if side == "SELL" else 0)) / 10000
                if side == "SELL":
                    fill = np.minimum(fill, units[chosen] * valuation[chosen])
                else:
                    required = fill.sum() * (1 + slip) * (1 + rate)
                    fill *= min(1., max(0., cash) / required) if required else 1.
                quantity = np.divide(fill, opening[chosen], out=np.zeros_like(fill), where=valid)
                sign = -1 if side == "SELL" else 1
                value = fill * (1 + sign * slip)
                cost = value * rate
                units[chosen] += sign * quantity
                cash -= float(sign * value.sum() + cost.sum())
                fees += cost.sum()
                traded += value.sum()
                slippage += fill.sum() * slip
                for k, j in enumerate(chosen):
                    orders.append(dict(date=dates[t], signal_date=dates[t - 1], symbol=symbols[j], side=side,
                                       requested_reference_notional=requested[k], filled_reference_notional=fill[k],
                                       adjusted_units=quantity[k], notional=value[k], fee=cost[k],
                                       is_st=int(state[t, j] >= 2), status="filled" if fill[k] >= requested[k] - .01 else "constrained"))
        units[np.abs(units) < 1e-9] = 0
        assert cash >= -1e-6 and units.min() >= 0
        values = units * market["mark"][t]
        equity = cash + values.sum()
        curve.append(dict(date=dates[t], equity=equity, cash=cash, return_=equity / previous - 1,
                          exposure=values.sum() / equity, holdings=int((units > 0).sum()), fees=fees,
                          slippage_cost=slippage, turnover=traded / open_equity,
                          stale_value_fraction=values[market["stale"][t] > 0].sum() / equity))
        if rebalance or winding or t == indices[-1]:
            for j in np.flatnonzero(units > 0):
                snapshots.append(dict(date=dates[t], symbol=symbols[j], adjusted_units=units[j],
                                      mark=market["mark"][t, j], value=values[j], stale_days=market["stale"][t, j]))
        previous = equity
    daily = pd.DataFrame(curve).rename(columns={"return_": "return"}).set_index("date")
    return daily, pd.DataFrame(orders), pd.DataFrame(snapshots), conversions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=HERE / "data/feathers.zip")
    parser.add_argument("--status", type=Path, default=HERE / "data/status.parquet")
    args = parser.parse_args()
    output = HERE / "assignment"
    output.mkdir(exist_ok=True)
    config = json.loads((HERE / "protocol.json").read_text())
    config.update(version="issue-8-20261023", frozen_on="2026-10-23 Asia/Shanghai; retrospective revision",
                  selection="reuse low_vol_60 selected by the original 2023-2024 validation; no assignment-period re-selection",
                  test=["2025-01-02", "2026-09-30"], initial_cash=1e9,
                  commission_bps=1., participation=.1, liquidation_days=20, stale_write_down_days=100000)
    for key in ("train", "validation", "candidate_ids", "stress_cost_multiplier", "bootstrap_block_days",
                "bootstrap_repetitions", "bootstrap_seed", "pass_gate"):
        config.pop(key, None)
    (output / "protocol.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    panels = load_data(args.data)
    market = prepare(panels, config)
    state = read_state(args.status, market["dates"], market["symbols"])
    score = score_signal("low_vol_60", panels, market)
    summary = {"protocol": config, "data_sha256": panels["source"]["sha256"],
               "status_sha256": hashlib.sha256(args.status.read_bytes()).hexdigest()}
    for name, broad in [("selected", False), ("equal_weight", True)]:
        print("Running", name, flush=True)
        daily, orders, holdings, conversions = simulate(market, score if not broad else np.zeros_like(score),
                                                       state, config, panels["cumadj"], broad=broad)
        daily.to_csv(output / f"{name}_daily.csv")
        orders.to_csv(output / f"{name}_orders.csv.gz", index=False)
        holdings.to_csv(output / f"{name}_holdings.csv.gz", index=False)
        summary[name] = {**metrics(daily, config["initial_cash"]), "final_equity": float(daily.equity.iloc[-1]),
                         "final_cash": float(daily.cash.iloc[-1]), "terminal_positions": int(daily.holdings.iloc[-1]),
                         "filled_orders": int((orders.notional > 0).sum()),
                         "st_buys": int(((orders.side == "BUY") & (orders.is_st == 1) & (orders.notional > 0)).sum()),
                         "first_fill": str(pd.to_datetime(orders.loc[orders.notional > 0, "date"]).min().date()),
                         "conversions": conversions}
        print(name, summary[name], flush=True)
    mask = (market["dates"] >= "2024-12-31") & (market["dates"] <= "2026-09-30")
    observed = panels["close"].to_numpy()[mask]
    summary["status_known_price_coverage"] = float(((state[mask] >= 0) & np.isfinite(observed)).sum() / np.isfinite(observed).sum())
    summary["checks"] = dict(no_st_buys=summary["selected"]["st_buys"] == 0,
                             first_day_built=summary["selected"]["first_fill"] == "2025-01-02",
                             final_cleared=summary["selected"]["terminal_positions"] == 0,
                             days_424=summary["selected"]["days"] == 424)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
