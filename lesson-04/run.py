"""Reproduce data audit, frozen validation selection and one final test."""
import argparse
import json
import platform
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
import numpy as np
import pandas as pd
import pyarrow

from data import audit_data, load_data, prepare, sha256
from engine import backtest, block_bootstrap, metrics
from report import write_report
from signals import make_targets, score_signal


HERE = Path(__file__).resolve().parent


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Original feathers.zip (read-only)")
    parser.add_argument("--output", type=Path, default=HERE, help="Report root; default lesson-04")
    args = parser.parse_args()
    output = args.output.resolve()
    results = output / "results"
    results.mkdir(parents=True, exist_ok=True)
    config = json.loads((HERE / "protocol.json").read_text())
    dump(results / "protocol.json", config)
    print("Loading and hashing the original archive", flush=True)
    panels = load_data(args.data)
    audit, coverage = audit_data(panels)
    dump(results / "data_audit.json", audit)
    coverage.to_csv(results / "data_coverage.csv", index_label="date")
    market = prepare(panels, config)
    score_rows, candidate_curves = [], {}
    for name in config["candidate_ids"]:
        print(f"Development / validation: {name}", flush=True)
        score = score_signal(name, panels, market)
        target = make_targets(score, market, config)
        for stage in ("train", "validation"):
            curve, _, _ = backtest(market, target, *config[stage], config)
            candidate_curves[f"{stage}__{name}"] = curve["return"]
            score_rows.append({"candidate": name, "stage": stage,
                               **metrics(curve, config["initial_cash"])})
    comparison = pd.DataFrame(score_rows)
    comparison.to_csv(results / "candidates.csv", index=False)
    pd.DataFrame(candidate_curves).to_csv(results / "candidate_daily_returns.csv", index_label="date")
    validation = comparison[comparison.stage == "validation"]
    chosen = validation.sort_values(["sharpe", "candidate"], ascending=[False, True]).iloc[0]
    selected = str(chosen.candidate)
    selection = {"selected": selected, "rule": config["selection"],
                 "validation_sharpe": float(chosen.sharpe), "test_seen_for_selection": False,
                 "candidate_count": len(config["candidate_ids"]),
                 "protocol_sha256": sha256(HERE / "protocol.json"),
                 "candidates_sha256": sha256(results / "candidates.csv")}
    # Persist the decision before running any final test or sensitivity analysis.
    dump(results / "selection.json", selection)
    print(f"Frozen selection: {selected}. Starting final test.", flush=True)
    target = make_targets(score_signal(selected, panels, market), market, config)
    broad = make_targets(score_signal("equal_weight", panels, market), market, config, broad=True)
    liquid = make_targets(score_signal("high_amount_20", panels, market), market, config)
    runs = {"selected": (target, 1.), "equal_weight": (broad, 1.),
            "liquid_50": (liquid, 1.), "selected_stress": (target, config["stress_cost_multiplier"]),
            "equal_weight_stress": (broad, config["stress_cost_multiplier"]),
            "selected_zero_cost": (target, 0.)}
    final, curves, checks = {}, {}, {}
    for name, (weights, cost) in runs.items():
        curve, orders, holdings = backtest(market, weights, *config["test"], config,
                                           cost_multiplier=cost, keep_orders=True)
        curves[name] = curve
        final[name] = metrics(curve, config["initial_cash"])
        curve.to_csv(results / f"test_{name}_daily.csv", index_label="date")
        # Detailed primary ledgers; sensitivities retain full daily accounting.
        if name in ("selected", "equal_weight", "liquid_50"):
            suffix = ".csv.gz" if name == "equal_weight" else ".csv"
            compression = {"method": "gzip", "mtime": 0} if name == "equal_weight" else None
            orders.to_csv(results / f"test_{name}_orders{suffix}", index=False, compression=compression)
            holdings.to_csv(results / f"test_{name}_holdings{suffix}", index=False, compression=compression)
        checks[f"{name}_cash_nonnegative"] = bool((curve.cash >= -1e-6).all())
        checks[f"{name}_no_same_day_signal"] = bool((orders.signal_date < orders.date).all())
        checks[f"{name}_cash_reconciles"] = bool(np.isclose(
            config["initial_cash"] + orders.loc[orders.side == "SELL", "notional"].sum()
            - orders.loc[orders.side == "BUY", "notional"].sum() - orders.fee.sum(), curve.cash.iloc[-1]))
        checks[f"{name}_positions_reconcile"] = bool(np.isclose(
            curve.equity.iloc[-1], curve.cash.iloc[-1] + holdings.loc[holdings.date == curve.index[-1], "value"].sum()))
        checks[f"{name}_orders_within_requests"] = bool((orders.filled_reference_notional <= orders.requested_reference_notional + 1e-6).all())
        checks[f"{name}_holdings_nonnegative"] = bool((holdings.adjusted_units >= -1e-8).all())
    excess = curves["selected"]["return"] - curves["equal_weight"]["return"]
    bootstrap = block_bootstrap(excess, config["bootstrap_block_days"], config["bootstrap_repetitions"], config["bootstrap_seed"])
    final["selected"]["benchmark_excess_total_return"] = final["selected"]["total_return"] - final["equal_weight"]["total_return"]
    stress_excess = final["selected_stress"]["total_return"] - final["equal_weight_stress"]["total_return"]
    gates = {"test_sharpe_above_0_5": final["selected"]["sharpe"] > .5,
             "test_cagr_positive": final["selected"]["cagr"] > 0,
             "beats_equal_weight": final["selected"]["benchmark_excess_total_return"] > 0,
             "bootstrap_lower_positive": bootstrap["ci_95"][0] > 0,
             "double_cost_excess_positive": stress_excess > 0}
    checks["source_archive_unchanged"] = sha256(args.data) == audit["sha256"]
    checks["selected_by_validation_only"] = selected == validation.sort_values(["sharpe", "candidate"], ascending=[False, True]).iloc[0].candidate
    checks["ohlc_consistent"] = audit["ohlc_inconsistent_cells"] == 0
    checks["test_separate_from_validation"] = config["validation"][1] < config["test"][0]
    checks["all_passed"] = all(checks.values())
    if not checks["all_passed"]:
        dump(results / "integrity_checks.json", checks)
        raise AssertionError("Integrity check failed; inspect results/integrity_checks.json")
    summary = {"selected": selected, "metrics": final, "bootstrap": bootstrap,
               "gate_conditions": gates, "statistical_gate_passed": all(gates.values()),
               "deployment_validated": False,
               "boundary": "Conditional daily-bar synthetic-account research; vendor metadata, corporate-action ledger and opening fills not validated"}
    dump(results / "summary.json", summary)
    dump(results / "integrity_checks.json", checks)
    yearly = []
    for name, curve in curves.items():
        for year, group in curve.groupby(curve.index.year):
            yearly.append({"run": name, "year": int(year), "return": float((1 + group["return"]).prod() - 1)})
    pd.DataFrame(yearly).to_csv(results / "test_yearly_returns.csv", index=False)
    environment = {"python": platform.python_version(), "numpy": np.__version__,
                   "pandas": pd.__version__, "pyarrow": pyarrow.__version__, "matplotlib": matplotlib.__version__}
    source_hashes = {p.name: sha256(p) for p in sorted(HERE.glob("*.py"))}
    dump(results / "run_manifest.json", {"completed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                                       "source": audit["sha256"], "protocol": selection["protocol_sha256"],
                                       "code_sha256": source_hashes, "environment": environment,
                                       "command": "python3 lesson-04/run.py --data /path/to/feathers.zip",
                                       "test_policy": "Only selected candidate, predeclared benchmarks and fixed sensitivities evaluated"})
    write_report(output, config, audit, comparison, curves, summary, checks, coverage)
    print(json.dumps({"selected": selected, "test": final["selected"],
                      "statistical_gate_passed": summary["statistical_gate_passed"],
                      "checks_passed": len(checks) - 1}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
