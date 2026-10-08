"""Cache public single-contract daily bars; never use continuous futures."""
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

HERE = Path(__file__).resolve().parent
URL = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V21052021_4_12=/InnerFuturesNewService.getDailyKLine"
MONTHS = {"RB": (1, 5, 10), "AG": (6, 12), "AU": (6, 12)}


def main():
    data = HERE / "data"
    data.mkdir(exist_ok=True)
    lock_path = HERE / "data-lock.json"
    previous = json.loads(lock_path.read_text()) if lock_path.exists() else None
    entries = []
    for year in range(2020, 2027):
        for product, months in MONTHS.items():
            for month in months:
                symbol = f"{product}{year % 100:02d}{month:02d}"
                path = data / f"{symbol}.json"
                if not path.exists():
                    r = requests.get(URL, params={"symbol": symbol, "type": "2021_04_12"}, timeout=20)
                    r.raise_for_status()
                    rows = json.loads(r.text.split("=(", 1)[1].split(");", 1)[0])
                    if not rows or not all(set("dohlcvps") <= set(row) for row in rows):
                        raise ValueError(f"Missing/unexpected data: {symbol}")
                    path.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n")
                    time.sleep(0.15)
                rows = json.loads(path.read_text())
                entry = {"symbol": symbol, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "rows": len(rows), "first": rows[0]["d"], "last": rows[-1]["d"]}
                entries.append(entry)
                print(symbol, len(rows), rows[0]["d"], rows[-1]["d"], flush=True)
    if previous:
        if previous["contracts"] != entries:
            raise ValueError("Data changed from locked snapshot; do not overwrite an existing experiment")
    else:
        lock_path.write_text(json.dumps({
            "downloaded_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "source": "Sina Finance / InnerFuturesNewService.getDailyKLine",
            "url": URL, "params": {"symbol": "<single-contract>", "type": "2021_04_12"},
            "reference": "https://github.com/akfamily/akshare/blob/main/akshare/futures/futures_zh_sina.py",
            "evaluation_start": "2020-01-01", "evaluation_end": "2025-12-31",
            "contracts": entries}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
