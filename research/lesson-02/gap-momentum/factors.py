"""All features known by t close; compute separately within each real contract."""
import numpy as np
import pandas as pd

DESCRIPTIONS = {
    "gap_raw": "log(O_t/C_{t-1})",
    "gap_atr": "(O_t-C_{t-1}) / ATR20_{t-1}",
    "gap_vol": "gap_raw / std20(log close returns)_{t-1}",
    "gap_breakout": "signed distance of O_t outside [L_{t-1},H_{t-1}] / ATR20_{t-1}",
    "gap_trend5": "gap_raw if gap and previous 5-bar close momentum agree, else 0",
    "gap_trend20": "gap_raw if gap and previous 20-bar close momentum agree, else 0",
    "gap_volume": "gap_raw * clip(V_t / mean20(V)_{t-1},0,3)",
    "gap_oi": "gap_raw if hold_t > hold_{t-1}, else 0",
    "gap_confirm": "gap_raw if gap and log(C_t/O_t) agree, else 0",
    "gap_retained": "gap_raw * clip(sign(gap)*(C_t-C_{t-1})/abs(O_t-C_{t-1}),0,2)",
    "gap_unfilled": "gap_raw if L_t>C_{t-1} for up gap or H_t<C_{t-1} for down gap, else 0",
    "gap_close_strength": "gap_raw * max(0,sign(gap)*(2*(C_t-L_t)/(H_t-L_t)-1))",
    "gap_sum3": "sum of latest 3 gap_raw values",
    "gap_sum5": "sum of latest 5 gap_raw values",
    "gap_acceleration": "gap_raw-previous mean5(gap_raw), only if same direction as current gap",
    "gap_compression": "gap_atr * clip(ATR20_{t-1}/ATR5_{t-1},0.5,2)",
}


def compute(bars):
    o, h, l, c = (bars[key] for key in ("open", "high", "low", "close"))
    prev = c.shift(1)
    gap = np.log(o / prev)
    sign = np.sign(gap)
    tr = pd.concat([h-l, (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    atr = tr.rolling(20).mean().shift(1).replace(0, np.nan)
    atr5 = tr.rolling(5).mean().shift(1).replace(0, np.nan)
    vol = np.log(c / prev).rolling(20).std().shift(1).replace(0, np.nan)
    breakout = (o-h.shift(1)).clip(lower=0) - (l.shift(1)-o).clip(lower=0)
    retention = (sign*(c-prev)/(o-prev).abs().replace(0, np.nan)).clip(0, 2)
    close_strength = (sign*(2*(c-l)/(h-l).replace(0, np.nan)-1)).clip(lower=0)
    accel = gap-gap.rolling(5).mean().shift(1)
    values = {
        "gap_raw": gap,
        "gap_atr": (o-prev)/atr,
        "gap_vol": gap/vol,
        "gap_breakout": breakout/atr,
        "gap_trend5": gap.where(sign == np.sign(np.log(prev/c.shift(6))), 0),
        "gap_trend20": gap.where(sign == np.sign(np.log(prev/c.shift(21))), 0),
        "gap_volume": gap*(bars.volume/bars.volume.rolling(20).mean().shift(1).replace(0,np.nan)).clip(0,3),
        "gap_oi": gap.where(bars.hold > bars.hold.shift(1), 0),
        "gap_confirm": gap.where(sign == np.sign(np.log(c/o)), 0),
        "gap_retained": gap*retention,
        "gap_unfilled": gap.where(((sign>0)&(l>prev))|((sign<0)&(h<prev)), 0),
        "gap_close_strength": gap*close_strength,
        "gap_sum3": gap.rolling(3).sum(),
        "gap_sum5": gap.rolling(5).sum(),
        "gap_acceleration": accel.where(np.sign(accel) == sign, 0),
        "gap_compression": (o-prev)/atr*(atr/atr5).clip(0.5,2),
    }
    return pd.DataFrame(values, index=bars.index).replace([np.inf,-np.inf],np.nan)
