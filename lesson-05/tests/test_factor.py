import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factor import DEFAULTS, analyze, assign_groups, forward_returns, hac_interval, transform, validate_settings
from shared import FOURTH, Workbench, factor_score
from data import prepare
from app import FactorService, FactorWorkbench, create_app


@pytest.fixture
def market():
    dates = pd.bdate_range("2025-01-01", periods=90)
    growth = 1 + np.arange(1, 11) / 1000
    opening = 10 * growth[None, :] ** np.arange(90)[:, None]
    return {"dates": dates, "symbols": pd.Index([f"S{i}" for i in range(10)]),
            "open": opening, "eligible": np.ones((90, 10), dtype=bool)}


@pytest.fixture
def settings(market):
    return {**DEFAULTS, "start": "2025-01-01", "end": str(market["dates"][-1].date()),
            "horizons": [1, 5, 20], "min_pairs": 3}


def test_next_open_label_and_boundary():
    dates = pd.bdate_range("2025-01-01", periods=5)
    opening = np.array([[100.], [200.], [300.], [600.], [900.]])
    actual, mature = forward_returns(opening, dates, 1, dates[3])
    np.testing.assert_allclose(actual[:, 0], [.5, 1., np.nan, np.nan, np.nan], equal_nan=True)
    np.testing.assert_array_equal(mature, [True, True, False, False, False])


def test_oracle_reverse_and_constant_are_distinguished(market, settings):
    score = np.tile(np.arange(10, dtype=float), (90, 1))
    good = analyze(score, market, settings)
    bad = analyze(-score, market, settings)
    constant = analyze(score * 0 + 1, market, settings)
    np.testing.assert_allclose(good["summary"].rank_ic_mean, 1)
    np.testing.assert_allclose(bad["summary"].rank_ic_mean, -1)
    assert good["summary"].spread_mean.gt(0).all()
    assert bad["summary"].diagnosis.str.contains("方向相反").all()
    assert constant["summary"].rank_ic_mean.isna().all()
    assert constant["summary"].rank_icir.isna().all()
    assert constant["summary"].group_valid_days.eq(0).all()
    assert constant["summary"].diagnosis.str.contains("不可评价").all()
    # Deterministic IC=1 has zero time-series std; do not invent an infinite ICIR.
    assert good["summary"].rank_icir.isna().all()


def test_future_missing_does_not_change_group_assignment(market, settings):
    score = np.tile(np.arange(10, dtype=float), (90, 1))
    complete = analyze(score, market, settings)["daily"]
    market["open"][2, 9] = np.nan
    actual = analyze(score, market, settings)["daily"]
    row = actual[(actual.date == "2025-01-01") & (actual.horizon == 1)].iloc[0]
    assert row.q5_count == 2 and row.q5_paired == 1
    assert row.paired_count == 9
    for q in range(1, 6):
        np.testing.assert_array_equal(actual[f"q{q}_count"], complete[f"q{q}_count"])
    summary = analyze(score, market, settings)["summary"].iloc[0]
    assert summary.missing_labels > 0 and summary.label_coverage < 1


def test_ties_never_split_and_low_sample_is_undefined(market, settings):
    values = np.repeat(np.arange(5), 2).astype(float)
    np.testing.assert_array_equal(assign_groups(values, 5), np.repeat(np.arange(1, 6), 2))
    assert not assign_groups(np.ones(10), 5).any()
    settings["min_pairs"] = 11
    result = analyze(np.tile(values, (90, 1)), market, settings)
    assert result["summary"].ic_days.eq(0).all()


def test_no_labels_beyond_end_or_forward_fill(market, settings):
    settings["end"] = str(market["dates"][50].date())
    market["open"][2, 0] = np.nan
    labels, _ = forward_returns(market["open"], market["dates"], 1, settings["end"])
    assert np.isnan(labels[0, 0])
    result = analyze(np.tile(np.arange(10), (90, 1)), market, settings)["daily"]
    assert result.loc[~result.label_mature, "paired_count"].eq(0).all()
    assert (pd.to_datetime(result.loc[result.label_mature, "exit_date"]) <= settings["end"]).all()
    for _, part in result.groupby("horizon"):
        assert (part.entry_date > part.date).all()


def test_hac_preserves_missing_calendar_positions():
    values = np.sin(np.arange(70) / 6)
    values[[5, 8, 11]] = np.nan
    mean = np.nanmean(values)
    z = np.nan_to_num(values - mean)
    var = z @ z + sum(2 * (1 - k / 6) * (z[k:] @ z[:-k]) for k in range(1, 6))
    expected = 1.96 * np.sqrt(var) / np.isfinite(values).sum()
    np.testing.assert_allclose(hac_interval(values, 1), [mean - expected, mean + expected])
    assert np.isnan(hac_interval(values[:20], 1)).all()


