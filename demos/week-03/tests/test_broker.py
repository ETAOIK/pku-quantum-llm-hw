import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sse_replay.book import OrderBook
from sse_replay.broker import PaperBroker
from sse_replay.data import Event, parse_time
from sse_replay.rules import daily_limits, phase, price_cage


NOW = parse_time("10:00:00")


def event(kind, side="", order_id=0, price=1000, qty=0, seq=1, time=NOW, **kwargs):
    return Event(time, seq, 1001, kind, side, order_id, price=price, qty=qty, **kwargs)


def advance(broker, book, ev):
    broker.on_event(ev, book)
    book.apply(ev)


def book_with_spread():
    book = OrderBook()
    book.apply(event("A", "B", 1, 999, 100, 1))
    book.apply(event("A", "S", 2, 1001, 100, 2))
    return book


def test_aggressive_sweep_price_time_fifo_and_account():
    book = OrderBook()
    book.apply(event("A", "S", 2, 1000, 200, 2))
    book.apply(event("A", "S", 1, 1000, 300, 1))
    book.apply(event("A", "S", 3, 1001, 400, 3))
    broker = PaperBroker("601688", cash=10000, preclose=1000)
    order = broker.submit("B", 1001, 600, NOW, book)
    assert order["status"] == "FILLED"
    assert [(f["price"], f["qty"]) for f in broker.fills] == [(1000, 300), (1000, 200), (1001, 100)]
    assert broker.reservations == {1: 300, 2: 200, 3: 100}
    assert book.depth() == {"bids": [], "asks": [[1000, 500], [1001, 400]]}
    account = broker.snapshot(1001)["account"]
    assert account == {
        "cash_total": 399900, "cash_available": 399900, "cash_frozen": 0,
        "position": 600, "sellable": 0, "sell_frozen": 0, "bought_today": 600,
        "market_value": 600600, "equity": 1000500,
    }


def test_partial_fill_limit_freeze_price_improvement_and_cancel_release():
    book = OrderBook()
    book.apply(event("A", "S", 1, 1000, 150))
    broker = PaperBroker("601688", cash=10000, preclose=1000)
    order = broker.submit("B", 1001, 200, NOW, book)
    assert order["status"] == "PARTIAL" and order["remaining"] == 50
    account = broker.snapshot(1000)["account"]
    assert account["cash_total"] == 850000
    assert account["cash_frozen"] == 50050
    assert account["cash_available"] == 799950
    broker.cancel(order["order_id"], NOW + 1)
    account = broker.snapshot(1000)["account"]
    assert account["cash_available"] == 850000 and account["cash_frozen"] == 0


def test_consumed_liquidity_cannot_be_used_twice_and_history_retires_reservation():
    book = OrderBook()
    book.apply(event("A", "S", 1, 1000, 150))
    broker = PaperBroker("601688", preclose=1000)
    broker.submit("B", 1000, 100, NOW, book)
    second = broker.submit("B", 1000, 100, NOW, book)
    assert second["filled"] == 50 and broker.reservations == {1: 150}
    advance(broker, book, event("T", "B", ask_id=1, bid_id=9, qty=100))
    assert broker.reservations == {1: 50}
    assert book.orders[1].qty == 50
    assert second["filled"] == 50 and len(broker.fills) == 2
    broker.cancel(second["order_id"], NOW + 1)
    third = broker.submit("B", 1000, 100, NOW + 1, book)
    assert third["filled"] == 0
    advance(broker, book, event("D", "S", 1, qty=50))
    assert broker.reservations == {} and not book.orders
    assert broker.snapshot(1000)["account"]["position"] == 150


