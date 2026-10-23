import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import prepare
from formula import evaluate, validate_expression
from server import Workbench, create_app, validate_request
from signals import score_signal


HERE = Path(__file__).resolve().parents[1]


@pytest.fixture
def panels():
    rng = np.random.default_rng(19)
    close = pd.DataFrame(10 * np.exp(np.cumsum(rng.normal(0, .01, (170, 4)), axis=0)),
                         index=pd.bdate_range("2024-01-01", periods=170), columns=["A", "B", "C", "D"])
    return {"close": close, "open": close * .999, "high": close * 1.01, "low": close * .99,
            "cumadj": close * 0 + 1, "amt": close * 0 + 1e8, "num_trades": close * 0 + 1000}


@pytest.fixture
def config():
    result = json.loads((HERE / "protocol.json").read_text())
    result.update(top_n=2, min_history=30)
    return result


@pytest.mark.parametrize("expression", [
    "lag(close, -1)", "returns(close, 0)", "ts_mean(close, 253)", "lag(close, 1.5)",
    "__import__('os')", "close.__class__", "close.iloc[0]", "open('/tmp/x')", "sum(close)",
    "[x for x in close]", "returns(close, n=2)", "close ** 1000000"
])
def test_formula_rejects_future_or_python_access(expression):
    with pytest.raises(ValueError):
        validate_expression(expression)


def test_formula_matches_existing_strategy_and_prefix(panels, config):
    market = prepare(panels, config)
    formula = "-returns(close, 5)"
    np.testing.assert_allclose(evaluate(formula, panels, market), score_signal("reversal_5", panels, market), equal_nan=True)
    expression = "rank(returns(close, 20)) + rank(-ts_std(returns(close, 1), 20))"
    prefix = {key: value.iloc[:145] for key, value in panels.items()}
    before = prepare(prefix, config)
    np.testing.assert_allclose(evaluate(expression, panels, market)[:145], evaluate(expression, prefix, before), equal_nan=True)


def test_conditions_missing_values_and_where(panels, config):
    panels["close"].iloc[100, 0] = np.nan
    market = prepare(panels, config)
    assert not evaluate("close != 0", panels, market, condition=True)[100, 0]
    actual = evaluate("close > ts_mean(close, 20) and amount > 100", panels, market, condition=True)
    expected = ((market["close"] > market["close"].rolling(20).mean()) & (panels["amt"] > 100)).to_numpy()
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(evaluate("where(close > 0, 1, 0)", panels, market)[100], [0, 1, 1, 1])


@pytest.mark.parametrize("body", [{"top_n": 0}, {"top_n": 2.5}, {"initial_cash": "NaN"},
                                  {"strategy": "unknown"}, {"start": "2024-09-01", "end": "2024-01-01"},
                                  {"start": "2024-01-01", "end": "2029-01-01"}])
def test_invalid_parameters(body, config, panels):
    with pytest.raises(ValueError):
        validate_request({"start": "2024-04-01", "end": "2024-06-28", **body}, config, panels["close"].index)


@pytest.fixture
def workbench(tmp_path, panels, config):
    app = Workbench("unused", tmp_path, load=False)
    app.defaults = config
    app.panels = {**panels, "source": {"sha256": "synthetic-test"}}
    app.market = prepare(panels, config)
    app.ready = True
    return app


def wait_for_run(workbench):
    deadline = time.monotonic() + 10
    while workbench.busy and time.monotonic() < deadline:
        time.sleep(.01)
    assert not workbench.busy
    assert workbench.error is None, workbench.error


def test_http_custom_strategy_end_to_end_and_original_unchanged(workbench):
    client = create_app(workbench).test_client()
    original = workbench.result("original")
    assert client.get("/").status_code == 200
    assert client.post("/api/formula/check", json={"formula": "lag(close,-1)"}).status_code == 400
    response = client.post("/api/run", json={"strategy": "custom", "name": "测试策略", "formula": "-returns(close, 5)",
                                               "condition": "close > ts_mean(close, 20)",
                                               "start": "2024-04-01", "end": "2024-06-28"})
    assert response.status_code == 202
    run_id = response.json["id"]
    wait_for_run(workbench)
    data = client.get(f"/api/result/{run_id}").json
    assert data["mode"] == "exploration" and data["name"] == "测试策略"
    assert data["metrics"]["days"] > 50
    assert data["metrics"]["min_cash"] >= -1e-6
    table = client.get(f"/api/table/{run_id}/orders").json
    assert table["total"] > 0
    assert all(row["signal_date"] < row["date"] for row in table["rows"])
    assert client.get(f"/api/table/{run_id}/holdings?q=A").status_code == 200
    assert client.get(f"/api/export/{run_id}/daily").headers["Content-Type"].startswith("text/csv")
    assert client.get("/api/result/original").json["metrics"] == original["metrics"]
    assert client.get("/api/export/original/private").status_code == 400
    assert client.post("/api/run", json={}, headers={"Origin": "https://untrusted.example"}).status_code == 403


def test_zero_orders_results_still_display_and_export(workbench):
    client = create_app(workbench).test_client()
    response = client.post("/api/run", json={"strategy": "custom", "formula": "close", "condition": "False",
                                               "start": "2024-04-01", "end": "2024-06-28"})
    assert response.status_code == 202
    run_id = response.json["id"]
    wait_for_run(workbench)
    result = client.get(f"/api/result/{run_id}").json
    assert result["empty_trades"]
    assert result["metrics"]["total_return"] == 0
    assert client.get(f"/api/table/{run_id}/orders").json["total"] == 0
    assert "signal_date" in client.get(f"/api/export/{run_id}/orders").text
