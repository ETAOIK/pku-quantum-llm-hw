import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import prepare
from engine import backtest, block_bootstrap, metrics
from signals import make_targets, score_signal


@pytest.fixture
def config():
    settings = json.loads((Path(__file__).resolve().parents[1] / "protocol.json").read_text())
    settings.update(initial_cash=1000., rebalance_every=1, participation=1., commission_bps=0.,
                    slippage_bps=0., sell_tax_bps_before_20230828=0., sell_tax_bps_from_20230828=0.,
                    min_history=1, min_amount_20=1., stale_write_down_days=20)
    return settings


def simple_market(prices):
    prices = np.asarray(prices, dtype=float).reshape(-1, 1)
    n = len(prices)
    return {"dates": pd.date_range("2025-01-01", periods=n), "symbols": pd.Index(["A"]),
            "open": prices.copy(), "mark": prices.copy(), "stale": np.zeros((n, 1)),
            "gap": np.zeros((n, 1)), "amount20": pd.DataFrame(np.full((n, 1), 1e9))}


def run(market, targets, config, **kwargs):
    return backtest(market, np.array(targets, dtype=float).reshape(-1, 1),
                    market["dates"][0], market["dates"][-1], config, keep_orders=True, **kwargs)


def test_lag_cash_ledger_and_no_same_day_resale(config):
    market = simple_market([10, 10, 12])
    curve, orders, _ = run(market, [1, 0, 0], config)
    assert curve.equity.tolist() == [1000., 1000., 1200.]
    assert curve.cash.tolist() == [1000., 0., 1200.]
    assert orders.side.tolist() == ["BUY", "SELL"]
    assert (orders.signal_date < orders.date).all()
    assert orders.date.nunique() == 2


def test_costs_and_full_investment_never_overdraw(config):
    config.update(commission_bps=10., slippage_bps=20.)
    curve, orders, _ = run(simple_market([10, 10]), [1, 0], config)
    assert curve.cash.min() >= -1e-8
    assert curve.equity.iloc[-1] == pytest.approx(1000 / (1.002 * 1.001))
    assert orders.notional.sum() + orders.fee.sum() == pytest.approx(1000)


def test_side_gap_guard_and_missing_open(config):
    market = simple_market([10, 10, 10, 10])
    market["gap"][1] = .05
    market["open"][2] = np.nan
    curve, orders, _ = run(market, [1, 1, 1, 0], config)
    assert curve.holdings.tolist() == [0, 0, 0, 1]
    assert orders.status.tolist()[:2] == ["missing_open_or_gap_guard"] * 2


def test_sell_block_preserves_units_and_no_fictitious_cash(config):
    market = simple_market([10, 10, 9])
    market["gap"][2] = -.1
    curve, orders, holdings = run(market, [1, 0, 0], config)
    assert curve.cash.iloc[-1] == 0
    assert curve.equity.iloc[-1] == 900
    assert holdings.iloc[-1].adjusted_units == 100
    assert orders.iloc[-1].notional == 0


def test_capacity_uses_previous_amount(config):
    market = simple_market([10, 10, 10])
    market["amount20"].iloc[0] = 100
    market["amount20"].iloc[1] = 1e9
    curve, orders, _ = run(market, [1, 1, 0], config)
    assert orders.iloc[0].notional == 100
    assert curve.cash.iloc[1] == 900


def test_tax_switch_date(config):
    config.update(sell_tax_bps_before_20230828=10., sell_tax_bps_from_20230828=5.)
    market = simple_market([10, 10, 10, 10, 10])
    market["dates"] = pd.date_range("2023-08-25", periods=5)
    _, orders, _ = run(market, [1, 0, 1, 0, 0], config)
    sells = orders[orders.side == "SELL"]
    assert (sells.fee / sells.notional).tolist() == pytest.approx([.001, .0005])


