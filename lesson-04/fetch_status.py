"""Fetch dated BaoStock ST/trading flags; never infer historical ST from prices."""
import argparse
import csv
import json
import socket
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from data import load_data, sha256


FIELDS = "date,code,preclose,close,tradestatus,isST"
CLIENT = None


def fetch_one(task):
    global CLIENT
    symbol, directory, start, end, client_path = task
    path = Path(directory) / f"{symbol}.csv"
    if path.exists():
        return {"symbol": symbol, "cached": True}
    if client_path:
        sys.path.append(client_path)
    socket.setdefaulttimeout(15)
    import baostock as bs
    try:
        if CLIENT is None:
            result = bs.login()
            if result.error_code != "0":
                raise RuntimeError(result.error_msg)
            CLIENT = bs
        code = symbol[-2:].lower() + "." + symbol[:6]
        query = bs.query_history_k_data_plus(code, FIELDS, start_date=start, end_date=end,
                                            frequency="d", adjustflag="3")
        if query.error_code != "0":
            raise RuntimeError(query.error_msg)
        rows = []
        while query.next():
            rows.append(query.get_row_data())
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(FIELDS.split(","))
            writer.writerows(rows)
        return {"symbol": symbol, "rows": len(rows)}
    except Exception as error:
        CLIENT = None
        return {"symbol": symbol, "error": str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--client-path", default="")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    directory = args.output / "status-cache"
    directory.mkdir(exist_ok=True)
    panels = load_data(args.data)
    close = panels["close"].loc["2024-12-01":"2026-09-30"]
    symbols = close.columns[close.notna().any()].tolist()
    tasks = [(s, str(directory), "2024-12-01", "2026-09-30", args.client_path) for s in symbols]
    outcomes = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(fetch_one, task) for task in tasks]
        for i, future in enumerate(as_completed(futures), 1):
            outcomes.append(future.result())
            if i % 100 == 0 or i == len(futures):
                print(json.dumps({"completed": i, "total": len(futures),
                                  "errors": sum("error" in o for o in outcomes)}, ensure_ascii=False), flush=True)
    frames = []
    for symbol in symbols:
        path = directory / f"{symbol}.csv"
        if path.exists():
            frame = pd.read_csv(path, dtype={"code": str, "isST": str, "tradestatus": str})
            frame["symbol"] = symbol
            frames.append(frame)
    status = pd.concat(frames, ignore_index=True)
    status["date"] = pd.to_datetime(status.date)
    status.to_parquet(args.output / "status.parquet", index=False)
    manifest = {"provider": "BaoStock", "query": "query_history_k_data_plus", "fields": FIELDS,
                "start": "2024-12-01", "end": "2026-09-30", "adjustflag": "3",
                "source_documentation": "https://pypi.org/project/baostock/",
                "fetched_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                "archive_sha256": panels["source"]["sha256"], "status_sha256": sha256(args.output / "status.parquet"),
                "requested_symbols": len(symbols), "rows": len(status),
                "st_rows": int((status.isST == "1").sum()), "errors": [o for o in outcomes if "error" in o]}
    (args.output / "status-source.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in manifest.items() if k != "errors"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
