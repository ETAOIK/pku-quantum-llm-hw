"""Expose the existing Harness inside the original local backtest application."""
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from flask import jsonify, request, send_from_directory

from harness import HERE, clean, now, ranked, read, write


class EvolutionService:
    def __init__(self, workbench, runtime=None, results=None):
        self.wb = workbench
        self.runtime = Path(runtime or HERE / "runtime/web")
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.results = Path(results or HERE / "results")
        self.jobs = {}
        for path in workbench.runtime.glob("*/settings.json"):
            run = read(path)
            if run.get("evolution_origin"):
                workbench.runs[run["id"]] = {**run, "directory": path.parent}
        if (self.results / "state.json").exists():
            self.jobs["saved"] = {"id": "saved", "directory": self.results, "mode": "recorded_replay",
                                  "status": "complete", "name": "第六课 · 已保存的三代演化", "started_at": "2026-10-30", "error": None}
        for path in sorted(self.runtime.glob("*/web-job.json")):
            job = read(path)
            job["directory"] = path.parent
            if job["status"] == "running":
                try:
                    if not job.get("pid"):
                        raise PermissionError()
                    os.kill(job["pid"], 0)
                except ProcessLookupError:
                    job.update(status="interrupted", error="此前任务进程已停止，可继续运行")
                except PermissionError:
                    job.update(status="orphaned", error="无法确认此前任务已停止，暂不允许在同一目录继续")
                else:
                    job.update(status="orphaned", error="此前任务进程仍在运行，暂不允许在同一目录继续")
            self.jobs[job["id"]] = job
        command = getattr(workbench, "agent_command", None)
        if isinstance(command, str):
            try:
                command = json.loads(command)
            except json.JSONDecodeError:
                raise ValueError("--agent-command 需为 JSON 字符串数组") from None
        if command is not None and (not isinstance(command, list) or not command or any(not isinstance(v, str) or not v for v in command)):
            raise ValueError("--agent-command 需为非空 JSON 字符串数组")
        self.agent_command = command

    def job(self, run_id):
        if run_id not in self.jobs:
            raise ValueError("没有找到这次演化")
        return self.jobs[run_id]

    def save_job(self, job):
        write(job["directory"] / "web-job.json", {k: v for k, v in job.items() if k != "directory"})

    def state(self):
        with self.wb.lock:
            return {"ready": self.wb.ready, "busy": self.wb.busy, "phase": self.wb.phase,
                    "historical_status": self.wb.course_state is not None, "agent_available": self.agent_command is not None,
                    "runs": [{k: v for k, v in job.items() if k != "directory"} for job in self.jobs.values()]}

    def submit(self, body, resume=None):
        if not isinstance(body, dict) or set(body) != {"mode"} or body["mode"] not in ("replay", "auto"):
            raise ValueError("请选择重放或已配置模型的自主挖掘")
        mode = body["mode"]
        with self.wb.lock:
            if not self.wb.ready or self.wb.busy:
                raise ValueError("数据尚未就绪或已有评价/演化/回测任务在运行")
            if self.wb.course_state is None or not self.wb.status_path:
                raise ValueError("演化需要第四课历史 ST 状态数据")
            if mode == "auto" and self.agent_command is None:
                raise ValueError("尚未配置模型命令，请在启动服务时配置 --agent-command")
            if resume:
                job = self.job(resume)
                if job["status"] not in ("failed", "interrupted") or job["mode"] != mode:
                    raise ValueError("仅可继续同一模式的失败或中断任务")
            else:
                run_id = uuid.uuid4().hex[:12]
                job = {"id": run_id, "directory": self.runtime / run_id, "mode": mode,
                       "name": ("模型自主挖掘" if mode == "auto" else "原提案重放") + " · " + now()[11:19], "started_at": now()}
                self.jobs[run_id] = job
            job.update(status="running", error=None)
            self.save_job(job)
            self.wb.busy, self.wb.error, self.wb.phase = True, None, "Agent 演化启动中"
            threading.Thread(target=self.execute, args=(job,), daemon=True).start()
            return job["id"]

    def execute(self, job):
        try:
            command = [sys.executable, "-u", str(HERE / "harness.py"), job["mode"], "--output", str(job["directory"]),
                       "--data", str(self.wb.data_path), "--status", str(self.wb.status_path)]
            if job["mode"] == "auto":
                command += ["--agent-command", json.dumps(self.agent_command)]
            env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
            with (job["directory"] / "web-run.log").open("a") as log:
                with subprocess.Popen(command, cwd=HERE.parent, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as process:
                    with self.wb.lock:
                        job["pid"] = process.pid
                        self.save_job(job)
                    for line in process.stdout:
                        log.write(line)
                        log.flush()
                        if line.startswith(("generation=", "validation ", "followup ")):
                            with self.wb.lock:
                                self.wb.phase = "Agent 演化 · " + line.strip()
                    if process.wait():
                        raise ValueError("演化任务失败，查看运行日志后可继续；已完成代保留")
            if read(job["directory"] / "state.json")["phase"] != "complete":
                raise ValueError("演化没有完成冻结后检查")
            with self.wb.lock:
                job.update(status="complete", completed_at=now())
                self.wb.phase = "Agent 演化完成"
        except Exception as error:
            with self.wb.lock:
                job.update(status="failed", error=str(error))
                self.wb.error, self.wb.phase = str(error), "Agent 演化失败"
        finally:
            with self.wb.lock:
                self.save_job(job)
                self.wb.busy = False

    def result(self, run_id):
        job = self.job(run_id)
        folder = job["directory"]
        def optional(name):
            try:
                return read(folder / name)
            except (FileNotFoundError, json.JSONDecodeError):
                # The worker may be between opening and finishing a JSON write.
                return None
        state = optional("state.json") or {"phase": "starting", "next_generation": 0, "history": []}
        rounds = []
        for g in sorted({c["generation"] for c in state["history"]}):
            candidates = [c for c in state["history"] if c["generation"] == g]
            leader = ranked(candidates)[0]
            rounds.append({"generation": g, "count": len(candidates), "passed": sum(c["development_pass"] for c in candidates),
                           "leader": leader["id"], "objective": leader["objective"]})
        summary = optional("summary.json")
        log = folder / "web-run.log"
        return clean({"job": {k: v for k, v in job.items() if k != "directory"}, "state": state,
                      "protocol": optional("protocol.json"), "rounds": rounds, "selection": optional("selection.json"),
                      "followup": summary["followup"] if summary else [],
                      "log": log.read_text()[-14000:] if log.exists() else "已保存运行，原始提案与每代反馈可在候选中查看。"})

    def bridge(self, run_id, candidate_id):
        from server import validate_request
        job = self.job(run_id)
        if job["status"] != "complete":
            raise ValueError("请等待演化完成后复测候选")
        folder = job["directory"]
        history = read(folder / "state.json")["history"]
        candidates = {c["id"]: c for c in history}
        if candidate_id not in candidates:
            raise ValueError("没有找到该候选")
        c, protocol = candidates[candidate_id], read(folder / "protocol.json")
        with self.wb.lock:
            if not self.wb.ready or self.wb.busy:
                raise ValueError("数据尚未就绪或已有任务在运行")
            if self.wb.course_state is None:
                raise ValueError("复测需要原演化使用的历史 ST 状态")
            if self.wb.panels["source"]["sha256"] != read(folder / "manifest.json")["data_sha256"]:
                raise ValueError("演化与回测行情指纹不同")
            settings = validate_request({**protocol["account"], "strategy": "custom", "name": "Agent · " + c["name"],
                                        "formula": c["formula"], "condition": c["condition"], "top_n": c["top_n"],
                                        "rebalance_every": c["rebalance_every"], "start": protocol["followup"][0],
                                        "end": protocol["followup"][1]}, self.wb.defaults, self.wb.market["dates"])
            settings["benchmark_rebalance_every"] = 5
            settings["evolution_origin"] = {"run_id": run_id, "candidate_id": candidate_id}
            backtest_id = uuid.uuid4().hex[:12]
            self.wb.busy, self.wb.error, self.wb.phase = True, None, "复测 Agent 候选与原等权基准"
            threading.Thread(target=self.wb.execute, args=(backtest_id, settings), daemon=True).start()
        return backtest_id


def register_evolution(app, workbench):
    service = EvolutionService(workbench)
    app.extensions["evolution"] = service
    app.config["EVOLUTION_URL"] = "/evolution"

    @app.get("/evolution")
    def evolution_home():
        return send_from_directory(HERE / "web", "index.html")

    @app.get("/evolution-static/<path:name>")
    def evolution_static(name):
        if name == "base.css":
            return send_from_directory(HERE.parent / "lesson-05/web", "style.css")
        return send_from_directory(HERE / "web", name)

    @app.get("/api/evolution/state")
    def evolution_state():
        return jsonify({**service.state(), "backtest_url": "/backtest" if "backtest_home" in app.view_functions else "/"})

    @app.get("/api/evolution/result/<run_id>")
    def evolution_result(run_id):
        return jsonify(service.result(run_id))

    @app.post("/api/evolution/run")
    def evolution_run():
        return jsonify(id=service.submit(request.get_json(silent=True))), 202

    @app.post("/api/evolution/resume/<run_id>")
    def evolution_resume(run_id):
        return jsonify(id=service.submit(request.get_json(silent=True), resume=run_id)), 202

    @app.post("/api/evolution/backtest/<run_id>/<candidate_id>")
    def evolution_backtest(run_id, candidate_id):
        backtest_id = service.bridge(run_id, candidate_id)
        return jsonify(id=backtest_id, url=f"/backtest?run={backtest_id}" if "backtest_home" in app.view_functions else f"/?run={backtest_id}"), 202