def panels_fixture(n=160):
    rng = np.random.default_rng(12)
    close = pd.DataFrame(10 * np.exp(np.cumsum(rng.normal(0, .01, (n, 3)), axis=0)),
                         index=pd.bdate_range("2020-01-01", periods=n), columns=["A", "B", "C"])
    return {"close": close, "open": close * .999, "high": close * 1.01, "low": close * .99,
            "cumadj": close * 0 + 1, "amt": close * 0 + 1e8, "num_trades": close * 0 + 1000}


def test_all_signals_and_targets_are_prefix_invariant(config):
    panels = panels_fixture()
    prefix = {k: v.iloc[:140].copy() for k, v in panels.items()}
    market, before = prepare(panels, config), prepare(prefix, config)
    for name in config["candidate_ids"]:
        full_score, prefix_score = score_signal(name, panels, market), score_signal(name, prefix, before)
        np.testing.assert_allclose(full_score[:140], prefix_score, equal_nan=True)
        a = make_targets(full_score, market, config)
        b = make_targets(prefix_score, before, config)
        np.testing.assert_array_equal(a[:139], b[:139])


def test_future_prices_do_not_change_earlier_ledger(config):
    market = simple_market([10, 10, 12, 12])
    altered = copy.deepcopy(market)
    altered["open"][3] = 1000
    altered["mark"][3] = 2000
    a, _, _ = run(market, [1, 1, 1, 0], config)
    b, _, _ = run(altered, [1, 1, 1, 0], config)
    pd.testing.assert_frame_equal(a.iloc[:3], b.iloc[:3])


def test_todays_close_not_used_to_size_opening_orders(config):
    market = simple_market([10, 10, 10])
    altered = copy.deepcopy(market)
    altered["mark"][1] = 1000
    _, a, _ = run(market, [1, 0, 0], config)
    _, b, _ = run(altered, [1, 0, 0], config)
    pd.testing.assert_frame_equal(a, b)


def test_opening_only_uses_previous_signal_row(config):
    market = simple_market([10, 10, 10])
    _, a, _ = run(market, [1, 0, 0], config)
    _, b, _ = run(market, [1, 1, 0], config)
    pd.testing.assert_frame_equal(a.iloc[:1], b.iloc[:1])


def test_missing_close_never_backfills_and_stale_write_down(config):
    config["stale_write_down_days"] = 2
    panels = panels_fixture(25)
    panels["close"].iloc[21:24, 0] = np.nan
    market = prepare(panels, config)
    assert market["mark"][21, 0] == market["mark"][20, 0]
    assert market["mark"][22, 0] == 0
    assert market["mark"][24, 0] > 0
    assert np.isnan(market["open"][21, 0])


def test_zero_amount_bar_not_executable(config):
    panels = panels_fixture(25)
    panels["amt"].iloc[22, 0] = 0
    market = prepare(panels, config)
    assert np.isnan(market["open"][22, 0])
    assert not market["eligible"][22, 0]


def test_split_adjustment_removes_mechanical_loss(config):
    panels = panels_fixture(25)
    for key in ("open", "close", "high", "low"):
        panels[key].iloc[22:, 0] /= 2
    panels["cumadj"].iloc[22:, 0] *= 2
    market = prepare(panels, config)
    original = prepare(panels_fixture(25), config)
    np.testing.assert_allclose(market["mark"], original["mark"])


def test_drawdown_includes_initial_capital(config):
    curve, _, _ = run(simple_market([10, 10]), [1, 0], config, cost_multiplier=1)
    curve.loc[curve.index[-1], "equity"] = 900
    assert metrics(curve, 1000)["max_drawdown"] == pytest.approx(-.1)


def test_bootstrap_is_reproducible():
    a = block_bootstrap(np.array([.001, -.002, .003] * 20), repetitions=100)
    assert a == block_bootstrap(np.array([.001, -.002, .003] * 20), repetitions=100)
    assert a["ci_95"][0] <= a["annualized_mean_excess"] <= a["ci_95"][1]


def test_invalid_targets_rejected(config):
    with pytest.raises(ValueError, match="Targets"):
        run(simple_market([10, 10]), [1.1, -1], config)
