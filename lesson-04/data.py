"""Read the seven real archive members without extracting or changing the source."""
import hashlib
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather


FIELDS = ("open", "high", "low", "close", "amt", "cumadj", "num_trades")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_data(path):
    panels, members = {}, {}
    with zipfile.ZipFile(path) as archive:
        for field in FIELDS:
            name = f"feathers/{field}.feather"
            content = archive.read(name)
            frame = feather.read_table(pa.BufferReader(content)).to_pandas()
            frame = frame.set_index("date")
            if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
                raise ValueError(f"Unsorted or duplicate dates: {field}")
            if frame.columns.has_duplicates:
                raise ValueError(f"Duplicate securities: {field}")
            if panels:
                ref = panels["open"]
                if not frame.index.equals(ref.index) or not frame.columns.equals(ref.columns):
                    raise ValueError(f"Axes differ: {field}")
            panels[field] = frame
            members[field] = {"member": name, "bytes": len(content),
                              "sha256": hashlib.sha256(content).hexdigest()}
    panels["source"] = {"archive_name": Path(path).name, "sha256": sha256(path),
                        "members": members}
    return panels


def audit_data(panels):
    close = panels["close"]
    adjusted = close * panels["cumadj"]
    raw_returns = close.pct_change(fill_method=None)
    adjusted_returns = adjusted.pct_change(fill_method=None)
    valid = close.notna()
    high, low, opening = (panels[k] for k in ("high", "low", "open"))
    inconsistent = ((high + 1e-7 < close) | (high + 1e-7 < opening)
                    | (low - 1e-7 > close) | (low - 1e-7 > opening) | (high < low))
    fields = {}
    for name in FIELDS:
        frame = panels[name]
        fields[name] = {"missing_cells": int(frame.isna().sum().sum()),
                        "nonpositive_cells": int((frame <= 0).sum().sum()),
                        "last_date_nonmissing": int(frame.iloc[-1].notna().sum()),
                        "last_covered_date": str(frame.index[frame.notna().any(axis=1)][-1].date())}
    summary = {**panels["source"], "rows": len(close), "securities": len(close.columns),
               "first_date": str(close.index[0].date()), "last_date": str(close.index[-1].date()),
               "fields": fields, "ohlc_inconsistent_cells": int(inconsistent.sum().sum()),
               "raw_abs_return_above_40pct": int((raw_returns.abs() > .4).sum().sum()),
               "adjusted_abs_return_above_40pct": int((adjusted_returns.abs() > .4).sum().sum()),
               "present_before_2025_absent_since_2025": int((valid.loc[:"2024"].any()
                                                            & ~valid.loc["2025":].any()).sum()),
               "adjustment_interpretation": "raw * cumadj; plausible from discontinuity reduction, vendor unconfirmed",
               "amount_unit": "assumed CNY from scale; vendor unconfirmed",
               "num_trades_unit": "assumed count from filename; not share volume"}
    coverage = pd.DataFrame({f"{k}_nonmissing": panels[k].notna().sum(axis=1) for k in FIELDS})
    coverage["positive_amount"] = (panels["amt"] > 0).sum(axis=1)
    return summary, coverage


def prepare(panels, config):
    close = panels["close"]
    factor = panels["cumadj"]
    adj_close = close * factor
    observed = adj_close.notna() & (panels["amt"] > 0)
    adj_close = adj_close.where(observed)
    amount20 = panels["amt"].where(panels["amt"] > 0).rolling(20, min_periods=20).mean()
    eligible = ((observed.cumsum() >= config["min_history"])
                & (observed.rolling(20, min_periods=20).sum() == 20)
                & (amount20 >= config["min_amount_20"]) & (close >= config["min_price"]))
    # No backfill. A missing last trade can never be replaced with a future price.
    marked = adj_close.ffill().fillna(0.)
    stale = np.zeros(observed.shape, dtype=np.int32)
    obs = observed.to_numpy()
    for t in range(len(stale)):
        stale[t] = np.where(obs[t], 0, (stale[t - 1] if t else 0) + 1)
    marked = marked.mask(stale >= config["stale_write_down_days"], 0.)
    adj_open = (panels["open"] * factor).where(observed)
    return {"dates": close.index, "symbols": close.columns,
            "close": adj_close, "open": adj_open.to_numpy(), "mark": marked.to_numpy(),
            "stale": stale, "amount20": amount20, "eligible": eligible.to_numpy(),
            "gap": (adj_open / adj_close.shift(1) - 1).to_numpy()}
