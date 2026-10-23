"""Local interactive backtesting workbench. Uses the same daily engine as run.py."""
import argparse
import io
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from flask import Flask, Response, jsonify, request, send_from_directory

from data import load_data, prepare
from engine import backtest, metrics
from formula import evaluate, validate_expression
from signals import make_targets, score_signal


HERE = Path(__file__).resolve().parent
LABELS = {
    "reversal_1": "1 日反转", "reversal_3": "3 日反转", "reversal_5": "5 日反转", "reversal_10": "10 日反转",
    "momentum_20": "20 日动量", "momentum_60": "60 日动量", "momentum_120_skip5": "120 日动量（跳过 5 日）",
    "low_vol_20": "20 日低波动", "low_vol_60": "60 日低波动", "low_amount_20": "低成交额",
    "high_amount_20": "高成交额", "range_reversal_5": "5 日区间反转", "range_reversal_20": "20 日区间反转",
    "gap_reversal_1": "1 日跳空反转", "gap_reversal_5": "5 日跳空反转", "low_trade_size_20": "低平均每笔金额",
    "high_trade_size_20": "高平均每笔金额", "reversal5_lowvol20": "反转 + 低波动", "custom": "自定义策略公式"}


def records(frame):
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def validate_request(body, defaults, dates):
    if not isinstance(body, dict):
        raise ValueError("请提交策略与参数")
    config = defaults.copy()
    strategy = body.get("strategy", "low_vol_60")
    if strategy not in LABELS:
        raise ValueError("请选择有效策略")
    bounds = {"initial_cash": (10000, 2e9), "top_n": (1, 500), "rebalance_every": (1, 60),
              "commission_bps": (0, 100), "slippage_bps": (0, 100),
              "invested_fraction": (.05, 1), "participation": (.0001, .1)}
    for key, (low, high) in bounds.items():
        try:
            value = float(body.get(key, defaults[key]))
        except (TypeError, ValueError):
            raise ValueError(f"{key} 需为数值") from None
        if not np.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} 需在 {low} 至 {high} 之间")
        if key in ("top_n", "rebalance_every"):
            if not value.is_integer():
                raise ValueError(f"{key} 需为整数")
            value = int(value)
        config[key] = value
    try:
        start = pd.Timestamp(body.get("start", defaults["test"][0]))
        end = pd.Timestamp(body.get("end", defaults["test"][1]))
        if start.tz is not None or end.tz is not None or pd.isna(start) or pd.isna(end):
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("请选择有效起止日期") from None
    if not dates[0] <= start <= end <= dates[-1] or not ((dates >= start) & (dates <= end)).any():
        raise ValueError("区间须在数据日期内，且至少包含一个交易日")
    formula = body.get("formula", "-returns(close, 5)")
    condition = body.get("condition", "True") or "True"
    if strategy == "custom":
        validate_expression(formula)
        validate_expression(condition)
    name = str(body.get("name", "我的策略")).strip()[:50] or "我的策略"
    return {"strategy": strategy, "name": name if strategy == "custom" else LABELS[strategy],
            "formula": formula if strategy == "custom" else None,
            "condition": condition if strategy == "custom" else None,
            "start": str(start.date()), "end": str(end.date()), "config": config}


