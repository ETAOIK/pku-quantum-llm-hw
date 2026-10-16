import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sse_replay.data import Event, SymbolData, parse_time
from sse_replay.session import ReplaySession, money_fen
from sse_replay.server import create_app, validated_report


def sample_data():
    def event(clock, seq, kind, side, **kwargs):
        return Event(parse_time(clock), seq, 1002, kind, side, **kwargs)
    return SymbolData("601688", [
        event("09:24:00", 1, "A", "B", order_id=1, price=1841, qty=400),
        event("09:24:00", 2, "A", "S", order_id=2, price=1842, qty=500),
        event("09:25:00", 3, "T", "S", bid_id=1, ask_id=3, price=1841, qty=100),
        event("09:30:01", 4, "A", "B", order_id=4, price=1840, qty=200),
        event("09:30:02", 5, "T", "B", bid_id=5, ask_id=2, price=1842, qty=100),
        event("09:30:03", 6, "D", "B", order_id=4, qty=200),
    ], [{"time": parse_time("09:25:00"), "preclose": 1847,
         "bids": [[1841, 300]], "asks": [[1842, 500]], "volume": 100,
         "turnover": 184100, "after_volume": 0, "after_turnover": 0}])


@pytest.fixture
def data():
    with patch("sse_replay.session.load_symbol", return_value=sample_data()), \
            patch("sse_replay.server.validated_report", return_value={"summary": {"status": "pending"}}):
        yield


def test_reset_preserves_opening_book_without_using_future(data):
    session = ReplaySession()
    assert session.cursor == 3
    assert session.book.depth() == {"bids": [[1841, 300]], "asks": [[1842, 500]]}
    session.advance(seconds=1)
    assert session.book.depth()["bids"] == [[1841, 300], [1840, 200]]
    session.advance(target="09:30:02")
    assert session.book.depth()["asks"] == [[1842, 400]]


def test_replay_is_deterministic_and_cannot_rewind(data):
    a, b = ReplaySession(), ReplaySession()
    a.advance(seconds=3)
    b.advance(target="09:30:03")
    assert a.state() == b.state()
    with pytest.raises(ValueError, match="不能倒退"):
        a.advance(target="09:30:02")


@pytest.mark.parametrize("value", [True, "nan", "inf", -1, "18.421", None])
def test_invalid_money(value):
    with pytest.raises(ValueError):
        money_fen(value)


def test_api_order_changes_account_and_export_is_actual_result(data):
    client = create_app().test_client()
    initial = client.get("/api/state").get_json()["state"]
    assert initial["account"]["equity"] == 1_000_000
    result = client.post("/api/order", json={"side": "B", "price": 18.48, "qty": 100})
    assert result.status_code == 200
    state = result.get_json()["state"]
    assert state["fills"][0]["price"] == 18.42
    assert state["account"]["cash_total"] == 998_158
    assert state["account"]["bought_today"] == 100
    assert state["account"]["sellable"] == 0
    # Paper consumption is separate; it never corrupts the reference book.
    assert state["book"]["asks"][0]["volume"] == 500
    csv = client.get("/api/export?kind=fills")
    assert csv.status_code == 200 and "18.42" in csv.get_data(as_text=True)
    invalid = client.post("/api/order", json={"side": "B", "price": 18.42, "qty": 100.5})
    assert invalid.status_code == 400
    assert client.get("/api/state").get_json()["state"]["account"] == state["account"]


def test_failed_reset_does_not_destroy_existing_account(data):
    client = create_app().test_client()
    before = client.get("/api/state").get_json()["state"]
    result = client.post("/api/reset", json={"symbol": "601688", "cash": -1})
    assert result.status_code == 400
    assert client.get("/api/state").get_json()["state"] == before


def test_validation_report_is_bound_to_source_contents(tmp_path):
    hashes = {}
    for kind in ("ord", "exe", "snp"):
        path = tmp_path / f"{kind}_20260923.parquet"
        path.write_bytes(kind.encode())
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"summary": {"status": "complete"}, "source_sha256": hashes}))
    assert validated_report(tmp_path, report_path)["summary"]["status"] == "complete"
    (tmp_path / "ord_20260923.parquet").write_bytes(b"different source")
    assert validated_report(tmp_path, report_path)["summary"]["status"] == "pending"


def test_other_data_directory_does_not_reuse_built_in_validation(tmp_path):
    result = create_app(tmp_path).test_client().get("/api/validation")
    assert result.status_code == 200
    assert result.get_json()["summary"]["status"] == "pending"


@pytest.mark.parametrize("side,price,frozen_key,frozen_value", [
    ("B", 18.40, "cash_frozen", 1840),
    ("S", 18.43, "sell_frozen", 100),
])
def test_clock_boundary_expires_order_without_a_historical_event(data, side, price,
                                                               frozen_key, frozen_value):
    session = ReplaySession(initial_position=100)
    session.advance(target="14:56:00")
    session.submit(side, price, 100)
    assert session.state()["account"][frozen_key] == frozen_value
    before_depth = session.book.depth()
    before_events, before_cursor = session.book.diagnostics["events"], session.cursor
    session.advance(target="14:57:00")
    state = session.state()
    assert state["orders"][0]["status"] == "EXPIRED"
    assert state["orders"][0]["updated_time"] == "14:57:00.000"
    assert state["account"]["cash_frozen"] == 0
    assert state["account"]["sell_frozen"] == 0
    assert state["account"]["sellable"] == 100
    assert not state["fills"]
    assert session.book.depth() == before_depth
    assert session.cursor == before_cursor
    assert session.book.diagnostics["events"] == before_events
