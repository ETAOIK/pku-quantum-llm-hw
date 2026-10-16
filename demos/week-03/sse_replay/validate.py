"""Check reconstructed books against the supplied, second-labelled snapshots.

Two metrics are deliberately separate: the state after all events <= the
literal timestamp, and existence of an equal-volume/equal-depth state in that
snapshot's labelled second. The latter does not identify an exact millisecond.
"""

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .book import OrderBook
from .data import DEFAULT_DATA_DIR, available_symbols, format_time, load_symbol


def _equal(book_depth, snapshot):
    return book_depth["bids"] == snapshot["bids"] and book_depth["asks"] == snapshot["asks"]


def validate_symbol(data):
    book = OrderBook()
    events = data.events
    groups = defaultdict(list)
    for snapshot in data.snapshots:
        if 34_200_000 <= snapshot["time"] < 53_820_000:
            groups[snapshot["time"]].append(snapshot)
    cursor = 0
    matched = strict = aligned = ambiguous = 0
    unmatched = []
    for stamp, snapshots in sorted(groups.items()):
        while cursor < len(events) and events[cursor].time < stamp:
            book.apply(events[cursor])
            cursor += 1
        candidates = [0] * len(snapshots)
        matches = [0] * len(snapshots)

        def consider():
            indices = [i for i, item in enumerate(snapshots)
                       if book.cum_volume == item["volume"]]
            if indices:
                depth = book.depth()
                for index in indices:
                    candidates[index] += 1
                    if _equal(depth, snapshots[index]):
                        matches[index] += 1

        # The earlier state can persist into this second. Also retain every
        # boundary inside a shared millisecond: the snapshot has no BizIndex.
        consider()
        while cursor < len(events) and events[cursor].time <= stamp:
            book.apply(events[cursor])
            cursor += 1
            consider()
        literal_depth = book.depth()
        strict += sum(book.cum_volume == item["volume"] and _equal(literal_depth, item)
                      for item in snapshots)
        while cursor < len(events) and events[cursor].time < stamp + 1000:
            book.apply(events[cursor])
            cursor += 1
            consider()
        for index, item in enumerate(snapshots):
            aligned += candidates[index] > 0
            matched += matches[index] > 0
            ambiguous += matches[index] > 1
            if matches[index] == 0 and len(unmatched) < 8:
                unmatched.append({"time": format_time(stamp),
                                  "snapshot_volume": item["volume"],
                                  "equal_volume_candidates": candidates[index]})
    while cursor < len(events):
        book.apply(events[cursor])
        cursor += 1
    last = data.snapshots[-1]
    total = sum(len(items) for items in groups.values())
    return {
        "symbol": data.symbol, "events": len(events),
        "snapshots": len(data.snapshots), "checked_snapshots": total,
        "same_second_volume_aligned": aligned, "same_second_depth_matched": matched,
        "same_second_multiple_matching_boundaries": ambiguous,
        "literal_timestamp_matched": strict,
        "ratio": matched / total if total else None,
        "literal_ratio": strict / total if total else None,
        "auction_volume": book.cum_volume, "snapshot_auction_volume": last["volume"],
        "auction_volume_equal": book.cum_volume == last["volume"],
        "turnover_difference_fen": book.cum_turnover - last["turnover"],
        "after_volume": book.after_volume, "snapshot_after_volume": last["after_volume"],
        "after_volume_equal": book.after_volume == last["after_volume"],
        "after_turnover_difference_fen": book.after_turnover - last["after_turnover"],
        "remaining_orders": len(book.orders),
        "negative_remaining_orders": sum(order.qty < 0 for order in book.orders.values()),
        "diagnostics": dict(book.diagnostics), "unmatched_examples": unmatched,
    }


def make_report(symbols=None, data_dir=None):
    directory = Path(data_dir or DEFAULT_DATA_DIR)
    symbols = symbols or available_symbols(directory)
    results = []
    for symbol in symbols:
        result = validate_symbol(load_symbol(symbol, directory))
        results.append(result)
        print(f"{symbol}: {result['same_second_depth_matched']}/{result['checked_snapshots']} "
              f"同秒深度匹配; 字面时刻 {result['literal_timestamp_matched']}; "
              f"日终量一致={result['auction_volume_equal']}", flush=True)
    total = sum(item["checked_snapshots"] for item in results)
    matched = sum(item["same_second_depth_matched"] for item in results)
    unknown = sum(item["diagnostics"].get("missing_passive_order", 0) +
                  item["diagnostics"].get("missing_auction_order", 0) for item in results)
    overdraw = sum(item["diagnostics"].get("quantity_overdraw", 0) for item in results)
    failures = sum(not item["auction_volume_equal"] or not item["after_volume_equal"]
                   for item in results)
    hashes = {}
    for path in sorted(directory.glob("*_20260923.parquet")):
        with path.open("rb") as handle:
            hashes[path.name] = hashlib.file_digest(handle, "sha256").hexdigest()
    return {
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "data_date": "2026-09-23", "source_sha256": hashes,
        "method": {
            "scope": "09:30–14:57前，包括午间；盘后仅核对成交累计量",
            "literal": "处理Time<=快照Time的全部逐笔事件，再比较累计量与十档",
            "same_second": "在快照标注秒内，搜索同累计成交股数且十档相等的事件边界；保留该秒开始前延续的状态",
            "limitation": "同秒存在性匹配不证明快照的精确毫秒或唯一逐笔序号；原始秒标签及事件排序仍有信息边界",
            "snapshot_repairs": False,
            "turnover": "逐笔价乘股数为分；快照整数元转分，日终允许50分舍入差",
        },
        "summary": {
            "status": "complete", "symbols_checked": len(results),
            "matched": matched, "total": total, "ratio": matched / total if total else None,
            "literal_matched": sum(item["literal_timestamp_matched"] for item in results),
            "multiple_matching_boundaries": sum(item["same_second_multiple_matching_boundaries"]
                                                for item in results),
            "unknown_passive": unknown, "negative": overdraw,
            "end_volume_failures": failures,
            "description": "秒级快照：同秒、同累计量的十档存在性校验；不代表精确毫秒验证",
        },
        "symbols": results,
    }


def main():
    parser = argparse.ArgumentParser(description="对原始十档快照校验历史订单簿")
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).parent / "reports" / "validation.json")
    args = parser.parse_args()
    report = make_report(args.symbols, args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.output)
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