class Workbench:
    def __init__(self, data_path, runtime, load=True, status_path=None):
        self.defaults = json.loads((HERE / "protocol.json").read_text())
        self.audit = json.loads((HERE / "results/data_audit.json").read_text())
        self.runtime = Path(runtime)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.ready, self.busy, self.error = False, False, None
        self.phase = "正在只读载入原始行情"
        self.panels = self.market = None
        self.course_state = None
        self.runs = {}
        self.current_id = "original"
        selected = json.loads((HERE / "results/selection.json").read_text())["selected"]
        self.runs["original"] = {
            "id": "original", "name": f"原始验证 · {LABELS[selected]}", "strategy": selected,
            "start": self.defaults["test"][0], "end": self.defaults["test"][1],
            "config": self.defaults.copy(), "formula": None, "condition": None,
            "created_at": "原始冻结实验", "mode": "frozen", "directory": HERE / "results",
            "files": {"daily": "test_selected_daily.csv", "orders": "test_selected_orders.csv",
                      "holdings": "test_selected_holdings.csv", "benchmark": "test_equal_weight_daily.csv"}}
        if status_path:
            self.defaults = json.loads((HERE / "assignment/protocol.json").read_text())
            self.runs["course"] = {**self.runs["original"], "id": "course", "name": "课程作业 · 60 日低波动",
                                   "start": self.defaults["test"][0], "end": self.defaults["test"][1],
                                   "config": self.defaults.copy(), "mode": "course", "directory": HERE / "assignment",
                                   "files": {"daily": "selected_daily.csv", "orders": "selected_orders.csv.gz",
                                             "holdings": "selected_holdings.csv.gz", "benchmark": "equal_weight_daily.csv"}}
            self.current_id = "course"
        if load:
            threading.Thread(target=self.load, args=(data_path, status_path), daemon=True).start()

    def load(self, data_path, status_path=None):
        try:
            self.panels = load_data(data_path)
            self.phase = "正在准备复权价格、流动性与可投股票池"
            self.market = prepare(self.panels, self.defaults)
            if status_path:
                from course import read_state
                self.course_state = read_state(status_path, self.market["dates"], self.market["symbols"])
                self.market["eligible"] &= self.course_state == 1
            if self.panels["source"]["sha256"] != self.audit["sha256"]:
                raise ValueError("原始 ZIP 与已有实验指纹不同，请先重新审计数据")
            self.ready, self.phase = True, "数据就绪"
        except Exception as error:
            self.error, self.phase = str(error), "数据载入失败"

    def submit(self, body):
        with self.lock:
            if not self.ready:
                raise ValueError(self.error or "数据仍在载入，请稍后运行")
            if self.busy:
                raise ValueError("已有回测正在运行，请等待完成")
            settings = validate_request(body, self.defaults, self.market["dates"])
            if self.course_state is not None and settings["end"] > "2026-09-30":
                raise ValueError("历史 ST 状态仅覆盖至 2026-09-30，请缩短区间")
            self.busy, self.error, self.phase = True, None, "计算策略信号"
            run_id = uuid.uuid4().hex[:12]
            threading.Thread(target=self.execute, args=(run_id, settings), daemon=True).start()
            return run_id

    def execute(self, run_id, settings):
        started = time.monotonic()
        try:
            config = settings["config"]
            if settings["strategy"] == "custom":
                score = evaluate(settings["formula"], self.panels, self.market)
                condition = evaluate(settings["condition"], self.panels, self.market, condition=True)
                market = {**self.market, "eligible": self.market["eligible"] & condition}
            else:
                market = self.market
                score = score_signal(settings["strategy"], self.panels, market)
            if not (np.isfinite(score) & self.market["eligible"]).any():
                raise ValueError("公式在可投股票池中没有有限分数；请检查窗口、条件和除零")
            weights = make_targets(score, market, config)
            self.phase = "模拟调仓、成交与资金账本"
            if self.course_state is not None:
                from course import simulate
                config["test"] = [settings["start"], settings["end"]]
                curve, orders, holdings, _ = simulate(market, score, self.course_state, config, self.panels["cumadj"])
            else:
                curve, orders, holdings = backtest(market, weights, settings["start"], settings["end"], config, keep_orders=True)
            if orders.empty:
                orders = pd.DataFrame(columns=["date", "signal_date", "symbol", "side", "requested_reference_notional",
                                               "filled_reference_notional", "adjusted_units", "adjusted_fill_price", "notional", "fee", "status"])
            if holdings.empty:
                holdings = pd.DataFrame(columns=["date", "symbol", "adjusted_units", "mark", "value", "stale_days"])
            self.phase = "计算同区间、同成本等权基准"
            benchmark_targets = make_targets(score_signal("equal_weight", self.panels, self.market), self.market, config, broad=True)
            if self.course_state is not None:
                benchmark, _, _, _ = simulate(self.market, np.zeros_like(score), self.course_state, config, self.panels["cumadj"], broad=True)
            else:
                benchmark, _, _ = backtest(self.market, benchmark_targets, settings["start"], settings["end"], config)
            directory = self.runtime / run_id
            directory.mkdir()
            files = {"daily": "daily.csv", "orders": "orders.csv", "holdings": "holdings.csv", "benchmark": "benchmark.csv"}
            curve.to_csv(directory / files["daily"], index_label="date")
            orders.to_csv(directory / files["orders"], index=False)
            holdings.to_csv(directory / files["holdings"], index=False)
            benchmark.to_csv(directory / files["benchmark"], index_label="date")
            run = {**settings, "id": run_id, "directory": directory, "files": files,
                   "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
                   "mode": "course-exploration" if self.course_state is not None else "exploration", "elapsed_seconds": round(time.monotonic() - started, 2),
                   "source_sha256": self.panels["source"]["sha256"]}
            (directory / "settings.json").write_text(json.dumps({k: v for k, v in run.items() if k != "directory"}, ensure_ascii=False, indent=2) + "\n")
            with self.lock:
                self.runs[run_id], self.current_id = run, run_id
                self.phase = "回测完成"
        except Exception as error:
            self.error, self.phase = str(error), "回测失败"
        finally:
            self.busy = False

    def run(self, run_id):
        if run_id not in self.runs:
            raise ValueError("没有找到该次回测，请刷新页面")
        return self.runs[run_id]

    def frame(self, run_id, kind):
        if kind not in {"daily", "orders", "holdings", "benchmark"}:
            raise ValueError("无效数据表")
        run = self.run(run_id)
        path = run["directory"] / run["files"][kind]
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

    def result(self, run_id):
        run = self.run(run_id)
        curve, baseline = self.frame(run_id, "daily"), self.frame(run_id, "benchmark")
        primary = metrics(curve, run["config"]["initial_cash"])
        benchmark = metrics(baseline, run["config"]["initial_cash"])
        curve["nav"] = curve.equity / run["config"]["initial_cash"]
        curve["drawdown"] = curve.nav / np.maximum.accumulate(np.r_[1., curve.nav])[1:] - 1
        curve["benchmark_nav"] = baseline.equity.to_numpy() / run["config"]["initial_cash"]
        curve["benchmark_drawdown"] = curve.benchmark_nav / np.maximum.accumulate(np.r_[1., curve.benchmark_nav])[1:] - 1
        holdings = self.frame(run_id, "holdings")
        return {"id": run_id, "name": run["name"], "strategy": run["strategy"], "mode": run["mode"],
                "start": run["start"], "end": run["end"], "created_at": run["created_at"],
                "config": run["config"], "formula": run["formula"], "condition": run["condition"],
                "metrics": primary, "benchmark_metrics": benchmark,
                "excess": primary["total_return"] - benchmark["total_return"],
                "curve": records(curve), "holding_dates": sorted(holdings.date.unique().tolist(), reverse=True) if len(holdings) else [],
                "elapsed_seconds": run.get("elapsed_seconds"),
                "terminal_positions": int(curve.holdings.iloc[-1]), "terminal_cash": float(curve.cash.iloc[-1]),
                "benchmark_terminal_positions": int(baseline.holdings.iloc[-1]),
                "empty_trades": not len(self.frame(run_id, "orders"))}