def test_preprocessing_uses_only_current_eligible_cross_section(market, settings):
    values = np.tile(np.arange(10, dtype=float), (90, 1))
    settings.update(preprocess="winsor_zscore", direction=-1)
    full = transform(values, market["eligible"], settings)
    before = transform(values[:50], market["eligible"][:50], settings)
    np.testing.assert_allclose(full[:50], before)
    np.testing.assert_allclose(full.mean(axis=1), 0, atol=1e-12)
    np.testing.assert_allclose(full.std(axis=1, ddof=1), 1)
    assert (np.diff(full, axis=1) <= 0).all()


@pytest.mark.parametrize("body", [None, {"direction": True}, {"direction": 0}, {"horizons": [0]},
                                 {"horizons": [1.5]}, {"horizons": "1,5"}, {"quantiles": 2.5},
                                 {"preprocess": "future"}, {"start": "2025-01-01T08:00"},
                                 {"start": "2026-01-01"}, {"end": "2025-01-02"}])
def test_invalid_evaluation_settings(body, market, settings):
    value = {**settings, **body} if body is not None else None
    with pytest.raises(ValueError):
        validate_settings(value, market["dates"])


@pytest.fixture
def service(tmp_path):
    config = json.loads((FOURTH / "protocol.json").read_text())
    config.update(top_n=3, min_history=30)
    rng = np.random.default_rng(42)
    close = pd.DataFrame(10 * np.exp(rng.normal(0, .02, (180, 10)).cumsum(axis=0)),
                         index=pd.bdate_range("2025-01-01", periods=180), columns=[f"S{i}" for i in range(10)])
    panels = {"close": close, "open": close * .999, "high": close * 1.01, "low": close * .99,
              "cumadj": close * 0 + 1, "amt": close * 0 + 1e8, "num_trades": close * 0 + 1000}
    wb = FactorWorkbench("unused", tmp_path / "backtests", load=False)
    wb.defaults, wb.panels, wb.market, wb.ready = config, {**panels, "source": {"sha256": "synthetic"}}, prepare(panels, config), True
    return FactorService(wb, tmp_path / "factors")


def wait(service):
    deadline = time.monotonic() + 15
    while service.wb.busy and time.monotonic() < deadline:
        time.sleep(.01)
    assert not service.wb.busy
    assert service.wb.error is None, service.wb.error


def test_factor_http_exports_and_exact_backtest_bridge(service):
    client = create_app(service).test_client()
    assert client.get("/").status_code == client.get("/backtest").status_code == 200
    assert "作业报告" not in client.get("/").text
    assert "课程作业简报" not in client.get("/backtest").text
    for path in ("/factor-report", "/report", "/assignment/report.html"):
        assert client.get(path).status_code == 404
    body = {"factor": "custom", "formula": "-returns(close, 5)", "condition": "close > ts_mean(close, 20)",
            "start": "2025-04-01", "end": "2025-08-15", "horizons": [1, 5], "min_pairs": 3, "direction": -1}
    response = client.post("/api/factors/run", json=body)
    assert response.status_code == 202
    run_id = response.json["id"]
    wait(service)
    result = client.get(f"/api/factors/result/{run_id}").json
    assert len(result["summary"]) == 2 and result["settings"]["source_sha256"] == "synthetic"
    assert client.get(f"/api/factors/export/{run_id}/daily").headers["Content-Type"].startswith("text/csv")
    assert client.get(f"/api/factors/export/{run_id}/private").status_code == 400
    assert client.get("/api/factors/result/unknown").status_code == 400
    assert client.post("/api/factors/run", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    response = client.post(f"/api/factors/backtest/{run_id}", json={})
    assert response.status_code == 202
    backtest_id = response.json["id"]
    wait(service)
    actual = service.wb.frame(backtest_id, "daily")
    # Negative direction must flow into real holdings, not just the displayed IC.
    original = Workbench("unused", service.runtime / "reference", load=False)
    original.defaults, original.market, original.panels, original.ready = service.wb.defaults, service.wb.market, service.wb.panels, True
    expected_id = original.submit({"strategy": "custom", "formula": "returns(close, 5)", "condition": body["condition"],
                                   "start": body["start"], "end": body["end"]})
    deadline = time.monotonic() + 15
    while original.busy and time.monotonic() < deadline:
        time.sleep(.01)
    assert original.error is None
    np.testing.assert_allclose(actual.equity, original.frame(expected_id, "daily").equity)
    assert client.get(f"/api/result/{backtest_id}").status_code == 200


def test_formula_rejection_controls_and_busy(service):
    client = create_app(service).test_client()
    base = {"factor": "custom", "formula": "lag(close, -1)", "start": "2025-04-01", "end": "2025-08-15"}
    assert client.post("/api/factors/run", json=base).status_code == 400
    assert client.post("/api/factors/run", json={**base, "factor": "unknown"}).status_code == 400
    response = client.post("/api/factors/run", json={**base, "factor": "constant_control"})
    wait(service)
    assert client.post(f"/api/factors/backtest/{response.json['id']}", json={}).status_code == 400
    service.wb.busy = True
    assert client.post("/api/factors/run", json={}).status_code == 400
