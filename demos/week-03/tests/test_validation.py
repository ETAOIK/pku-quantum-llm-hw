import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sse_replay.data import Event, SymbolData, parse_time
from sse_replay.validate import validate_symbol


def snapshot(clock, bids, asks):
    return {"time": parse_time(clock), "bids": bids, "asks": asks,
            "volume": 0, "turnover": 0, "after_volume": 0, "after_turnover": 0}


def resting_bid():
    return Event(parse_time("09:29:00"), 1, 1002, "A", "B",
                 order_id=1, price=1000, qty=300)


def test_second_label_match_does_not_claim_the_literal_timestamp_matches():
    # The snapshot is labelled 10:00:00; its ask first appears at .500.
    data = SymbolData("601688", [resting_bid(),
        Event(parse_time("10:00:00.500"), 2, 1002, "A", "S",
              order_id=2, price=1001, qty=200),
    ], [snapshot("10:00:00", [[1000, 300]], [[1001, 200]])])
    result = validate_symbol(data)
    assert result["same_second_depth_matched"] == 1
    assert result["literal_timestamp_matched"] == 0


def test_next_second_event_cannot_repair_the_previous_seconds_snapshot():
    data = SymbolData("601688", [resting_bid(),
        Event(parse_time("10:00:01"), 2, 1002, "A", "S",
              order_id=2, price=1001, qty=200),
    ], [snapshot("10:00:00", [[1000, 300]], [[1001, 200]]),
        snapshot("10:00:01", [[1000, 300]], [[1001, 200]])])
    result = validate_symbol(data)
    assert result["checked_snapshots"] == 2
    assert result["same_second_depth_matched"] == 1
    assert result["literal_timestamp_matched"] == 1
    assert result["unmatched_examples"][0]["time"] == "10:00:00.000"


def test_shared_millisecond_retains_intermediate_event_boundary():
    # Two cancellations share Time; the snapshot has no sequence field.
    data = SymbolData("601688", [resting_bid(),
        Event(parse_time("10:00:00"), 2, 1002, "D", "B", order_id=1, qty=100),
        Event(parse_time("10:00:00"), 3, 1002, "D", "B", order_id=1, qty=100),
    ], [snapshot("10:00:00", [[1000, 200]], [])])
    result = validate_symbol(data)
    assert result["same_second_depth_matched"] == 1
    assert result["literal_timestamp_matched"] == 0
    assert result["same_second_multiple_matching_boundaries"] == 0
