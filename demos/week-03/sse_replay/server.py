"""Local, single-account teaching application. Run with python -m sse_replay.server."""

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
from threading import RLock

from flask import Flask, Response, jsonify, render_template, request

from .data import DEFAULT_DATA_DIR, available_symbols
from .session import ReplaySession


def validated_report(directory, report_file):
    pending = {"summary": {"status": "pending", "description": "当前数据尚无经过指纹核对的校验报告"}}
    if not report_file.exists():
        return pending
    report = json.loads(report_file.read_text())
    expected = report.get("source_sha256", {})
    names = {f"{kind}_20260923.parquet" for kind in ("ord", "exe", "snp")}
    if set(expected) != names:
        return pending
    for name in sorted(names):
        path = directory / name
        if not path.is_file():
            return pending
        with path.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != expected[name]:
            return pending
    return report


def create_app(data_dir=None):
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    directory = Path(data_dir or os.environ.get("SSE_DATA_DIR", DEFAULT_DATA_DIR))
    lock = RLock()
    current = {"session": None, "report": None}
    report_file = Path(__file__).parent / "reports" / "validation.json"

    def report_data():
        # Original inputs are immutable for the lifetime of this local process.
        if current["report"] is None:
            current["report"] = validated_report(directory, report_file)
        return current["report"]

    def validation():
        return report_data()["summary"]

    def session():
        if current["session"] is None:
            current["session"] = ReplaySession(data_dir=directory)
        return current["session"]

    def response(message=None):
        return jsonify(ok=True, state=session().state(validation()), message=message)

    def payload():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("请求须包含 JSON 对象")
        return body

    @app.errorhandler(ValueError)
    def invalid_input(error):
        return jsonify(ok=False, error=str(error)), 400

    @app.errorhandler(FileNotFoundError)
    def missing_data(error):
        return jsonify(ok=False, error="没有找到原始 Parquet 数据，请按运行说明配置 SSE_DATA_DIR"), 503

    @app.get("/")
    def home():
        return render_template("index.html")

    @app.get("/api/catalog")
    def catalog():
        return jsonify(ok=True, symbols=available_symbols(directory), date="2026-09-23")

    @app.get("/api/state")
    def state():
        with lock:
            return response()

    @app.post("/api/reset")
    def reset():
        body = payload()
        with lock:
            new = ReplaySession(body.get("symbol", "601688"), body.get("cash", 1_000_000),
                                body.get("initial_position", 0), directory)
            current["session"] = new
            return response("已恢复开盘订单簿，并重置模拟账户")

    @app.post("/api/advance")
    def advance():
        body = payload()
        with lock:
            session().advance(seconds=body.get("seconds"), target=body.get("target"))
            return response()

    @app.post("/api/order")
    def order():
        body = payload()
        with lock:
            order = session().submit(body.get("side", ""), body.get("price"), body.get("qty"))
            message = order.get("reject_reason") or "模拟委托已处理"
            return response(message)

    @app.post("/api/cancel")
    def cancel():
        body = payload()
        with lock:
            session().cancel(body.get("order_id"))
            return response("委托未成交部分已撤销，冻结资源已释放")

    @app.get("/api/validation")
    def report():
        with lock:
            return jsonify(report_data())

    @app.get("/api/export")
    def export():
        kind = request.args.get("kind", "fills")
        if kind not in {"orders", "fills", "depth"}:
            raise ValueError("导出类型应为 orders、fills 或 depth")
        with lock:
            data = session().state(validation())
            if kind == "depth":
                rows = [{"symbol": data["symbol"], "time": data["clock"],
                         "side": side, "level": index, **level}
                        for side, levels in data["book"].items()
                        for index, level in enumerate(levels, 1)]
                columns = ["symbol", "time", "side", "level", "price", "volume"]
            else:
                rows = data[kind]
                columns = (list(rows[0]) if rows else
                           ["order_id", "side", "price", "qty", "time"])
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
            filename = f"{data['symbol']}-{kind}-20260923.csv"
            return Response("\ufeff" + buffer.getvalue(), mimetype="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    return app


def main():
    parser = argparse.ArgumentParser(description="上交所历史回放与模拟交易原型")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    print(f"本地界面：http://127.0.0.1:{args.port}")
    create_app(args.data_dir).run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
