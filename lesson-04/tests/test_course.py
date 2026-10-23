import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from course import simulate


def fixture():
    dates = pd.bdate_range("2025-01-01", periods=7)
    price = pd.DataFrame(10., index=dates, columns=["A", "B"])
    market = dict(dates=dates, symbols=price.columns, open=price.to_numpy(), mark=price.to_numpy(),
                  amount20=price * 1e6, eligible=np.ones((7, 2), dtype=bool),
                  gap=np.zeros((7, 2)), stale=np.zeros((7, 2), dtype=int))
    config = dict(test=[str(dates[1].date()), str(dates[-1].date())], initial_cash=1000.,
                  rebalance_every=5, liquidation_days=2, top_n=1, invested_fraction=.95,
                  participation=.1, slippage_bps=0., commission_bps=1., open_gap_guard=.048)
    score = np.tile([2., 1.], (7, 1))
    state = np.tile([3, 1], (7, 1))
    return market, score, state, config, price / 10


def test_first_open_historical_st_costs_and_final_cash():
    market, score, state, config, factors = fixture()
    daily, orders, _, _ = simulate(market, score, state, config, factors, events=[])
    buys = orders[(orders.side == "BUY") & (orders.notional > 0)]
    assert buys.symbol.tolist() == ["B"]
    assert buys.date.iloc[0] == market["dates"][1]
    assert buys.signal_date.iloc[0] == market["dates"][0]
    assert daily.holdings.iloc[-1] == 0
    assert np.isclose(daily.cash.iloc[-1], 1000 - 950 * .0001 - 950 * .0006)
    assert np.allclose(daily.equity, daily.cash + daily.exposure * daily.equity)


def test_new_st_exits_before_next_rebalance_and_capacity_never_forced():
    market, score, state, config, factors = fixture()
    state[3:, 1] = 3
    daily, orders, _, _ = simulate(market, score, state, config, factors, events=[])
    assert daily.holdings.iloc[2] == 0
    market["amount20"][:] = 1000
    config["participation"] = .1
    _, orders, _, _ = simulate(market, score, state, config, factors, events=[])
    assert orders.filled_reference_notional.max() <= 100
