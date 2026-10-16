"""Paper trading on a read-only historical book, with an independent account.

One open simulated order per security is an explicit prototype simplification.
Small orders do not change the future historical tape. Liquidity consumed by
aggressive simulated fills stays reserved until the corresponding historical
trade/cancel removes it. Passive orders join the back of the existing same-price
queue; only eligible trade flow or crossing new residual orders can fill them.
Fees, market impact and auction participation are outside this teaching model.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING

from .rules import CONTINUOUS_END, daily_limits, is_continuous, price_cage, quantity_error

if TYPE_CHECKING:
    from .book import OrderBook
    from .data import Event


@dataclass
class PaperOrder:
    order_id: int
    side: str
    price: int
    qty: int
    remaining: int
    created_time: int
    updated_time: int
    status: str = "ACTIVE"
    reject_reason: str = ""
    ahead: dict[int, int] = field(default_factory=dict)

    def snapshot(self) -> dict:
        return {
            "order_id": self.order_id, "side": self.side, "price": self.price,
            "qty": self.qty, "remaining": self.remaining,
            "filled": self.qty - self.remaining if type(self.qty) is int else 0, "status": self.status,
            "created_time": self.created_time, "updated_time": self.updated_time,
            "queue_ahead": sum(self.ahead.values()), "reject_reason": self.reject_reason,
        }


class PaperBroker:
    def __init__(self, symbol: str, cash: float = 1_000_000,
                 initial_position: int = 0, preclose: int = 0):
        initial_cash = Decimal(str(cash))
        if not initial_cash.is_finite() or initial_cash < 0:
            raise ValueError("初始资金须为有限非负数")
        if type(initial_position) is not int or initial_position < 0:
            raise ValueError("期初可卖持仓须为非负整数股")
        self.symbol = symbol
        self.preclose = preclose
        self.cash = int((initial_cash * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        self.sellable = initial_position
        self.bought_today = 0
        self.orders: list[PaperOrder] = []
        self.fills: list[dict] = []
        self.reservations: dict[int, int] = {}
        self.active: PaperOrder | None = None

    def _cash_frozen(self) -> int:
        return self.active.price * self.active.remaining if self.active and self.active.side == "B" else 0

    def _sell_frozen(self) -> int:
        return self.active.remaining if self.active and self.active.side == "S" else 0

    def _validation_error(self, side: str, price: int, qty: int, time: int,
                          book: "OrderBook") -> str:
        if side not in ("B", "S"):
            return "委托方向须为 B（买入）或 S（卖出）"
        if type(price) is not int or price <= 0:
            return "限价须为正整数分；A 股价格最小变动为 0.01 元"
        if not is_continuous(time):
            return "本原型仅在连续竞价时段接受模拟委托"
        if self.active:
            return "每只股票同时只支持一笔在途模拟委托，请先撤单"
        error = quantity_error(self.symbol, side, qty, self.sellable - self._sell_frozen())
        if error:
            return error
        limits = daily_limits(self.symbol, self.preclose)
        if limits and not limits[0] <= price <= limits[1]:
            return f"限价超出当日价格范围 {limits[0] / 100:.2f}–{limits[1] / 100:.2f} 元"
        reference = book.best("S" if side == "B" else "B") or book.best(side) or book.last_price or self.preclose
        cage = price_cage(self.symbol, side, reference)
        if cage is not None and ((side == "B" and price > cage) or (side == "S" and price < cage)):
            return f"限价超出连续竞价有效申报价格范围，{'买价上界' if side == 'B' else '卖价下界'}为 {cage / 100:.2f} 元"
        if side == "B" and price * qty > self.cash - self._cash_frozen():
            return "可用资金不足（买入按全部委托限价冻结资金）"
        return ""

    def submit(self, side: str, price: int, qty: int, time: int,
               book: "OrderBook") -> dict:
        error = self._validation_error(side, price, qty, time, book)
        order = PaperOrder(len(self.orders) + 1, side, price, qty, qty, time, time)
        self.orders.append(order)
        if error:
            order.status, order.reject_reason = "REJECTED", error
            return order.snapshot()
        self.active = order
        opposite = "S" if side == "B" else "B"
        prices = sorted({o.price for o in book.orders.values() if o.side == opposite}, reverse=side == "S")
        for level in prices:
            if (side == "B" and level > price) or (side == "S" and level < price):
                break
            for order_id, historical_qty in book.get_front_orders(opposite, level):
                available = historical_qty - self.reservations.get(order_id, 0)
                fill_qty = min(order.remaining, max(0, available))
                if fill_qty:
                    self._fill(order, level, fill_qty, time, "AGGRESSIVE")
                    self.reservations[order_id] = self.reservations.get(order_id, 0) + fill_qty
                if not order.remaining:
                    return order.snapshot()
        order.ahead = {
            order_id: available for order_id, historical_qty in book.get_front_orders(side, price)
            if (available := historical_qty - self.reservations.get(order_id, 0)) > 0
        }
        return order.snapshot()

    def cancel(self, order_id: int, time: int) -> dict:
        if not is_continuous(time):
            raise ValueError("本原型仅在连续竞价时段接受模拟撤单")
        if self.active is None or self.active.order_id != order_id:
            raise ValueError("该委托不存在或已不在途")
        order = self.active
        order.status, order.updated_time = "CANCELLED", time
        order.ahead.clear()
        self.active = None
        return order.snapshot()

    def _fill(self, order: PaperOrder, price: int, qty: int, time: int, kind: str) -> None:
        if order.side == "B":
            self.cash -= price * qty
            self.bought_today += qty
        else:
            self.cash += price * qty
            self.sellable -= qty
        order.remaining -= qty
        order.updated_time = time
        order.status = "FILLED" if order.remaining == 0 else "PARTIAL"
        self.fills.append({
            "fill_id": len(self.fills) + 1, "order_id": order.order_id,
            "side": order.side, "price": price, "qty": qty, "time": time, "kind": kind,
        })
        if order.remaining == 0:
            order.ahead.clear()
            self.active = None

    def _release_reservation(self, order_id: int, qty: int) -> int:
        overlap = min(qty, self.reservations.get(order_id, 0))
        remaining = self.reservations.get(order_id, 0) - overlap
        if remaining:
            self.reservations[order_id] = remaining
        else:
            self.reservations.pop(order_id, None)
        return overlap

    def on_clock(self, time: int) -> None:
        """End the prototype's continuous-auction orders even without tape events."""
        order = self.active
        if order and time >= CONTINUOUS_END:
            order.status, order.updated_time = "EXPIRED", CONTINUOUS_END
            order.reject_reason = "原型仅支持连续竞价，进入收盘集合竞价时结束模拟挂单"
            order.ahead.clear()
            self.active = None

    def on_event(self, event: "Event", book: "OrderBook") -> None:
        """Must run before book.apply(event), so queue quantities are pre-event."""
        self.on_clock(event.time)
        order = self.active
        if event.kind == "D":
            unused = event.qty - self._release_reservation(event.order_id, event.qty)
            if order and event.order_id in order.ahead:
                remaining = max(0, order.ahead[event.order_id] - unused)
                if remaining:
                    order.ahead[event.order_id] = remaining
                else:
                    del order.ahead[event.order_id]
            return
        if event.kind == "T":
            overlaps = {
                order_id: self._release_reservation(order_id, event.qty)
                for order_id in {event.bid_id, event.ask_id} if order_id
            }
            if order is None:
                return
            historical_id = event.bid_id if order.side == "B" else event.ask_id
            unused = max(0, event.qty - overlaps.get(historical_id, 0))
            ahead_consumed = min(unused, order.ahead.get(historical_id, 0))
            if historical_id in order.ahead:
                remaining = order.ahead[historical_id] - ahead_consumed
                if remaining:
                    order.ahead[historical_id] = remaining
                else:
                    del order.ahead[historical_id]
            eligible = event.side == ("S" if order.side == "B" else "B")
            reaches_price = event.price <= order.price if order.side == "B" else event.price >= order.price
            if eligible and reaches_price and not order.ahead and is_continuous(event.time):
                fill_qty = min(order.remaining, unused - ahead_consumed)
                if fill_qty > 0:
                    self._fill(order, order.price, fill_qty, event.time, "PASSIVE_TRADE")
        elif event.kind == "A" and order and event.side != order.side:
            crosses = event.price <= order.price if order.side == "B" else event.price >= order.price
            if crosses and not order.ahead and is_continuous(event.time):
                fill_qty = min(order.remaining, event.qty)
                if fill_qty > 0:
                    self._fill(order, order.price, fill_qty, event.time, "PASSIVE_NEW_ORDER")
                    self.reservations[event.order_id] = self.reservations.get(event.order_id, 0) + fill_qty

    def snapshot(self, last_price: int) -> dict:
        cash_frozen, sell_frozen = self._cash_frozen(), self._sell_frozen()
        position = self.sellable + self.bought_today
        market_value = position * (last_price or self.preclose)
        return {
            "account": {
                "cash_total": self.cash, "cash_available": self.cash - cash_frozen,
                "cash_frozen": cash_frozen, "position": position,
                "sellable": self.sellable - sell_frozen, "sell_frozen": sell_frozen,
                "bought_today": self.bought_today, "market_value": market_value,
                "equity": self.cash + market_value,
            },
            "orders": [order.snapshot() for order in self.orders],
            "fills": [dict(fill) for fill in self.fills],
        }
