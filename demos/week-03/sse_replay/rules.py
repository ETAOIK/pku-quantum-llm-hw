"""Verified SSE rules for ordinary A-share continuous-auction limit orders.

Source: SSE Trading Rules (2026 revision), effective 2026-07-06;
checked 2026-10-09, sections 3.1.4, 3.3.8-17, 6.6-8.
https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml
Prices and monetary values use integer fen; times are milliseconds since midnight.
The supplied established stocks use the ordinary 10% / STAR 20% daily bands.
IPO exceptions and special security statuses require additional instrument metadata.
"""

MORNING_START = (9 * 60 + 30) * 60_000
MORNING_END = (11 * 60 + 30) * 60_000
AFTERNOON_START = 13 * 60 * 60_000
CONTINUOUS_END = (14 * 60 + 57) * 60_000


def phase(time: int) -> str:
    if time < (9 * 60 + 15) * 60_000:
        return "开盘前"
    if time < (9 * 60 + 25) * 60_000:
        return "开盘集合竞价"
    if time < MORNING_START:
        return "开盘等待"
    if time < MORNING_END:
        return "连续竞价"
    if time < AFTERNOON_START:
        return "午间休市"
    if time < CONTINUOUS_END:
        return "连续竞价"
    if time < 15 * 60 * 60_000:
        return "收盘集合竞价"
    if time < (15 * 60 + 5) * 60_000:
        return "盘后等待"
    if time < (15 * 60 + 30) * 60_000:
        return "盘后固定价格"
    return "已收盘"


def is_continuous(time: int) -> bool:
    return MORNING_START <= time < MORNING_END or AFTERNOON_START <= time < CONTINUOUS_END


def is_star(symbol: str) -> bool:
    return symbol.startswith("688")


def round_price(value: int, percent: int) -> int:
    """Positive prices, rounded half up to the 0.01-yuan tick (rule 3.3.17)."""
    return (value * percent + 50) // 100


def daily_limits(symbol: str, preclose: int) -> tuple[int, int] | None:
    if preclose <= 0:
        return None
    percent = 20 if is_star(symbol) else 10
    return max(1, min(preclose - 1, round_price(preclose, 100 - percent))), max(
        preclose + 1, round_price(preclose, 100 + percent)
    )


def price_cage(symbol: str, side: str, reference: int) -> int | None:
    if reference <= 0:
        return None
    if side == "B":
        upper = max(reference + 1, round_price(reference, 102))
        return upper if is_star(symbol) else max(upper, reference + 10)
    lower = min(reference - 1, round_price(reference, 98))
    return max(1, lower if is_star(symbol) else min(lower, reference - 10))


def quantity_error(symbol: str, side: str, qty: int, sellable: int) -> str:
    if type(qty) is not int or qty <= 0:
        return "数量必须为正整数股"
    star = is_star(symbol)
    maximum = 100_000 if star else 1_000_000
    if qty > maximum:
        return f"单笔限价委托最多 {maximum:,} 股"
    if side == "B":
        if star and qty < 200:
            return "科创板买入限价委托至少 200 股"
        if not star and qty % 100:
            return "主板买入数量须为 100 股的整数倍"
    else:
        if qty > sellable:
            return "可卖持仓不足；当日买入股票不能当日卖出"
        if star and qty < 200 and qty != sellable:
            return "科创板不足 200 股的余额须一次卖出"
        if not star and qty % 100 not in (0, sellable % 100):
            return "主板余股须一次卖出，不能拆分不足 100 股的余额"
    return ""
