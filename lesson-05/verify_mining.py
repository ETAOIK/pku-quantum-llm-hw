"""Independently reconstruct cash and verify saved research boundaries."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "research-20261029"


def main():
    protocol = json.loads((OUTPUT / "protocol.json").read_text())
    summary = pd.read_csv(OUTPUT / "factors.csv")
    checks = {"270_summary_rows": len(summary) == 270, "30_factors": summary.factor.nunique() == 30}
    first_followup = min(p.stat().st_mtime_ns for p in (OUTPUT / "evaluations/followup").glob("*/settings.json"))
    checks["selection_file_precedes_followup"] = (OUTPUT / "selection.json").stat().st_mtime_ns < first_followup
    for stage, (start, end) in protocol["splits"].items():
        okay = True
        for path in (OUTPUT / "evaluations" / stage).glob("*/daily.csv.gz"):
            daily = pd.read_csv(path)
            mature = daily[daily.label_mature]
            okay &= bool((mature.exit_date <= end).all() and (mature.entry_date > mature.date).all()
                         and (daily.loc[~daily.label_mature, "paired_count"] == 0).all())
        checks[f"{stage}_label_boundaries"] = okay
    ledger_errors = []
    for settings in sorted((OUTPUT / "backtests").glob("*/*/settings.json")):
        directory = settings.parent
        config = json.loads(settings.read_text())["config"]
        daily = pd.read_csv(directory / "daily.csv").set_index("date")
        orders = pd.read_csv(directory / "orders.csv.gz", usecols=["date", "side", "notional", "fee", "signal_date"])
        flow = np.where(orders.side == "SELL", orders.notional, -orders.notional) - orders.fee
        daily_flow = pd.Series(flow.to_numpy(), index=orders.date).groupby(level=0).sum().reindex(daily.index, fill_value=0.)
        rebuilt = config["initial_cash"] + daily_flow.cumsum()
        relative_error = float(np.max(np.abs(rebuilt - daily.cash)) / config["initial_cash"])
        fees = orders.notional * (config["commission_bps"] + np.where(orders.side == "SELL", 5., 0.)) / 10000
        fee_relative_error = float(np.max(np.abs(fees - orders.fee) / np.maximum(1., fees)))
        recomputed_returns = daily.equity / daily.equity.shift(1).fillna(config["initial_cash"]) - 1
        return_error = float(np.max(np.abs(recomputed_returns - daily["return"])))
        name = "/".join(directory.parts[-2:])
        checks[f"ledger_{name}"] = bool(relative_error < 1e-7 and fee_relative_error < 1e-7
                                         and return_error < 1e-10 and (orders.signal_date < orders.date).all()
                                         and daily.cash.min() >= -1e-6)
        ledger_errors.append({"run": name, "relative_cash_reconstruction_error": relative_error,
                              "max_fee_relative_error": fee_relative_error, "max_daily_return_error": return_error})
    payload = {"checked_on": "2026-10-29 Asia/Shanghai", "checks": checks, "ledger_errors": ledger_errors,
               "precision_note": "Compressed order amounts use 10 significant digits; cash comparison tolerance is 1e-7 of initial cash",
               "passed": all(checks.values())}
    (OUTPUT / "verification.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if not payload["passed"]:
        raise RuntimeError(checks)
    print(f"Verified {len(checks)} checks and {len(ledger_errors)} cash ledgers")


if __name__ == "__main__":
    main()
