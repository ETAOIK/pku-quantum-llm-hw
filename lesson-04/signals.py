"""Every score at t is formed only with observations dated <= t."""
import numpy as np


def score_signal(name, panels, market):
    close = market["close"]
    daily = close.pct_change(fill_method=None)
    if name.startswith("reversal_"):
        score = -close.pct_change(int(name.split("_")[1]), fill_method=None)
    elif name == "momentum_120_skip5":
        score = close.shift(5) / close.shift(120) - 1
    elif name.startswith("momentum_"):
        score = close.pct_change(int(name.split("_")[1]), fill_method=None)
    elif name.startswith("low_vol_"):
        score = -daily.rolling(int(name.split("_")[-1])).std()
    elif name in ("low_amount_20", "high_amount_20"):
        score = np.log(market["amount20"]) * (-1 if name.startswith("low") else 1)
    elif name.startswith("range_reversal_"):
        days = int(name.split("_")[-1])
        high = (panels["high"] * panels["cumadj"]).rolling(days).max()
        low = (panels["low"] * panels["cumadj"]).rolling(days).min()
        score = -(close - low) / (high - low).replace(0, np.nan)
    elif name.startswith("gap_reversal_"):
        days = int(name.split("_")[-1])
        gap = panels["open"] * panels["cumadj"] / close.shift(1) - 1
        score = -gap.rolling(days).mean()
    elif name in ("low_trade_size_20", "high_trade_size_20"):
        count = panels["num_trades"].where(panels["num_trades"] > 0)
        size = (panels["amt"] / count).rolling(20).mean()
        score = np.log(size) * (-1 if name.startswith("low") else 1)
    elif name == "reversal5_lowvol20":
        eligible = market["eligible"]
        rev = (-close.pct_change(5, fill_method=None)).where(eligible).rank(axis=1, pct=True)
        vol = (-daily.rolling(20).std()).where(eligible).rank(axis=1, pct=True)
        score = (rev + vol) / 2
    elif name == "equal_weight":
        score = close * 0
    else:
        raise ValueError(f"Unknown strategy: {name}")
    return score.to_numpy(dtype=np.float32)


def make_targets(score, market, config, broad=False):
    """Row t is the target decided AFTER the close at t, for the NEXT opening."""
    targets = np.zeros(score.shape, dtype=np.float32)
    for t in range(len(score) - 1):
        if (t + 1) % config["rebalance_every"]:
            continue
        valid = np.flatnonzero(market["eligible"][t] & np.isfinite(score[t]))
        if not broad:
            # Stable sort makes ties deterministic in original symbol order.
            valid = valid[np.argsort(-score[t, valid], kind="stable")[:config["top_n"]]]
        if len(valid):
            targets[t, valid] = config["invested_fraction"] / len(valid)
    return targets
