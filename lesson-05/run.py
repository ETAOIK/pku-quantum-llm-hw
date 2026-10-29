"""Reproducible batch diagnostics for lesson 04's factors and negative controls."""
import argparse
import json
import platform
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from shared import FOURTH, CATALOG, factor_score, load_context, sha256
from factor import HERE, DEFAULTS, analyze, save_result, validate_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=FOURTH / "data/feathers.zip")
    parser.add_argument("--status", type=Path, default=FOURTH / "data/status.parquet")
    parser.add_argument("--output", type=Path, default=HERE / "results")
    args = parser.parse_args()
    status = args.status if args.status.exists() else None
    panels, market, config = load_context(args.data, status)
    dates = market["dates"]
    settings = validate_settings(DEFAULTS, dates)
    args.output.mkdir(parents=True, exist_ok=True)
    comparisons = []
    for factor, name in CATALOG.items():
        if factor == "custom":
            continue
        print(f"评价 {factor}", flush=True)
        selected = {**settings, "factor": factor, "name": name, "formula": None, "condition": "True",
                    "source_sha256": panels["source"]["sha256"], "historical_status": bool(status),
                    "status_sha256": sha256(status) if status else None}
        score, selected_market = factor_score(selected, panels, market)
        result = analyze(score, selected_market, selected)
        save_result(args.output / "factors" / factor, result, selected)
        comparisons.append(result["summary"].assign(factor=factor, name=name))
    comparison = pd.concat(comparisons, ignore_index=True)
    comparison.to_csv(args.output / "comparison.csv", index=False, float_format="%.10g")
    positive = comparison[comparison.factor == "low_vol_60"].sort_values("horizon")
    negative = comparison[comparison.factor == "negative_low_vol_60"].sort_values("horizon")
    checks = {"source_unchanged": sha256(args.data) == panels["source"]["sha256"],
              "constant_ic_undefined": bool(comparison.loc[comparison.factor == "constant_control", "rank_ic_mean"].isna().all()),
              "constant_groups_not_fabricated": bool(comparison.loc[comparison.factor == "constant_control", "group_valid_days"].eq(0).all()),
              "opposite_direction_ic": bool(np.allclose(positive.rank_ic_mean, -negative.rank_ic_mean, atol=1e-8)),
              "all_candidates_saved": len(comparison) == (len(CATALOG) - 1) * len(settings["horizons"])}
    run = {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
           "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
           "source_sha256": panels["source"]["sha256"], "status_sha256": sha256(status) if status else None,
           "universe_config": config, "mode": "retrospective-exploration", "checks": checks,
           "code_sha256": {str(p.relative_to(HERE.parent)): sha256(p) for p in [*HERE.glob("*.py"), *[FOURTH / name for name in ("data.py", "signals.py", "formula.py", "engine.py", "course.py")]]}}
    (args.output / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    if not all(checks.values()):
        raise RuntimeError(f"完整性检查失败：{checks}")
    print(json.dumps(checks, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