def test_passive_fifo_partial_cancel_and_later_orders():
    book = OrderBook()
    book.apply(event("A", "B", 1, 1000, 300, 1))
    book.apply(event("A", "B", 2, 1000, 200, 2))
    book.apply(event("A", "S", 9, 1002, 1000, 3))
    broker = PaperBroker("601688", preclose=1000)
    broker.submit("B", 1000, 200, NOW, book)
    assert broker.active.snapshot()["queue_ahead"] == 500
    advance(broker, book, event("A", "B", 3, 1000, 500, 4))
    advance(broker, book, event("T", "S", bid_id=1, ask_id=90, qty=300))
    assert not broker.fills and broker.active.snapshot()["queue_ahead"] == 200
    advance(broker, book, event("D", "B", 3, qty=100))
    assert broker.active.snapshot()["queue_ahead"] == 200
    advance(broker, book, event("D", "B", 2, qty=150))
    assert broker.active.snapshot()["queue_ahead"] == 50
    advance(broker, book, event("T", "S", bid_id=2, ask_id=91, qty=50))
    assert not broker.fills and broker.active.snapshot()["queue_ahead"] == 0
    advance(broker, book, event("T", "S", bid_id=3, ask_id=92, qty=80))
    assert broker.active.remaining == 120
    advance(broker, book, event("T", "S", bid_id=3, ask_id=93, qty=120))
    assert broker.active is None
    assert [(f["qty"], f["price"]) for f in broker.fills] == [(80, 1000), (120, 1000)]


def test_cancellation_does_not_fill_and_crossing_new_residual_can_fill():
    book = OrderBook()
    book.apply(event("A", "B", 1, 1000, 100))
    broker = PaperBroker("601688", preclose=1000)
    broker.submit("B", 1000, 100, NOW, book)
    advance(broker, book, event("D", "B", 1, qty=100))
    assert broker.active.remaining == 100 and not broker.fills
    advance(broker, book, event("A", "S", 2, 999, 100, 2))
    assert broker.active is None
    assert broker.fills[0]["price"] == 1000
    assert broker.fills[0]["kind"] == "PASSIVE_NEW_ORDER"
    assert broker.reservations == {2: 100}
    assert book.orders[2].qty == 100


def test_passive_improved_price_obeys_priority_and_uses_own_resting_price():
    book = OrderBook()
    book.apply(event("A", "B", 1, 1001, 100))
    book.apply(event("A", "B", 2, 999, 200, 2))
    book.apply(event("A", "S", 9, 1002, 100, 3))
    broker = PaperBroker("601688", preclose=1000)
    broker.submit("B", 1000, 100, NOW, book)
    advance(broker, book, event("T", "S", price=1001, qty=100, bid_id=1, ask_id=91))
    assert not broker.fills
    advance(broker, book, event("T", "S", price=999, qty=100, bid_id=2, ask_id=92))
    assert broker.fills[0]["price"] == 1000 and broker.active is None


def test_ineligible_trade_direction_does_not_fill_passive_buy():
    book = book_with_spread()
    broker = PaperBroker("601688", preclose=1000)
    broker.submit("B", 1000, 100, NOW, book)
    advance(broker, book, event("T", "B", price=1000, qty=100, bid_id=90, ask_id=91))
    assert not broker.fills and broker.active.remaining == 100


def test_aggressive_sell_and_sell_freeze_do_not_allow_t_plus_zero():
    book = OrderBook()
    book.apply(event("A", "B", 1, 1000, 150))
    broker = PaperBroker("601688", cash=10000, initial_position=200, preclose=1000)
    order = broker.submit("S", 999, 200, NOW, book)
    assert order["filled"] == 150
    account = broker.snapshot(1000)["account"]
    assert account["cash_total"] == 1150000
    assert account["position"] == 50 and account["sellable"] == 0 and account["sell_frozen"] == 50
    broker.cancel(order["order_id"], NOW)
    assert broker.snapshot(1000)["account"]["sellable"] == 50
    book.apply(event("A", "S", 2, 1001, 100, 2))
    broker.submit("B", 1001, 100, NOW, book)
    rejected = broker.submit("S", 1000, 100, NOW, book)
    assert rejected["status"] == "REJECTED" and "可卖持仓不足" in rejected["reject_reason"]
    account = broker.snapshot(1000)["account"]
    assert account["position"] == 150 and account["bought_today"] == 100 and account["sellable"] == 50


