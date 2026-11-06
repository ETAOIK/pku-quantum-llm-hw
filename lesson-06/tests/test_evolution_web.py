import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lesson-05"))
from app import FactorService, FactorWorkbench, create_app
from harness import evaluate, read, write
from evolution_web import EvolutionService
from course import simulate
from server import create_app as backtest_app
from test_harness import candidate, synthetic_tools


@pytest.fixture
def integrated(tmp_path):
    tools = synthetic_tools()
    wb = FactorWorkbench("synthetic-only", tmp_path / "backtests", load=False)
    wb.defaults, wb.market, wb.course_state = tools.config, tools.market, tools.state
    wb.panels, wb.ready = {**tools.panels, "source": {"sha256": "synthetic-test-only"}}, True
    wb.status_path = tmp_path / "status"
    wb.status_path.write_text("synthetic test status")
    app = create_app(FactorService(wb, tmp_path / "factors"))
    service = app.extensions["evolution"]
    service.runtime, service.jobs = tmp_path / "evolution", {}
    service.runtime.mkdir()
    folder = service.runtime / "existing"
    c = {**candidate("user_child", "rank(-returns(close, 5))"), "condition": "close > ts_mean(close, 5)",
         "top_n": 50, "rebalance_every": 10, "generation": 0, "objective": .1,
         "development_pass": True, "folds": []}
    protocol = {**tools.protocol, "followup": ["2025-01-02", "2025-05-20"]}
    write(folder / "state.json", {"phase": "complete", "next_generation": 3, "history": [c]})
    write(folder / "protocol.json", protocol)
    write(folder / "manifest.json", {"data_sha256": "synthetic-test-only"})
    service.jobs["existing"] = {"id": "existing", "directory": folder, "name": "synthetic only", "status": "complete", "mode": "replay", "error": None}
    return app.test_client(), service, wb, c, protocol


def test_existing_app_exposes_evolution_and_keeps_report_routes_absent(integrated):
    client, service, wb, _, _ = integrated
    for path in ("/", "/backtest", "/evolution", "/evolution-static/app.js", "/evolution-static/base.css"):
        assert client.get(path).status_code == 200
    for path in ("/report", "/factor-report", "/assignment/report.html"):
        assert client.get(path).status_code == 404
    assert "Agent 演化" in client.get("/").text and "Agent 演化" in client.get("/backtest").text
    assert client.get("/api/evolution/state").json["backtest_url"] == "/backtest"
    result = client.get("/api/evolution/result/existing").json
    assert result["state"]["history"][0]["formula"] == "rank(-returns(close, 5))"
    assert result["rounds"][0]["leader"] == "user_child"
    assert client.get("/api/evolution/result/missing").status_code == 400


def test_original_lesson04_entry_also_contains_evolution(integrated):
    _, _, wb, _, _ = integrated
    client = backtest_app(wb).test_client()
    assert client.get("/").status_code == client.get("/evolution").status_code == 200
    assert client.get("/api/evolution/state").json["backtest_url"] == "/"


def test_server_controls_model_command_and_shares_busy_lock(integrated):
    client, service, wb, _, _ = integrated
    assert not client.get("/api/evolution/state").json["agent_available"]
    assert client.post("/api/evolution/run", json={"mode": "auto"}).status_code == 400
    assert client.post("/api/evolution/run", json={"mode": "replay", "agent_command": ["anything"]}).status_code == 400
    assert client.post("/api/evolution/run", json={"mode": "replay"}, headers={"Origin": "https://evil.example"}).status_code == 403
    wb.busy = True
    assert client.post("/api/evolution/run", json={"mode": "replay"}).status_code == 400
    assert client.post("/api/evolution/backtest/existing/user_child", json={}).status_code == 400
    wb.busy = False
    assert client.post("/api/evolution/backtest/existing/missing", json={}).status_code == 400
    assert client.post("/api/evolution/resume/existing", json={"mode": "replay"}).status_code == 400


