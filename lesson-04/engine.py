"""Daily long-only simulator with explicit synthetic units, cash, orders and fills."""
import numpy as np
import pandas as pd


def metrics(curve, initial_cash):
    returns = curve["return"].to_numpy()
    nav = curve["equity"].to_numpy() / initial_cash
    years = len(nav) / 252
    volatility = returns.std(ddof=1) if len(returns) > 1 else 0.
    peaks = np.maximum.accumulate(np.r_[1., nav])[1:]
    return {"days": len(nav), "total_return": float(nav[-1] - 1),
            "cagr": float(nav[-1] ** (1 / years) - 1) if years else 0.,
            "sharpe": float(returns.mean() / volatility * np.sqrt(252)) if volatility else 0.,
            "annual_vol": float(volatility * np.sqrt(252)),
            "max_drawdown": float(np.min(nav / peaks - 1)),
            "mean_exposure": float(curve.exposure.mean()),
            "annual_one_way_turnover": float(curve.turnover.mean() * 252 / 2),
            "fees": float(curve.fees.sum()), "slippage_cost": float(curve.slippage_cost.sum()),
            "min_cash": float(curve.cash.min()),
            "max_stale_value_fraction": float(curve.stale_value_fraction.max())}


def backtest(market, targets, start, end, config, cost_multiplier=1., keep_orders=False):
    if not np.isfinite(targets).all() or (targets < 0).any() or (targets.sum(axis=1) > 1.00001).any():
        raise ValueError("Targets must be finite, long-only and unlevered")
    dates, symbols = market["dates"], market["symbols"]
    indices = np.flatnonzero((dates >= start) & (dates <= end))
    if not len(indices):
        raise ValueError("Empty backtest interval")
    units = np.zeros(len(symbols))
    cash = previous_equity = config["initial_cash"]
    curve, orders, snapshots = [], [], []
    commission = config["commission_bps"] * cost_multiplier / 10000
    slip = config["slippage_bps"] * cost_multiplier / 10000
    amount20 = market["amount20"].to_numpy()
    for t in indices:
        opening, mark = market["open"][t], market["mark"][t]
        # At the open, absent quotes retain the PREVIOUS close; never today's close.
        previous_mark = market["mark"][t - 1] if t else np.zeros(len(symbols))
        valuation = np.where(np.isfinite(opening) & (opening > 0), opening, previous_mark)
        open_equity = cash + float(units @ valuation)
        fees_today = traded_today = slippage_today = 0.
        rejected_today = 0
        if t > 0 and t % config["rebalance_every"] == 0:
            weights = targets[t - 1]
            desired_value = weights * open_equity
            current_value = units * valuation
            desired_delta = desired_value - current_value
            desired_delta[np.abs(desired_delta) < .01] = 0
            # Capacity uses yesterday's rolling amount, not today's total amount.
            capacity = np.nan_to_num(amount20[t - 1], nan=0.) * config["participation"]
            sell_tax = config["sell_tax_bps_before_20230828"] if dates[t] < pd.Timestamp("2023-08-28") else config["sell_tax_bps_from_20230828"]
            tax = sell_tax * cost_multiplier / 10000
            # One opening per day; sell old units before buying. No same-day resale.
            for side in ("SELL", "BUY"):
                selected = np.flatnonzero(desired_delta < 0 if side == "SELL" else desired_delta > 0)
                executable = np.isfinite(opening[selected]) & (opening[selected] > 0)
                gap = market["gap"][t, selected]
                executable &= np.isfinite(gap)
                executable &= gap > -config["open_gap_guard"] if side == "SELL" else gap < config["open_gap_guard"]
                requested = np.abs(desired_delta[selected])
                reference_notional = np.minimum(requested, capacity[selected])
                reference_notional[~executable] = 0
                if side == "SELL":
                    reference_notional = np.minimum(reference_notional, units[selected] * valuation[selected])
                    fill_prices = opening[selected] * (1 - slip)
                else:
                    fill_prices = opening[selected] * (1 + slip)
                    required = reference_notional.sum() * (1 + slip) * (1 + commission)
                    reference_notional *= min(1., max(0., cash) / required) if required else 1.
                quantities = np.divide(reference_notional, opening[selected], out=np.zeros_like(reference_notional), where=executable)
                values = np.where(executable, quantities * fill_prices, 0.)
                costs = values * (commission + (tax if side == "SELL" else 0.))
                direction = -1 if side == "SELL" else 1
                units[selected] += direction * quantities
                cash -= float(direction * values.sum() + costs.sum())
                fees_today += float(costs.sum())
                traded_today += float(values.sum())
                slippage_today += float(reference_notional.sum() * slip)
                rejected_today += int((reference_notional < requested - .01).sum())
                if keep_orders:
                    for k, j in enumerate(selected):
                        reason = "filled"
                        if not executable[k]:
                            reason = "missing_open_or_gap_guard"
                        elif reference_notional[k] < requested[k] - .01:
                            reason = "partial_capacity_or_cash"
                        orders.append({"date": dates[t], "signal_date": dates[t - 1],
                                       "symbol": symbols[j], "side": side,
                                       "requested_reference_notional": float(requested[k]),
                                       "filled_reference_notional": float(reference_notional[k]),
                                       "adjusted_units": float(quantities[k]),
                                       "adjusted_fill_price": float(fill_prices[k]) if executable[k] else None,
                                       "notional": float(values[k]), "fee": float(costs[k]), "status": reason})
        if cash < -1e-6 or units.min() < -1e-8:
            raise AssertionError("Negative cash or short inventory")
        values = units * mark
        equity = cash + float(values.sum())
        stale_value = float(values[market["stale"][t] > 0].sum())
        curve.append({"date": dates[t], "equity": equity, "cash": cash,
                      "return": equity / previous_equity - 1,
                      "exposure": float(values.sum() / equity) if equity else 0.,
                      "holdings": int((units > 1e-10).sum()), "fees": fees_today,
                      "slippage_cost": slippage_today, "turnover": traded_today / open_equity if open_equity else 0.,
                      "constrained_orders": rejected_today, "stale_value_fraction": stale_value / equity if equity else 0.,
                      "written_down_positions": int(((units > 1e-10) & (mark == 0)).sum())})
        if keep_orders and (t == indices[-1] or t % config["rebalance_every"] == 0):
            for j in np.flatnonzero(units > 1e-10):
                snapshots.append({"date": dates[t], "symbol": symbols[j], "adjusted_units": units[j],
                                  "mark": mark[j], "value": values[j], "stale_days": int(market["stale"][t, j])})
        previous_equity = equity
    return (pd.DataFrame(curve).set_index("date"), pd.DataFrame(orders), pd.DataFrame(snapshots))


def block_bootstrap(excess, block=20, repetitions=2000, seed=20261016):
    """Paired daily excess; circular blocks retain some serial dependence."""
    x = np.asarray(excess)
    rng = np.random.default_rng(seed)
    means = np.empty(repetitions)
    offsets = np.arange(block)
    for i in range(repetitions):
        starts = rng.integers(0, len(x), size=int(np.ceil(len(x) / block)))
        indices = ((starts[:, None] + offsets) % len(x)).ravel()[:len(x)]
        means[i] = x[indices].mean() * 252
    return {"annualized_mean_excess": float(x.mean() * 252),
            "ci_95": [float(v) for v in np.quantile(means, [.025, .975])],
            "block_days": block, "repetitions": repetitions, "seed": seed}
