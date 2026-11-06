"""Reconstruct saved cash/inventory and independently check chronology and reported metrics."""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from harness import HERE, Tools, benchmark, digest, evaluate, read, sha256, write


def verify(output, data, status):
    state, protocol = read(output / "state.json"), read(output / "protocol.json")
    frozen, selection = read(output / "freeze.json"), read(output / "selection.json")
    history = state["history"]
    checks = {"complete": state["phase"] == "complete", "candidate_budget": len(history) == protocol["generations"] * protocol["batch_size"],
              "freeze_history_digest": frozen["history_sha256"] == digest(history),
              "selection_freeze_digest": selection["freeze_sha256"] == sha256(output / "freeze.json"),
              "freeze_before_selection": frozen["frozen_at"] <= selection["selected_at"],
              "no_followup_selection": selection["followup_used_for_selection"] is False}
    original = HERE / "provenance/interactive-session"
    if (original / "state.json").exists():
        checks["replay_matches_interactive_history"] = history == read(original / "state.json")["history"]
        checks["interactive_source_fingerprint"] = sha256(original / "harness-source.py.txt") == read(original / "manifest.json")["source_sha256"]["lesson-06/harness.py"]
    def passes(folds):
        rules = protocol["gate"]
        return all(all(f[k] is not None and np.isfinite(f[k]) and f[k] > rules[r] for k, r in (
            ("rank_ic_mean", "min_rank_ic"), ("spread_mean", "min_spread"), ("annual_excess", "min_excess")))
            and all(f[k] is not None and f[k] >= rules[r] for k, r in (
                ("factor_coverage", "min_factor_coverage"), ("label_coverage", "min_label_coverage"), ("pool_coverage", "min_pool_coverage"))) for f in folds)
    order = lambda items: sorted(items, key=lambda c: (not c["development_pass"], -c["objective"], c["id"]))
    checks["frozen_shortlist"] = frozen["shortlist"] == [c["id"] for c in order(history)[:protocol["shortlist_size"]]]
    checks["generation_champions"] = frozen["generation_champions"] == [order([c for c in history if c["generation"] == g])[0]["id"] for g in range(protocol["generations"])]
    for g in range(protocol["generations"]):
        folder = output / f"round-{g:02d}"
        context, proposal, feedback = [read(folder / f"{name}.json") for name in ("context", "proposal", "feedback")]
        saved = context.pop("context_sha256")
        checks[f"round_{g}_context"] = saved == proposal["context_sha256"] == feedback["context_sha256"] == digest(context)
        checks[f"round_{g}_prior_history"] = context["history"] == history[:g * protocol["batch_size"]]
        checks[f"round_{g}_proposal_count"] = len(proposal["candidates"]) == protocol["batch_size"]
        prior = {c["id"] for c in context["history"]}
        checks[f"round_{g}_parents"] = all(set(c["parents"]) <= prior and bool(c["parents"]) == (g > 0) for c in proposal["candidates"])
        actual = {c["id"]: c for c in history if c["generation"] == g}
        checks[f"round_{g}_proposal_binding"] = all({k: actual[c["id"]][k] for k in c} == c for c in proposal["candidates"])
    by_id = {c["id"]: c for c in history}
    for c in history:
        checks[f"gate/{c['id']}"] = c["development_pass"] == passes(c["folds"])
    ordered_validation = sorted(selection["validation"], key=lambda c: (not c["qualified"], -c["validation_objective"], c["id"]))
    qualified = [c["id"] for c in ordered_validation if c["qualified"]]
    checks["validation_gate"] = all(c["qualified"] == (by_id[c["id"]]["development_pass"] and passes([c])) for c in selection["validation"])
    checks["selection_rule"] = selection["qualified_candidate"] == (qualified[0] if qualified else None) and selection["diagnostic_leader"] == ordered_validation[0]["id"]
    tools = Tools(output, data, status)
    benchmarks = {fold: tools.run(benchmark(), period, diagnostics=False)[1] for fold, period in protocol["development"].items()}
    for c in history:
        objective = min(f["annual_excess"] for f in c["folds"]) - .25 * max(abs(f["max_drawdown"]) for f in c["folds"]) - .0001 * c["ast_nodes"]
        checks[f"objective/{c['id']}"] = bool(np.isclose(c["objective"], objective, atol=1e-12))
        for f in c["folds"]:
            daily = pd.read_csv(output / f"round-{c['generation']:02d}" / c["id"] / f["fold"] / "daily.csv", index_col="date", parse_dates=True)
            b = benchmarks[f["fold"]]
            checks[f"development/{c['id']}/{f['fold']}"] = bool(daily.index.equals(b.index)
                and np.isclose((daily["return"].to_numpy() - b["return"].to_numpy()).mean() * 252, f["annual_excess"], atol=1e-10)
                and np.isclose(daily.equity.iloc[-1] / 1e9 - 1, f["total_return"], atol=1e-10))
    frame = pd.read_csv(output / "followup.csv")
    mark = pd.DataFrame(tools.market["mark"], index=tools.market["dates"], columns=tools.market["symbols"])
    max_cash_error = max_equity_error = max_ic_error = 0.
    for row in frame.to_dict("records"):
        folder = output / "backtests" / row["scenario"] / row["id"]
        settings = read(folder / "settings.json")
        initial = settings["config"]["initial_cash"]
        daily = pd.read_csv(folder / "daily.csv", index_col="date", parse_dates=True)
        orders = pd.read_csv(folder / "orders.csv.gz", parse_dates=["date", "signal_date"])
        holdings = pd.read_csv(folder / "holdings.csv.gz", parse_dates=["date"])
        key = f"{row['scenario']}/{row['id']}"
        cashflow = np.where(orders.side == "SELL", orders.notional, -orders.notional) - orders.fee
        cash = pd.Series(cashflow.to_numpy(), index=orders.date, dtype=float).groupby(level=0).sum().reindex(daily.index, fill_value=0).cumsum() + initial
        signed = orders.adjusted_units * np.where(orders.side == "BUY", 1., -1.)
        inventory = (orders.assign(units=signed).pivot_table(index="date", columns="symbol", values="units", aggfunc="sum", fill_value=0.)
                     if len(orders) else pd.DataFrame(index=daily.index))
        inventory = inventory.reindex(index=daily.index, fill_value=0.).cumsum()
        value = (inventory * mark.reindex(index=daily.index, columns=inventory.columns)).sum(axis=1)
        max_cash_error = max(max_cash_error, float(np.abs(cash - daily.cash).max()))
        max_equity_error = max(max_equity_error, float(np.abs(cash + value - daily.equity).max()))
        checks[f"cash/{key}"] = bool(np.allclose(cash, daily.cash, atol=.05, rtol=1e-10))
        # Orders were exported with 12 significant digits; bound accumulated unit-rounding per symbol.
        gross_units = orders.assign(units=orders.adjusted_units).groupby("symbol").units.sum()
        nonnegative = (inventory.min() >= -(gross_units.reindex(inventory.columns) * 1e-10 + 1e-8)).all()
        checks[f"inventory/{key}"] = bool(nonnegative and np.allclose(cash + value, daily.equity, atol=.1, rtol=1e-9))
        if len(holdings):
            reconstructed = np.array([inventory.loc[d, s] for d, s in zip(holdings.date, holdings.symbol)])
            checks[f"snapshots/{key}"] = bool(np.allclose(reconstructed, holdings.adjusted_units, rtol=1e-8, atol=1e-4))
        else:
            checks[f"snapshots/{key}"] = bool(daily.holdings.eq(0).all())
        baseline = pd.read_csv(output / "backtests" / row["scenario"] / "equal_weight/daily.csv", index_col="date", parse_dates=True)
        nav = daily.equity.to_numpy() / initial
        drawdown = np.min(nav / np.maximum.accumulate(np.r_[1., nav])[1:] - 1)
        expected_return = daily.equity / daily.equity.shift(1).fillna(initial) - 1
        checks[f"metrics/{key}"] = bool(np.allclose(expected_return, daily["return"], atol=1e-12)
            and daily.index.equals(baseline.index) and np.isclose(nav[-1] - 1, row["total_return"], atol=1e-9)
            and np.isclose(drawdown, row["max_drawdown"], atol=1e-9)
            and np.isclose((daily["return"] - baseline["return"]).mean() * 252, row["annual_excess"], atol=1e-9)
            and int(daily.holdings.iloc[-1]) == row["terminal_positions"])
        checks[f"execution/{key}"] = bool((orders.signal_date < orders.date).all() and daily.cash.min() >= -1e-6
            and not ((orders.side == "BUY") & (orders.is_st == 1) & (orders.notional > 0)).any())
        fees = orders.groupby("date").fee.sum().reindex(daily.index, fill_value=0)
        checks[f"fees/{key}"] = bool(np.allclose(fees, daily.fees, atol=.01, rtol=1e-9))
        if row["scenario"] == "base" and row["id"] != "equal_weight":
            c = settings["candidate"]
            score = evaluate(c["formula"], tools.panels, tools.market)
            condition = evaluate(c["condition"], tools.panels, tools.market, condition=True)
            saved = pd.read_csv(folder / "factor/daily.csv.gz")
            errors = []
            for f in saved[saved.label_mature].iloc[::17].to_dict("records"):
                t = tools.market["dates"].get_loc(pd.Timestamp(f["date"]))
                h = protocol["horizon"]
                opening = tools.market["open"]
                entry, exit_ = opening[t+1], opening[t+1+h]
                valid = tools.market["eligible"][t] & condition[t] & np.isfinite(score[t]) & np.isfinite(entry) & np.isfinite(exit_) & (entry > 0) & (exit_ > 0)
                labels = exit_[valid] / entry[valid] - 1
                actual = pd.Series(score[t, valid]).corr(pd.Series(labels), method="spearman") if valid.sum() >= 30 else np.nan
                errors.append(0. if np.isnan(actual) and pd.isna(f["rank_ic"]) else abs(actual - f["rank_ic"])
                              if np.isfinite(actual) and pd.notna(f["rank_ic"]) else np.inf)
            max_ic_error = max(max_ic_error, max(errors, default=0.))
            checks[f"independent_label_ic/{row['id']}"] = bool(errors and max(errors) < 1e-8
                and (saved.loc[saved.label_mature, "exit_date"] <= protocol["followup"][1]).all())
        del orders, holdings, inventory
    result = {"checks": checks, "passed": all(checks.values()), "check_count": len(checks),
              "max_cash_reconstruction_error_cny": max_cash_error, "max_equity_reconstruction_error_cny": max_equity_error,
              "max_sampled_rank_ic_error": max_ic_error,
              "scope": "Chronology/digests, development summaries, all saved followup cash and inventories, sampled independent labels/IC. Not proof of market realism or independent future performance."}
    write(output / "verification.json", result)
    print({k: v for k, v in result.items() if k != "checks"})
    if not result["passed"]:
        raise AssertionError([name for name, passed in checks.items() if not passed])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=HERE / "results")
    parser.add_argument("--data", type=Path, default=HERE.parent / "lesson-04/data/feathers.zip")
    parser.add_argument("--status", type=Path, default=HERE.parent / "lesson-04/data/status.parquet")
    args = parser.parse_args()
    verify(args.results, args.data, args.status)


if __name__ == "__main__":
    main()
