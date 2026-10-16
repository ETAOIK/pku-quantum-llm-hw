"""Reconstruct the published resting order book, without snapshot repairs."""

from collections import Counter
from dataclasses import dataclass

from .data import Event


@dataclass(slots=True)
class RestingOrder:
    order_id: int
    side: str
    price: int
    qty: int
    seq: int


class OrderBook:
    def __init__(self):
        self.orders: dict[int, RestingOrder] = {}
        self._levels: dict[str, dict[int, int]] = {"B": {}, "S": {}}
        self.last_price = 0
        self.cum_volume = 0
        self.cum_turnover = 0
        self.after_volume = 0
        self.after_turnover = 0
        self.status = ""
        self.last_time = 0
        self.last_seq = 0
        self.diagnostics = Counter()

    def _change_level(self, side: str, price: int, delta: int):
        levels = self._levels[side]
        qty = levels.get(price, 0) + delta
        if qty:
            levels[price] = qty
        else:
            levels.pop(price, None)

    def _reduce(self, order_id: int, qty: int, missing_key: str):
        order = self.orders.get(order_id)
        if order is None:
            self.diagnostics[missing_key] += 1
            return
        if qty > order.qty:
            self.diagnostics["quantity_overdraw"] += 1
        removed = min(qty, order.qty)
        self._change_level(order.side, order.price, -removed)
        order.qty -= removed
        if order.qty == 0:
            del self.orders[order_id]

    def apply(self, event: Event) -> None:
        self.diagnostics["events"] += 1
        self.last_time = event.time
        self.last_seq = event.seq
        if event.kind == "S":
            self.status = event.status
            self.diagnostics["stage_messages"] += 1
            return
        if event.channel == 2301:
            if event.kind == "T":
                self.after_volume += event.qty
                self.after_turnover += event.price * event.qty
                self.diagnostics["after_trades"] += 1
            return
        if event.kind == "A":
            if event.side not in {"B", "S"} or event.price <= 0 or event.qty <= 0:
                self.diagnostics["invalid_add"] += 1
                return
            if event.order_id in self.orders:
                self.diagnostics["duplicate_add"] += 1
                prior = self.orders.pop(event.order_id)
                self._change_level(prior.side, prior.price, -prior.qty)
            self.orders[event.order_id] = RestingOrder(
                event.order_id, event.side, event.price, event.qty, event.seq)
            self._change_level(event.side, event.price, event.qty)
        elif event.kind == "D":
            self._reduce(event.order_id, event.qty, "unknown_cancel")
        elif event.kind == "T":
            self.last_price = event.price
            self.cum_volume += event.qty
            self.cum_turnover += event.price * event.qty
            if event.side == "B" and event.ask_id not in self.orders:
                self.diagnostics["missing_passive_order"] += 1
            elif event.side == "S" and event.bid_id not in self.orders:
                self.diagnostics["missing_passive_order"] += 1
            elif not event.side and (event.bid_id not in self.orders or
                                     event.ask_id not in self.orders):
                self.diagnostics["missing_auction_order"] += 1
            # Fully aggressive orders may have no A message; A messages appearing
            # after a T already contain only the unexecuted remaining quantity.
            self._reduce(event.bid_id, event.qty, "unpublished_trade_bid")
            self._reduce(event.ask_id, event.qty, "unpublished_trade_ask")
        else:
            self.diagnostics["unknown_event"] += 1

    def depth(self, levels: int = 10) -> dict:
        bids = sorted(self._levels["B"], reverse=True)[:levels]
        asks = sorted(self._levels["S"])[:levels]
        return {"bids": [[price, self._levels["B"][price]] for price in bids],
                "asks": [[price, self._levels["S"][price]] for price in asks]}

    def best(self, side: str) -> int | None:
        levels = self._levels[side]
        if not levels:
            return None
        return max(levels) if side == "B" else min(levels)

    def get_front_orders(self, side: str, price: int) -> list[tuple[int, int]]:
        queue = [order for order in self.orders.values()
                 if order.side == side and order.price == price]
        queue.sort(key=lambda order: order.seq)
        return [(order.order_id, order.qty) for order in queue]
