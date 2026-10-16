import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sse_replay.book import OrderBook
from sse_replay.data import Event


def event(kind, side="", order_id=0, qty=0, price=1848, seq=1, **kwargs):
    return Event(34_200_000, seq, 1002, kind, side, order_id,
                 price=price, qty=qty, **kwargs)


def test_aggressive_trade_before_remaining_order_does_not_double_subtract():
    book = OrderBook()
    book.apply(event("A", "B", 10, 11700))
    book.apply(event("T", "S", qty=11700, bid_id=10, ask_id=326077, seq=2))
    book.apply(event("A", "S", 326077, 35500, seq=3))
    assert book.orders[326077].qty == 35500
    assert book.depth() == {"bids": [], "asks": [[1848, 35500]]}
    assert book.cum_volume == 11700
    assert book.cum_turnover == 1848 * 11700
    assert book.diagnostics["unpublished_trade_ask"] == 1
    assert book.diagnostics["quantity_overdraw"] == 0
    assert book.diagnostics["missing_passive_order"] == 0


def test_price_levels_partial_trade_partial_cancel_and_fifo():
    book = OrderBook()
    book.apply(event("A", "S", 2, 300, seq=2))
    book.apply(event("A", "S", 1, 200, seq=1))
    book.apply(event("A", "S", 3, 400, price=1849, seq=3))
    assert book.get_front_orders("S", 1848) == [(1, 200), (2, 300)]
    assert book.best("S") == 1848
    book.apply(event("T", qty=100, bid_id=999, ask_id=1))
    book.apply(event("D", "S", 2, 200))
    assert book.depth() == {"bids": [], "asks": [[1848, 200], [1849, 400]]}
    book.apply(event("D", "S", 1, 100))
    book.apply(event("D", "S", 2, 100))
    assert book.best("S") == 1849
    assert book.get_front_orders("S", 1848) == []


def test_stage_and_after_hours_do_not_change_auction_order_book():
    book = OrderBook()
    book.apply(event("A", "B", 10, 100))
    book.apply(event("A", "S", 20, 100, price=1849))
    original = book.depth()
    book.apply(event("S", status="V", price=0))
    book.apply(Event(54_300_000, 20, 2301, "T", "B", bid_id=10,
                     ask_id=20, price=1848, qty=100))
    assert book.depth() == original
    assert book.status == "V"
    assert book.cum_volume == 0
    assert book.after_volume == 100
    assert book.after_turnover == 184800


def test_unknown_reference_is_recorded_and_overdraw_never_creates_negative_qty():
    book = OrderBook()
    book.apply(event("D", "B", 99, 100))
    book.apply(event("A", "B", 10, 100))
    book.apply(event("T", qty=200, bid_id=10, ask_id=20))
    assert book.orders == {}
    assert book.depth() == {"bids": [], "asks": []}
    assert book.diagnostics["unknown_cancel"] == 1
    assert book.diagnostics["quantity_overdraw"] == 1


def test_missing_passive_and_auction_orders_are_distinguished_from_active_orders():
    book = OrderBook()
    book.apply(event("T", "B", qty=100, bid_id=1, ask_id=2))
    book.apply(event("T", qty=100, bid_id=3, ask_id=4))
    assert book.diagnostics["missing_passive_order"] == 1
    assert book.diagnostics["missing_auction_order"] == 1


def test_bids_are_descending_and_asks_ascending():
    book = OrderBook()
    for order_id, side, price in [(1, "B", 1847), (2, "B", 1846),
                                   (3, "S", 1849), (4, "S", 1848)]:
        book.apply(event("A", side, order_id, 100, price=price))
    assert book.best("B") == 1847
    assert book.depth(1) == {"bids": [[1847, 100]], "asks": [[1848, 100]]}
