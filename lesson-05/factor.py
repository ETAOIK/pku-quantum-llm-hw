"""Cross-sectional diagnostics. Future prices are used only as evaluation labels."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DEFAULTS = json.loads((HERE / "protocol.json").read_text())


def validate_settings(body, dates):
    if not isinstance(body, dict):
        raise ValueError("请提交因子与评价参数")
    settings = DEFAULTS.copy()
    for key in ("start", "end"):
        try:
            date = pd.Timestamp(body.get(key, settings[key]))
            if pd.isna(date) or date.tz is not None or date != date.normalize():
                raise ValueError()
            settings[key] = str(date.date())
        except (ValueError, TypeError):
            raise ValueError("请选择有效日期") from None
    if not dates[0] <= pd.Timestamp(settings["start"]) <= pd.Timestamp(settings["end"]) <= dates[-1]:
        raise ValueError("起止日期须按顺序位于可用数据范围内")
    horizons = body.get("horizons", settings["horizons"])
    if (not isinstance(horizons, list) or not 1 <= len(horizons) <= 6
            or any(type(h) is not int or not 1 <= h <= 60 for h in horizons)):
        raise ValueError("评价周期须为 1–60 个交易日的整数列表，最多 6 个")
    settings["horizons"] = sorted(set(horizons))
    for key, low, high in (("quantiles", 2, 10), ("min_pairs", 3, 1000)):
        value = body.get(key, settings[key])
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{key} 须为 {low}–{high} 的整数")
        settings[key] = value
    if body.get("direction", 1) not in (-1, 1) or type(body.get("direction", 1)) is not int:
        raise ValueError("方向只能为 1 或 -1，且需预先指定")
    settings["direction"] = body.get("direction", 1)
    settings["preprocess"] = body.get("preprocess", settings["preprocess"])
    if settings["preprocess"] not in ("raw", "winsor_zscore"):
        raise ValueError("预处理只能选择原值或截面 1% 缩尾标准化")
    inside = dates[(dates >= settings["start"]) & (dates <= settings["end"])]
    if len(inside) < max(settings["horizons"]) + 3:
        raise ValueError("区间太短，至少需覆盖最长评价周期再加 3 个交易日")
    return settings


def transform(score, eligible, settings):
    frame = pd.DataFrame(np.where(eligible & np.isfinite(score), score, np.nan), dtype=float)
    frame *= settings["direction"]
    if settings["preprocess"] == "winsor_zscore":
        frame = frame.clip(lower=frame.quantile(.01, axis=1), upper=frame.quantile(.99, axis=1), axis=0)
        scale = frame.std(axis=1).replace(0, np.nan)
        frame = frame.sub(frame.mean(axis=1), axis=0).div(scale, axis=0)
    return frame.to_numpy()


def corr(x, y, rank=False, minimum=3):
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < minimum:
        return np.nan
    a, b = x[valid], y[valid]
    if rank:
        a, b = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    a, b = a - a.mean(), b - b.mean()
    denominator = np.sqrt((a @ a) * (b @ b))
    return float(np.clip((a @ b) / denominator, -1, 1)) if denominator > 0 else np.nan


def assign_groups(values, quantiles):
    """Do not split ties to manufacture five groups out of a constant factor."""
    groups = np.zeros(len(values), dtype=np.int8)
    valid = np.isfinite(values)
    if len(np.unique(values[valid])) < quantiles:
        return groups
    ranks = pd.Series(values[valid]).rank(method="average").to_numpy()
    labels = np.ceil(ranks * quantiles / len(ranks)).astype(np.int8)
    if len(np.unique(labels)) == quantiles:
        groups[valid] = labels
    return groups


def forward_returns(opening, dates, horizon, end):
    """At close t: enter at open t+1, exit at open t+1+h (never same-day open)."""
    result = np.full(opening.shape, np.nan)
    count = len(dates) - horizon - 1
    mature = np.zeros(len(dates), dtype=bool)
    if count <= 0:
        return result, mature
    entry, exit_ = opening[1:count + 1], opening[1 + horizon:]
    valid = np.isfinite(entry) & (entry > 0) & np.isfinite(exit_) & (exit_ > 0)
    mature[:count] = dates[1 + horizon:] <= pd.Timestamp(end)
    valid &= mature[:count, None]
    np.divide(exit_, entry, out=result[:count], where=valid)
    result[:count] -= 1
    return result, mature


def hac_interval(series, horizon):
    """Bartlett HAC on the original date grid; missing dates are not compressed."""
    values = np.asarray(series, dtype=float)
    valid = np.isfinite(values)
    n = int(valid.sum())
    if n < 30:
        return (np.nan, np.nan)
    mean = values[valid].mean()
    centered = np.where(valid, values - mean, 0.)
    lag = min(max(5, horizon), len(values) - 1)
    variance = centered @ centered
    for k in range(1, lag + 1):
        variance += 2 * (1 - k / (lag + 1)) * (centered[k:] @ centered[:-k])
    se = np.sqrt(max(0., variance)) / n
    return float(mean - 1.96 * se), float(mean + 1.96 * se)


def describe(frame, horizon, quantiles):
    mature = frame[frame.label_mature]
    ic = mature.pearson_ic.dropna()
    ric = mature.rank_ic.dropna()
    low, high = hac_interval(mature.rank_ic, horizon)
    std = ric.std()
    formed = mature.signal_count.sum()
    paired = mature.paired_count.sum()
    group_means = [mature[f"q{q}_return"].mean() for q in range(1, quantiles + 1)]
    result = {
        "horizon": horizon, "signal_days": len(frame), "mature_days": len(mature),
        "ic_days": len(ric), "pearson_ic_mean": ic.mean(), "rank_ic_mean": ric.mean(),
        "rank_ic_std": std, "rank_icir": ric.mean() / std if std > 1e-12 else np.nan,
        "rank_ic_positive_fraction": (ric > 0).mean() if len(ric) else np.nan,
        "rank_ic_ci_low": low, "rank_ic_ci_high": high,
        "factor_coverage": frame.signal_count.sum() / max(1, frame.universe_count.sum()),
        "label_coverage": paired / formed if formed else np.nan,
        "paired_samples": int(paired), "missing_labels": int(formed - paired),
        "group_valid_days": int(mature.groups_valid.sum()),
        "spread_mean": mature.spread.mean(),
        "quantile_monotonicity": corr(np.arange(1, quantiles + 1), np.array(group_means), rank=True),
        "top_turnover": frame.top_turnover.mean(), "bottom_turnover": frame.bottom_turnover.mean(),
        "rank_autocorrelation": frame.rank_autocorrelation.mean(),
    }
    if not len(ric):
        verdict = "不可评价：截面常数或配对样本不足"
    elif result["factor_coverage"] < .8 or result["label_coverage"] < .95:
        verdict = "覆盖不足：先检查缺失偏差"
    elif len(ric) < 60 or not np.isfinite(low):
        verdict = "证据不足：有效日期太少"
    elif high < 0:
        verdict = "方向相反：当前方向不支持"
    elif low <= 0:
        verdict = "证据不足：Rank IC 区间含零"
    elif result["spread_mean"] <= 0 or not np.isfinite(result["spread_mean"]):
        verdict = "结果不一致：检查分组与收益"
    else:
        verdict = "可继续研究：仍需扣费与新样本"
    result["diagnosis"] = verdict
    return result


def analyze(score, market, settings):
    dates = market["dates"]
    indices = np.flatnonzero((dates >= settings["start"]) & (dates <= settings["end"]))
    if not len(indices):
        raise ValueError("区间内没有交易日")
    eligible = market["eligible"][indices]
    values = transform(np.asarray(score)[indices], eligible, settings)
    quantiles = settings["quantiles"]
    groups = np.array([assign_groups(row, quantiles) for row in values])
    common = []
    for i, (t, row, group) in enumerate(zip(indices, values, groups)):
        valid = np.isfinite(row)
        prev = groups[i - 1] if i else None
        turnover = {}
        for q, name in ((1, "bottom_turnover"), (quantiles, "top_turnover")):
            current = group == q
            turnover[name] = (1 - np.sum(current & (prev == q)) / current.sum()
                              if i and current.any() and (prev == q).any() else np.nan)
        common.append({"date": str(dates[t].date()), "universe_count": int(eligible[i].sum()),
                       "signal_count": int(valid.sum()), "unique_scores": len(np.unique(row[valid])),
                       "groups_valid": bool(group.any()),
                       "rank_autocorrelation": corr(row, values[i - 1], rank=True) if i else np.nan,
                       **turnover})
    rows, summaries, periods, group_summary = [], [], [], []
    for h in settings["horizons"]:
        labels, mature = forward_returns(market["open"], dates, h, settings["end"])
        horizon_rows = []
        for i, t in enumerate(indices):
            x, y, group = values[i], labels[t], groups[i]
            paired = np.isfinite(x) & np.isfinite(y)
            row = {**common[i], "horizon": h, "label_mature": bool(mature[t]),
                   "entry_date": str(dates[t + 1].date()) if t + 1 < len(dates) else None,
                   "exit_date": str(dates[t + h + 1].date()) if t + h + 1 < len(dates) else None,
                   "paired_count": int(paired.sum()),
                   "pearson_ic": corr(x, y, minimum=settings["min_pairs"]),
                   "rank_ic": corr(x, y, rank=True, minimum=settings["min_pairs"])}
            for q in range(1, quantiles + 1):
                selected = group == q
                complete = selected & paired
                row[f"q{q}_count"] = int(selected.sum())
                row[f"q{q}_paired"] = int(complete.sum())
                row[f"q{q}_return"] = float(y[complete].mean()) if complete.any() else np.nan
            row["spread"] = row[f"q{quantiles}_return"] - row["q1_return"]
            horizon_rows.append(row)
        frame = pd.DataFrame(horizon_rows)
        summary = describe(frame, h, quantiles)
        summaries.append(summary)
        for q in range(1, quantiles + 1):
            subset = frame[frame.label_mature]
            count = subset[f"q{q}_count"].sum()
            paired = subset[f"q{q}_paired"].sum()
            group_summary.append({"horizon": h, "quantile": q, "mean_return": subset[f"q{q}_return"].mean(),
                                  "formed_samples": int(count), "paired_samples": int(paired),
                                  "label_coverage": paired / count if count else np.nan})
        for frequency, width in (("year", 4), ("month", 7)):
            for period, part in frame.groupby(frame.date.str[:width], sort=True):
                periods.append({"frequency": frequency, "period": period, **describe(part, h, quantiles)})
        rows.extend(horizon_rows)
    return {"summary": pd.DataFrame(summaries), "daily": pd.DataFrame(rows),
            "periods": pd.DataFrame(periods), "quantiles": pd.DataFrame(group_summary)}


def save_result(directory, result, settings):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for key, frame in result.items():
        frame.to_csv(directory / ("daily.csv.gz" if key == "daily" else f"{key}.csv"), index=False,
                     float_format="%.10g")
    (directory / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
