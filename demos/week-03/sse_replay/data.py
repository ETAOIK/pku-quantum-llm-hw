"""Read the provided Parquet files without changing or copying the sources.

Prices are integer fen and quantities are shares. SSE A messages report the
remaining resting quantity after any immediately executed trades.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[4] / "第三周实践课" / "sse50_20260923"


@dataclass(frozen=True, slots=True)
class Event:
    time: int
    seq: int
    channel: int
    kind: str
    side: str
    order_id: int = 0
    bid_id: int = 0
    ask_id: int = 0
    price: int = 0
    qty: int = 0
    status: str = ""


@dataclass(slots=True)
class SymbolData:
    symbol: str
    events: list[Event]
    snapshots: list[dict]


def parse_time(value: str) -> int:
    """Convert HH:MM:SS[.mmm] to milliseconds after midnight."""
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?", value)
    if not match:
        raise ValueError("时间格式应为 HH:MM:SS 或 HH:MM:SS.mmm")
    hour, minute, second = map(int, match.group(1, 2, 3))
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("时间超出一天的范围")
    millis = int((match.group(4) or "0").ljust(3, "0"))
    return ((hour * 60 + minute) * 60 + second) * 1000 + millis


def format_time(milliseconds: int) -> str:
    hour, remainder = divmod(milliseconds, 3_600_000)
    minute, remainder = divmod(remainder, 60_000)
    second, millis = divmod(remainder, 1000)
    return f"{hour:02}:{minute:02}:{second:02}.{millis:03}"


def _exchange_time(value: int) -> int:
    hour, remainder = divmod(int(value), 10_000_000)
    minute, remainder = divmod(remainder, 100_000)
    second, millis = divmod(remainder, 1000)
    return ((hour * 60 + minute) * 60 + second) * 1000 + millis


def _fen(value: float) -> int:
    # The input float32 encodes prices such as 18.47999954; tick size is 0.01.
    return int(round(float(value) * 100))


def _directory(data_dir) -> str:
    return str(Path(data_dir or DEFAULT_DATA_DIR).expanduser().resolve())


def _read_symbol(path: Path, symbol: str, columns=None) -> pa.Table:
    # The files interleave symbols in every row group. Filtering bounded batches
    # avoids allocating all other symbols' projected columns in parallel.
    file = pq.ParquetFile(path)
    requested = list(columns) if columns is not None else file.schema_arrow.names
    read_columns = list(dict.fromkeys([*requested, "Symbol"]))
    pieces = []
    for batch in file.iter_batches(batch_size=131_072, columns=read_columns,
                                   use_threads=False):
        selected = batch.filter(pc.equal(batch.column("Symbol"), int(symbol)))
        if selected.num_rows:
            pieces.append(selected)
    schema = pa.schema([file.schema_arrow.field(name) for name in read_columns])
    return pa.Table.from_batches(pieces, schema=schema).select(requested)


@lru_cache(maxsize=4)
def _symbols(directory: str) -> tuple[str, ...]:
    path = Path(directory) / "ord_20260923.parquet"
    values = set()
    for batch in pq.ParquetFile(path).iter_batches(columns=["Symbol"], use_threads=False):
        values.update(batch.column("Symbol").unique().to_pylist())
    return tuple(sorted(f"{int(value):06}" for value in values))


def available_symbols(data_dir=None) -> list[str]:
    return list(_symbols(_directory(data_dir)))


def load_symbol(symbol: str, data_dir=None) -> SymbolData:
    value = str(symbol)
    if not re.fullmatch(r"\d{6}", value):
        raise ValueError("证券代码应为六位数字")
    return _load_symbol(value, _directory(data_dir))


@lru_cache(maxsize=2)
def _load_symbol(symbol: str, directory: str) -> SymbolData:
    source = Path(directory)
    order_columns = ["Time", "BizIndex", "Channel", "OrderKind", "FunctionCode",
                     "OrderOriNo", "Price", "Volume"]
    trade_columns = ["Time", "BizIndex", "Channel", "BSFlag", "BidOrder",
                     "AskOrder", "Price", "Volume"]
    orders = _read_symbol(source / "ord_20260923.parquet", symbol, order_columns)
    trades = _read_symbol(source / "exe_20260923.parquet", symbol, trade_columns)
    snapshots = _read_symbol(source / "snp_20260923.parquet", symbol)
    if not orders.num_rows or not snapshots.num_rows:
        raise ValueError(f"数据中没有证券 {symbol}")

    events = []
    order_arrays = [orders[name].to_numpy() for name in order_columns]
    for time, seq, channel, kind, function, order_id, price, qty in zip(*order_arrays):
        kind, function = chr(int(kind)), chr(int(function))
        if kind not in {"A", "D", "S"}:
            raise ValueError(f"未识别的逐笔委托类型: {kind!r}")
        events.append(Event(_exchange_time(time), int(seq), int(channel), kind,
                            function if kind != "S" else "", int(order_id),
                            price=_fen(price), qty=int(qty),
                            status=function if kind == "S" else ""))

    trade_arrays = [trades[name].to_numpy() for name in trade_columns]
    for time, seq, channel, flag, bid_id, ask_id, price, qty in zip(*trade_arrays):
        flag = chr(int(flag)) if int(flag) else ""
        events.append(Event(_exchange_time(time), int(seq), int(channel), "T",
                            flag if flag in {"B", "S"} else "", bid_id=int(bid_id),
                            ask_id=int(ask_id), price=_fen(price), qty=int(qty)))

    # BizIndex is authoritative within a channel. There is no total exchange
    # sequence across channels: this dataset has one auction channel per symbol
    # plus an independent after-hours channel. Each stream's time is monotone.
    events.sort(key=lambda event: (event.time, event.channel, event.seq))
    previous_seq = {}
    for event in events:
        if event.seq <= previous_seq.get(event.channel, -1):
            raise ValueError("同通道 BizIndex 重复，或逐笔时间与 BizIndex 顺序冲突")
        previous_seq[event.channel] = event.seq

    normalized = []
    columns = snapshots.to_pydict()
    for index in range(snapshots.num_rows):
        depth = {}
        for name, prefix in (("bids", "Bid"), ("asks", "Ask")):
            levels = []
            for level in range(1, 11):
                price = _fen(columns[f"{prefix}Price{level}"][index])
                qty = int(columns[f"{prefix}Volume{level}"][index])
                if price > 0 and qty > 0:
                    levels.append([price, qty])
            depth[name] = levels
        normalized.append({
            "time": _exchange_time(columns["Time"][index]),
            **depth,
            "last": _fen(columns["Price"][index]),
            "preclose": _fen(columns["PreClose"][index]),
            "volume": int(columns["AccVolume"][index]),
            # AccTurnover/AfterTurnover are integer yuan in the supplied files.
            "turnover": int(columns["AccTurnover"][index]) * 100,
            "after_volume": int(columns["AfterVolume"][index]),
            "after_turnover": int(columns["AfterTurnover"][index]) * 100,
        })
    normalized.sort(key=lambda snapshot: snapshot["time"])
    return SymbolData(symbol, events, normalized)