@pytest.mark.parametrize("side,price,qty,time,reason", [
    ("B", 1000, 50, NOW, "100 股"),
    ("B", 1000, 100.5, NOW, "正整数"),
    ("B", 1000, "100", NOW, "正整数"),
    ("B", 1000, 0, NOW, "正整数"),
    ("B", 1000.5, 100, NOW, "正整数分"),
    ("X", 1000, 100, NOW, "委托方向"),
    ("B", 1000, 100, parse_time("09:20:00"), "连续竞价"),
    ("B", 1000, 100, parse_time("12:00:00"), "连续竞价"),
    ("B", 1000, 100, parse_time("14:57:00"), "连续竞价"),
    ("B", 1101, 100, NOW, "当日价格范围"),
    ("B", 1050, 100, NOW, "有效申报价格"),
])
def test_rejected_orders_do_not_change_account(side, price, qty, time, reason):
    broker = PaperBroker("601688", preclose=1000)
    before = broker.snapshot(1000)["account"]
    order = broker.submit(side, price, qty, time, book_with_spread())
    assert order["status"] == "REJECTED" and reason in order["reject_reason"]
    assert broker.active is None and broker.snapshot(1000)["account"] == before


def test_insufficient_cash_and_one_open_order_rejections():
    broker = PaperBroker("601688", cash=999, preclose=1000)
    assert "资金不足" in broker.submit("B", 1000, 100, NOW, OrderBook())["reject_reason"]
    broker = PaperBroker("601688", preclose=1000)
    first = broker.submit("B", 1000, 100, NOW, OrderBook())
    second = broker.submit("B", 1000, 100, NOW, OrderBook())
    assert "一笔在途" in second["reject_reason"]
    assert broker.active.order_id == first["order_id"]
    with pytest.raises(ValueError):
        broker.cancel(second["order_id"], NOW)


def test_midday_retains_order_and_closing_auction_expires_simulated_order():
    broker = PaperBroker("601688", preclose=1000)
    book = OrderBook()
    broker.submit("B", 1000, 100, NOW, book)
    advance(broker, book, event("S", time=parse_time("12:00:00"), status="O"))
    assert broker.active and broker.snapshot(1000)["account"]["cash_frozen"] == 100000
    advance(broker, book, event("S", time=parse_time("14:57:00"), status="J"))
    assert broker.active is None
    assert broker.orders[0].status == "EXPIRED"
    assert broker.snapshot(1000)["account"]["cash_frozen"] == 0
    assert not broker.fills


def test_star_minimum_increment_maximum_and_odd_lot_sell():
    book = OrderBook()
    broker = PaperBroker("688981", preclose=1000)
    assert broker.submit("B", 1000, 100, NOW, book)["status"] == "REJECTED"
    assert broker.submit("B", 1000, 100001, NOW, book)["status"] == "REJECTED"
    accepted = broker.submit("B", 1000, 201, NOW, book)
    assert accepted["status"] == "ACTIVE" and accepted["qty"] == 201
    broker = PaperBroker("688981", initial_position=199, preclose=1000)
    assert broker.submit("S", 1000, 100, NOW, book)["status"] == "REJECTED"
    assert broker.submit("S", 1000, 199, NOW, book)["status"] == "ACTIVE"
    broker = PaperBroker("601688", initial_position=150, preclose=1000)
    assert broker.submit("S", 1000, 25, NOW, book)["status"] == "REJECTED"
    assert broker.submit("S", 1000, 50, NOW, book)["status"] == "ACTIVE"


def test_rules_half_up_daily_bands_and_different_price_cages():
    assert daily_limits("601688", 1005) == (905, 1106)
    assert daily_limits("688981", 1005) == (804, 1206)
    assert price_cage("601688", "B", 100) == 110
    assert price_cage("601688", "S", 100) == 90
    assert price_cage("688981", "B", 100) == 102
    assert price_cage("688981", "S", 100) == 98
    assert price_cage("688981", "B", 25) == 26
    assert phase(parse_time("09:30:00")) == "连续竞价"
    assert phase(parse_time("11:30:00")) == "午间休市"
    assert phase(parse_time("14:57:00")) == "收盘集合竞价"
