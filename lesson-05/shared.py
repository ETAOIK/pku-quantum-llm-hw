"""Reuse lesson 04 without copying or changing its source and frozen results."""
import json
import sys
from pathlib import Path

FOURTH = Path(__file__).resolve().parents[1] / "lesson-04"
sys.path.insert(0, str(FOURTH))

from data import load_data, prepare, sha256
from signals import score_signal
from formula import evaluate, validate_expression
from server import LABELS, Workbench, create_app as backtest_app

CATALOG = {**LABELS, "custom": "自定义因子公式", "constant_control": "常数对照（不可评价）", "noise_control": "随机对照（固定种子）",
           "negative_low_vol_60": "60 日低波动的反向对照"}


def factor_score(settings, panels, market):
    import numpy as np
    name = settings["factor"]
    if name == "custom":
        score = evaluate(settings["formula"], panels, market)
    elif name == "constant_control":
        score = np.ones_like(market["eligible"], dtype=float)
    elif name == "noise_control":
        score = np.random.default_rng(20261023).normal(size=market["eligible"].shape)
    elif name == "negative_low_vol_60":
        score = -score_signal("low_vol_60", panels, market)
    else:
        score = score_signal(name, panels, market)
    condition = evaluate(settings.get("condition", "True"), panels, market, condition=True)
    return score, {**market, "eligible": market["eligible"] & condition}


def load_context(data_path, status_path):
    config = json.loads((FOURTH / ("assignment/protocol.json" if status_path else "protocol.json")).read_text())
    panels = load_data(data_path)
    expected = json.loads((FOURTH / "results/data_audit.json").read_text())["sha256"]
    if panels["source"]["sha256"] != expected:
        raise ValueError("行情指纹与第四课不一致，请先审计新数据")
    market = prepare(panels, config)
    if status_path:
        from course import read_state
        state = read_state(status_path, market["dates"], market["symbols"])
        market["eligible"] &= state == 1
    return panels, market, config