def test_candidate_bridge_preserves_formula_parameters_and_original_benchmark(integrated):
    client, service, wb, c, protocol = integrated
    response = client.post("/api/evolution/backtest/existing/user_child", json={})
    assert response.status_code == 202
    run_id = response.json["id"]
    assert response.json["url"] == f"/backtest?run={run_id}"
    deadline = time.monotonic() + 15
    while wb.busy and time.monotonic() < deadline:
        time.sleep(.01)
    assert not wb.busy and wb.error is None, wb.error
    run = wb.run(run_id)
    assert run["formula"] == c["formula"] and run["condition"] == c["condition"]
    assert run["config"]["top_n"] == 50 and run["config"]["rebalance_every"] == 10
    assert run["benchmark_rebalance_every"] == 5
    assert run["config"]["initial_cash"] == protocol["account"]["initial_cash"]
    score = evaluate(c["formula"], wb.panels, wb.market)
    pool = {**wb.market, "eligible": wb.market["eligible"] & evaluate(c["condition"], wb.panels, wb.market, condition=True)}
    expected, *_ = simulate(pool, score, wb.course_state, run["config"], wb.panels["cumadj"])
    benchmark, *_ = simulate(wb.market, np.zeros_like(score), wb.course_state, {**run["config"], "rebalance_every": 5}, wb.panels["cumadj"], broad=True)
    np.testing.assert_allclose(wb.frame(run_id, "daily").equity, expected.equity, rtol=1e-12)
    np.testing.assert_allclose(wb.frame(run_id, "benchmark").equity, benchmark.equity, rtol=1e-12)
    actual = client.get(f"/api/result/{run_id}").json
    assert actual["evolution_origin"] == {"run_id": "existing", "candidate_id": "user_child"}
    del wb.runs[run_id]
    EvolutionService(wb, service.runtime, service.results)
    assert wb.run(run_id)["evolution_origin"]["candidate_id"] == "user_child"


def test_background_controller_uses_existing_harness_and_records_completion(integrated, monkeypatch):
    client, service, wb, _, _ = integrated
    calls = []
    class StubProcess:
        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))
            output = Path(command[command.index("--output") + 1])
            write(output / "state.json", {"phase": "complete", "history": [], "next_generation": 3})
            self.stdout = iter(["generation=0 candidate=stub development=stub\n"])
            self.pid = 12345
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def wait(self):
            return 0
    monkeypatch.setattr("evolution_web.subprocess.Popen", StubProcess)
    response = client.post("/api/evolution/run", json={"mode": "replay"})
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while wb.busy and time.monotonic() < deadline:
        time.sleep(.01)
    job = service.jobs[response.json["id"]]
    assert not wb.busy and job["status"] == "complete"
    assert read(job["directory"] / "web-job.json")["status"] == "complete"
    command, kwargs = calls[0]
    assert command[2].endswith("lesson-06/harness.py") and command[3] == "replay"
    assert kwargs.get("shell", False) is False
    assert kwargs["env"]["OPENBLAS_NUM_THREADS"] == "1"
    assert client.get(f"/api/evolution/result/{job['id']}").json["log"].startswith("generation=0")


def test_restarted_service_does_not_resume_a_still_running_child(integrated, monkeypatch):
    _, service, wb, _, _ = integrated
    folder = service.runtime / "old"
    write(folder / "web-job.json", {"id": "old", "mode": "replay", "name": "synthetic interrupted run", "status": "running", "pid": 12345})
    monkeypatch.setattr("evolution_web.os.kill", lambda *_: None)
    restarted = EvolutionService(wb, service.runtime, service.results)
    assert restarted.jobs["old"]["status"] == "orphaned"
    with pytest.raises(ValueError, match="失败或中断"):
        restarted.submit({"mode": "replay"}, resume="old")
    def gone(*_):
        raise ProcessLookupError()
    monkeypatch.setattr("evolution_web.os.kill", gone)
    restarted = EvolutionService(wb, service.runtime, service.results)
    assert restarted.jobs["old"]["status"] == "interrupted"
