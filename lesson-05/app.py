"""Lesson 05 factor workbench, extending lesson 04's local account backtest."""
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
from flask import Response, jsonify, request, send_from_directory

from shared import FOURTH, CATALOG, Workbench, backtest_app, factor_score, validate_expression
from server import validate_request
from factor import HERE, DEFAULTS, analyze, save_result, transform, validate_settings


def records(frame):
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def validate_factor(body, dates):
    settings = validate_settings(body, dates)
    name = body.get("factor", "low_vol_60")
    if name not in CATALOG:
        raise ValueError("请选择已实现的因子或自定义公式")
    formula = body.get("formula", "-returns(close, 5)")
    condition = body.get("condition", "True") or "True"
    if name == "custom":
        validate_expression(formula)
    validate_expression(condition)
    return {**settings, "factor": name, "name": str(body.get("name") or CATALOG[name])[:60],
            "formula": formula if name == "custom" else None, "condition": condition}


class FactorWorkbench(Workbench):
    def compute_score(self, settings):
        if "factor_settings" not in settings:
            return super().compute_score(settings)
        factor = settings["factor_settings"]
        score, market = factor_score(factor, self.panels, self.market)
        score = transform(score, market["eligible"], factor)
        return score, market


class FactorService:
    def __init__(self, workbench, runtime, results=None):
        self.wb = workbench
        self.runtime = Path(runtime)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.runs = {}
        self.current_id = None
        if results:
            for path in sorted(Path(results).glob("factors/*/settings.json")):
                settings = json.loads(path.read_text())
                run_id = path.parent.name
                self.runs[run_id] = {"directory": path.parent, "settings": settings}
            self.current_id = "low_vol_60" if "low_vol_60" in self.runs else next(iter(self.runs), None)

    def valid_dates(self):
        dates = self.wb.market["dates"]
        if self.wb.course_state is not None:
            dates = dates[(self.wb.course_state >= 0).any(axis=1)]
        return dates

    def submit(self, body):
        with self.wb.lock:
            if not self.wb.ready or self.wb.busy:
                raise ValueError("数据尚未就绪或已有任务在运行")
            settings = validate_factor(body, self.valid_dates())
            run_id = uuid.uuid4().hex[:12]
            self.wb.busy, self.wb.error, self.wb.phase = True, None, "计算因子与多周期评价"
            threading.Thread(target=self.execute, args=(run_id, settings), daemon=True).start()
        return run_id

    def execute(self, run_id, settings):
        started = time.monotonic()
        try:
            score, market = factor_score(settings, self.wb.panels, self.wb.market)
            result = analyze(score, market, settings)
            settings.update(source_sha256=self.wb.panels["source"]["sha256"],
                            historical_status=self.wb.course_state is not None,
                            created_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
                            elapsed_seconds=round(time.monotonic() - started, 2))
            directory = self.runtime / run_id
            save_result(directory, result, settings)
            with self.wb.lock:
                self.runs[run_id] = {"directory": directory, "settings": settings}
                self.current_id = run_id
                self.wb.phase = "因子评价完成"
        except Exception as error:
            self.wb.error, self.wb.phase = str(error), "因子评价失败"
        finally:
            with self.wb.lock:
                self.wb.busy = False

    def run(self, run_id):
        if run_id not in self.runs:
            raise ValueError("没有找到这次因子评价")
        return self.runs[run_id]

    def frame(self, run_id, kind):
        if kind not in ("summary", "daily", "periods", "quantiles"):
            raise ValueError("没有此类评价表")
        filename = "daily.csv.gz" if kind == "daily" else f"{kind}.csv"
        return pd.read_csv(self.run(run_id)["directory"] / filename)

    def result(self, run_id):
        return {"id": run_id, "settings": self.run(run_id)["settings"],
                **{kind: records(self.frame(run_id, kind)) for kind in ("summary", "daily", "periods", "quantiles")}}

    def bridge(self, run_id):
        factor = self.run(run_id)["settings"]
        if factor["factor"].endswith("control") or factor["factor"] == "negative_low_vol_60":
            raise ValueError("对照因子用于诊断，请选择实际因子衔接策略回测")
        with self.wb.lock:
            if not self.wb.ready or self.wb.busy:
                raise ValueError("数据尚未就绪或已有任务在运行")
            name = factor["factor"]
            body = {"strategy": name, "name": factor["name"], "formula": factor["formula"],
                    "condition": factor["condition"], "start": factor["start"], "end": factor["end"]}
            settings = validate_request(body, self.wb.defaults, self.valid_dates())
            settings["factor_settings"] = factor.copy()
            settings["name"] = f"因子回测 · {factor['name']} · 方向{factor['direction']:+d} · {factor['preprocess']}"
            self.wb.busy, self.wb.error, self.wb.phase = True, None, "按本次因子计算扣费策略账本"
            backtest_id = uuid.uuid4().hex[:12]
            threading.Thread(target=self.wb.execute, args=(backtest_id, settings), daemon=True).start()
        return backtest_id


def create_app(service):
    app = backtest_app(service.wb)
    original_home = app.view_functions["home"]
    app.add_url_rule("/backtest", "backtest_home", original_home)
    app.view_functions["home"] = lambda: send_from_directory(HERE / "web", "index.html")

    @app.get("/factor-static/<path:name>")
    def factor_static(name):
        return send_from_directory(HERE / "web", name)

    @app.get("/api/factors/state")
    def factor_state():
        with service.wb.lock:
            dates = service.valid_dates() if service.wb.ready else None
            return jsonify(ready=service.wb.ready, busy=service.wb.busy, error=service.wb.error,
                           phase=service.wb.phase, current_id=service.current_id, catalog=CATALOG,
                           defaults=DEFAULTS, historical_status=service.wb.course_state is not None,
                           first_date=str(dates[0].date()) if dates is not None else None,
                           last_date=str(dates[-1].date()) if dates is not None else None,
                           runs=[{"id": key, "name": value["settings"]["name"]} for key, value in service.runs.items()])

    @app.post("/api/factors/run")
    def factor_run():
        return jsonify(id=service.submit(request.get_json(silent=True))), 202

    @app.get("/api/factors/comparison")
    def comparison():
        path = HERE / "results/comparison.csv"
        return jsonify(records(pd.read_csv(path)) if path.exists() else [])

    @app.get("/api/factors/result/<run_id>")
    def factor_result(run_id):
        return jsonify(service.result(run_id))

    @app.post("/api/factors/backtest/<run_id>")
    def bridge(run_id):
        return jsonify(id=service.bridge(run_id), url="/backtest"), 202

    @app.get("/api/factors/export/<run_id>/<kind>")
    def factor_export(run_id, kind):
        content = io.StringIO()
        service.frame(run_id, kind).to_csv(content, index=False)
        return Response("\ufeff" + content.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="factor-{run_id}-{kind}.csv"'})

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=FOURTH / "data/feathers.zip")
    parser.add_argument("--status", type=Path, default=FOURTH / "data/status.parquet")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    wb = FactorWorkbench(args.data, HERE / "runtime/backtests", status_path=args.status if args.status.exists() else None)
    service = FactorService(wb, HERE / "runtime/factors", HERE / "results")
    print(f"第五课因子评价：http://127.0.0.1:{args.port}；原回测：/backtest", flush=True)
    create_app(service).run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