def create_app(workbench):
    app = Flask(__name__, static_folder=str(HERE / "web"), static_url_path="/static")
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

    @app.before_request
    def local_origin():
        if request.method == "POST" and request.headers.get("Origin"):
            if request.headers["Origin"] != request.host_url.rstrip("/"):
                return jsonify(error="请在本机工作台页面提交请求"), 403

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.get("/")
    def home():
        return send_from_directory(HERE / "web", "index.html")

    @app.get("/api/state")
    def state():
        with workbench.lock:
            runs = [{"id": k, "name": v["name"], "created_at": v["created_at"]} for k, v in workbench.runs.items()]
            return jsonify(ready=workbench.ready, busy=workbench.busy, phase=workbench.phase,
                           error=workbench.error, current_id=workbench.current_id, runs=runs,
                           strategies=LABELS, defaults=workbench.defaults,
                           data={"first_date": workbench.audit["first_date"], "last_date": workbench.audit["last_date"],
                                 "securities": workbench.audit["securities"], "days": workbench.audit["rows"],
                                 "sha256": workbench.audit["sha256"]})

    @app.get("/api/result/<run_id>")
    def result(run_id):
        return jsonify(workbench.result(run_id))

    @app.post("/api/run")
    def run():
        return jsonify(id=workbench.submit(request.get_json(silent=True))), 202

    @app.post("/api/formula/check")
    def check_formula():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("请提供公式")
        validate_expression(body.get("formula"))
        validate_expression(body.get("condition") or "True")
        return jsonify(message="语法和历史窗口检查通过。运行后将检查有效信号与实际成交。")

    @app.get("/api/table/<run_id>/<kind>")
    def table(run_id, kind):
        frame = workbench.frame(run_id, kind)
        if request.args.get("date") and "date" in frame:
            frame = frame[frame.date == request.args["date"]]
        query = request.args.get("q", "").strip()
        if query and "symbol" in frame:
            frame = frame[frame.symbol.str.contains(query, case=False, regex=False)]
        page = max(1, int(request.args.get("page", 1)))
        size = 25
        total = len(frame)
        page = min(page, max(1, int(np.ceil(total / size))))
        return jsonify(rows=records(frame.iloc[(page - 1) * size:page * size]), total=total,
                       page=page, pages=max(1, int(np.ceil(total / size))))

    @app.get("/api/export/<run_id>/<kind>")
    def export(run_id, kind):
        frame = workbench.frame(run_id, kind)
        content = io.StringIO()
        frame.to_csv(content, index=False)
        return Response("\ufeff" + content.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{run_id}-{kind}.csv"'})

    @app.get("/api/candidates")
    def candidates():
        frame = pd.read_csv(HERE / "results/candidates.csv")
        frame = frame[frame.stage == "validation"].sort_values("sharpe", ascending=False)
        return jsonify(rows=records(frame), labels=LABELS)

    @app.get("/api/audit")
    def audit():
        return jsonify(workbench.audit)

    @app.get("/report")
    def report():
        return send_from_directory(HERE, "report.html")

    @app.get("/assignment/<path:name>")
    def assignment(name):
        return send_from_directory(HERE / "assignment", name)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--status", type=Path, default=HERE / "data/status.parquet")
    args = parser.parse_args()
    workbench = Workbench(args.data, HERE / "runtime", status_path=args.status if args.status.exists() else None)
    print(f"本地回测工作台：http://127.0.0.1:{args.port}", flush=True)
    create_app(workbench).run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
