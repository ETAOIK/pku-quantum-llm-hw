"""One deterministic market replay and its independent paper account."""

from bisect import bisect_right
from decimal import Decimal, InvalidOperation

from .book import OrderBook
from .broker import PaperBroker
from .data import format_time, load_symbol, parse_time
from .rules import phase


START = parse_time("09:30:00")
END = parse_time("15:30:00")


def money_fen(value) -> int:
    if isinstance(value, bool):
        raise ValueError("金额或价格必须是数字")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
            raise ValueError("金额或价格须非负，且最多保留两位小数")
        return int(amount * 100)
    except (InvalidOperation, TypeError):
        raise ValueError("金额或价格必须是有效数字") from None


def integer(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label}必须是整数")
    return value


class ReplaySession:
    def __init__(self, symbol="601688", cash=1_000_000, initial_position=0,
                 data_dir=None):
        initial_position = integer(initial_position, "期初持仓")
        if initial_position < 0:
            raise ValueError("期初持仓不能为负")
        initial_cash = money_fen(cash)
        self.data = load_symbol(symbol, data_dir)
        self.book = OrderBook()
        self._candles = []
        self._times = [event.time for event in self.data.events]
        self.cursor = bisect_right(self._times, START)
        for event in self.data.events[:self.cursor]:
            self.book.apply(event)
            self._update_candle(event)
        self.clock = START
        self.preclose = next(snapshot["preclose"] for snapshot in self.data.snapshots
                             if snapshot["preclose"] > 0)
        self.initial_equity = initial_cash + initial_position * self.preclose
        self.broker = PaperBroker(symbol, initial_cash / 100, initial_position,
                                  self.preclose)

    def _update_candle(self, event):
        if event.kind != "T" or event.channel == 2301:
            return
        minute = event.time // 60_000 * 60_000
        if not self._candles or self._candles[-1]["time_ms"] != minute:
            self._candles.append({
                "time_ms": minute, "open": event.price, "high": event.price,
                "low": event.price, "close": event.price, "volume": event.qty,
            })
            return
        candle = self._candles[-1]
        candle["high"] = max(candle["high"], event.price)
        candle["low"] = min(candle["low"], event.price)
        candle["close"] = event.price
        candle["volume"] += event.qty

    def advance(self, *, seconds=None, target=None):
        if (seconds is None) == (target is None):
            raise ValueError("请选择推进秒数或目标时间其中一种")
        if target is not None:
            destination = parse_time(str(target))
        else:
            seconds = integer(seconds, "推进秒数")
            if seconds <= 0:
                raise ValueError("推进秒数必须大于零")
            destination = min(self.clock + seconds * 1000, END)
        if destination < self.clock:
            raise ValueError("回放不能倒退；请重置账户后重新推进")
        if destination > END:
            raise ValueError("回放终点为 15:30:00")
        stop = bisect_right(self._times, destination)
        for event in self.data.events[self.cursor:stop]:
            self.broker.on_event(event, self.book)
            self.book.apply(event)
            self._update_candle(event)
        self.broker.on_clock(destination)
        self.cursor = stop
        self.clock = destination

    def submit(self, side, price, qty):
        qty = integer(qty, "委托数量")
        return self.broker.submit(str(side), money_fen(price), qty,
                                  self.clock, self.book)

    def cancel(self, order_id):
        return self.broker.cancel(integer(order_id, "委托号"), self.clock)

    def state(self, validation=None):
        depth = self.book.depth()
        result = self.broker.snapshot(self.book.last_price or self.preclose)
        account = dict(result["account"])
        for key in ("cash_total", "cash_available", "cash_frozen", "market_value", "equity"):
            account[key] /= 100
        account["pnl"] = account["equity"] - self.initial_equity / 100
        orders = []
        for order in result["orders"]:
            order = dict(order)
            order["price"] /= 100
            order["created_time"] = format_time(order["created_time"])
            order["updated_time"] = format_time(order["updated_time"])
            orders.append(order)
        fills = []
        for fill in result["fills"]:
            fill = dict(fill)
            fill["price"] /= 100
            fill["time"] = format_time(fill["time"])
            fills.append(fill)
        bid = self.book.best("B")
        ask = self.book.best("S")
        bid_volume = sum(level[1] for level in depth["bids"])
        ask_volume = sum(level[1] for level in depth["asks"])
        total = bid_volume + ask_volume
        return {
            "symbol": self.data.symbol, "date": "2026-09-23",
            "clock": format_time(self.clock), "time_ms": self.clock,
            "phase": phase(self.clock), "processed_events": self.cursor,
            "total_events": len(self.data.events),
            "last_price": (self.book.last_price or self.preclose) / 100,
            "preclose": self.preclose / 100,
            "book": {side: [{"price": price / 100, "volume": qty}
                            for price, qty in depth[side]] for side in ("bids", "asks")},
            "candles": [{"time": format_time(candle["time_ms"]),
                         "time_ms": candle["time_ms"],
                         **{key: candle[key] / 100 for key in ("open", "high", "low", "close")},
                         "volume": candle["volume"]} for candle in self._candles],
            "account": account, "orders": orders, "fills": fills,
            "metrics": {
                "spread": (ask - bid) / 100 if bid is not None and ask is not None else None,
                "mid": (ask + bid) / 200 if bid is not None and ask is not None else None,
                "imbalance": (bid_volume - ask_volume) / total if total else None,
                "total_bid_volume": bid_volume, "total_ask_volume": ask_volume,
            },
            "diagnostics": {
                **dict(self.book.diagnostics),
                "auction_volume": self.book.cum_volume,
                "auction_turnover": self.book.cum_turnover / 100,
                "after_volume": self.book.after_volume,
                "after_turnover": self.book.after_turnover / 100,
            },
            "validation": validation or {"status": "pending", "description": "校验报告生成中"},
        }
