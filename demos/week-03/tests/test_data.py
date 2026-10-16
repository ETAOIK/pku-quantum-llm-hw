import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sse_replay.data import available_symbols, format_time, load_symbol, parse_time


def test_time_roundtrip_and_fractional_seconds():
    assert parse_time("09:30:00") == 34_200_000
    assert parse_time("09:30:00.5") == 34_200_500
    assert format_time(parse_time("15:29:59.070")) == "15:29:59.070"
    for value in ["24:00:00", "09:60:00", "09:30:60", "93000000", "09:30"]:
        with pytest.raises(ValueError):
            parse_time(value)


def test_loader_preserves_preopen_sequence_original_order_id_and_units(tmp_path):
    # A timestamp alone cannot order a trade and a remaining-quantity message.
    orders = [
        {"Symbol": 601688, "Time": 93000580, "BizIndex": 4, "Channel": 1002,
         "OrderKind": 65, "FunctionCode": 83, "OrderOriNo": 326077,
         "OrderNumber": 4, "Price": 18.479999542, "Volume": 35500},
        {"Symbol": 601688, "Time": 91500020, "BizIndex": 2, "Channel": 1002,
         "OrderKind": 65, "FunctionCode": 66, "OrderOriNo": 10,
         "OrderNumber": 2, "Price": 18.479999542, "Volume": 11700},
        {"Symbol": 601688, "Time": 91500000, "BizIndex": 1, "Channel": 1002,
         "OrderKind": 83, "FunctionCode": 73, "OrderOriNo": 0,
         "OrderNumber": 1, "Price": 0.0, "Volume": 0},
    ]
    trades = [{"Symbol": 601688, "Time": 93000580, "BizIndex": 3,
               "Channel": 1002, "BSFlag": 83, "BidOrder": 10,
               "AskOrder": 326077, "Price": 18.479999542, "Volume": 11700}]
    snapshot = {"Symbol": 601688, "Time": 93002000, "Price": 18.479999542,
                "PreClose": 18.469999314, "AccVolume": 11700,
                "AccTurnover": 216216, "AfterVolume": 0, "AfterTurnover": 0}
    for prefix in ("Bid", "Ask"):
        for level in range(1, 11):
            snapshot[f"{prefix}Price{level}"] = 18.48 if level == 1 else 0.0
            snapshot[f"{prefix}Volume{level}"] = 35500 if level == 1 else 0.0
    for kind, rows in [("ord", orders), ("exe", trades), ("snp", [snapshot])]:
        pq.write_table(pa.Table.from_pylist(rows), tmp_path / f"{kind}_20260923.parquet")
    assert available_symbols(tmp_path) == ["601688"]
    data = load_symbol("601688", tmp_path)
    assert [event.kind for event in data.events] == ["S", "A", "T", "A"]
    assert data.events[1].time == parse_time("09:15:00.020")
    assert data.events[-1].order_id == 326077
    assert data.events[-1].price == 1848
    assert data.snapshots[0]["preclose"] == 1847
    assert data.snapshots[0]["turnover"] == 21621600
    assert data.snapshots[0]["asks"] == [[1848, 35500]]
    with pytest.raises(ValueError):
        load_symbol("bad", tmp_path)
    with pytest.raises(ValueError):
        load_symbol("600000", tmp_path)
