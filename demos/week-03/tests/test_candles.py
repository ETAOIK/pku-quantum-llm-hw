import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sse_replay.data import Event, SymbolData, parse_time
from sse_replay.session import ReplaySession


@pytest.fixture
def session():
    trades = [
        ("09:25:00", 1800, 100, 1002),
        ("09:25:01", 1810, 200, 1002),
        ("09:30:01", 1850, 100, 1002),
        ("09:30:02", 1840, 200, 1002),
        ("09:30:59.999", 1870, 300, 1002),
        ("09:31:00", 1860, 400, 1002),
        ("11:29:59", 1850, 500, 1002),
        ("13:00:05", 1880, 600, 1002),
        ("15:00:00", 1860, 700, 1002),
        ("15:05:00", 1860, 800, 2301),
    ]
    events = [Event(parse_time(clock), index + (index >= 3), channel, "T", "", price=price, qty=qty)
              for index, (clock, price, qty, channel) in enumerate(trades, start=1)]
    events.insert(2, Event(parse_time("09:30:00"), 3, 1002, "A", "B",
                           order_id=1, price=1830, qty=500))
    data = SymbolData("601688", events, [{"preclose": 1810}])
    with patch("sse_replay.session.load_symbol", return_value=data):
        yield ReplaySession()


def test_initial_candles_include_observed_opening_trade_without_future_data(session):
    assert session.state()["candles"] == [{
        "time": "09:25:00.000", "time_ms": parse_time("09:25:00"),
        "open": 18.0, "high": 18.1, "low": 18.0, "close": 18.1, "volume": 300,
    }]
    assert session.cursor == 3
    assert session._candles[0]["close"] == 1810  # Internal prices remain integer fen.


def test_one_minute_ohlc_and_volume_update_only_with_processed_trades(session):
    session.advance(target="09:30:02")
    candle = session.state()["candles"][-1]
    assert candle == {
        "time": "09:30:00.000", "time_ms": parse_time("09:30:00"),
        "open": 18.5, "high": 18.5, "low": 18.4, "close": 18.4, "volume": 300,
    }
    # A trade later in the same minute must not leak into high, close or volume.
    session.advance(target="09:30:59.999")
    candle = session.state()["candles"][-1]
    assert (candle["open"], candle["high"], candle["low"], candle["close"], candle["volume"]) == (
        18.5, 18.7, 18.4, 18.7, 600,
    )
    session.advance(target="09:31:00")
    assert session.state()["candles"][-1] == {
        "time": "09:31:00.000", "time_ms": parse_time("09:31:00"),
        "open": 18.6, "high": 18.6, "low": 18.6, "close": 18.6, "volume": 400,
    }


def test_midday_empty_minutes_are_not_fabricated_and_after_hours_are_excluded(session):
    session.advance(target="11:30:00")
    before_lunch = session.state()["candles"]
    session.advance(target="12:59:59")
    assert session.state()["candles"] == before_lunch
    session.advance(target="13:00:05")
    assert session.state()["candles"][-1]["time"] == "13:00:00.000"
    session.advance(target="15:00:00")
    before_after_hours = session.state()["candles"]
    session.advance(target="15:30:00")
    assert session.state()["candles"] == before_after_hours
    assert sum(candle["volume"] for candle in before_after_hours) == session.book.cum_volume
    assert session.book.after_volume == 800
    assert [candle["time"] for candle in before_after_hours] == [
        "09:25:00.000", "09:30:00.000", "09:31:00.000",
        "11:29:00.000", "13:00:00.000", "15:00:00.000",
    ]


def test_state_uses_candle_cache_and_does_not_scan_future_or_past_events(session):
    session.advance(target="09:30:02")
    expected = session.state()["candles"]

    class UnreadableEvents:
        def __len__(self):
            return 11

        def __iter__(self):
            raise AssertionError("state must use cached candles")

        def __getitem__(self, key):
            raise AssertionError("state must use cached candles")

    session.data.events = UnreadableEvents()
    assert session.state()["candles"] == expected
    # Returning JSON-ready data must not let callers mutate the aggregation cache.
    expected[-1]["high"] = 99
    assert session.state()["candles"][-1]["high"] == 18.5
