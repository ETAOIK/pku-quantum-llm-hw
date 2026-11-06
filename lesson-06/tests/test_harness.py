import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harness
from harness import (HERE, Tools, aggregate, context_for, digest, fixed_controls, freeze, gate,
                     read, run_agent, validate_batch, write)


def candidate(name="c1", formula="-returns(close, 5)", parents=None):
    return dict(id=name, name=name, formula=formula, condition="True", top_n=50,
                rebalance_every=5, parents=parents or [], hypothesis="test hypothesis", change="test change")


@pytest.fixture
def context():
    return {"phase": "evolving", "next_generation": 0, "history": [], "protocol": read(HERE / "protocol.json")}


def proposal(context):
    return {"generation": context["next_generation"], "context_sha256": digest(context), "agent": "test-only stub",
            "candidates": [candidate(f"c{i}", f"-returns(close, {i+1})") for i in range(6)]}


def test_valid_proposal_and_structural_deduplication(context):
    batch = proposal(context)
    assert len(validate_batch(batch, context)) == 6
    batch["candidates"][1]["formula"] = " -returns(close, 1) "
    with pytest.raises(ValueError, match="Duplicate"):
        validate_batch(batch, context)


@pytest.mark.parametrize("change", ["stale", "future", "python", "fees", "strategy", "parent", "oversize", "budget"])
def test_reject_unsafe_or_out_of_contract_proposals(context, change):
    batch = proposal(context)
    if change == "stale":
        batch["context_sha256"] = "0" * 64
    elif change == "future":
        batch["candidates"][0]["formula"] = "lag(close, -1)"
    elif change == "python":
        batch["candidates"][0]["formula"] = "__import__('os').system('id')"
    elif change == "fees":
        batch["candidates"][0]["commission_bps"] = 0
    elif change == "strategy":
        batch["candidates"][0]["top_n"] = 1
    elif change == "parent":
        batch["candidates"][0]["parents"] = ["invented"]
    elif change == "oversize":
        batch["candidates"].append(candidate("extra"))
    elif change == "budget":
        context["next_generation"] = 3
        batch["generation"] = 3
        batch["context_sha256"] = digest(context)
    with pytest.raises(ValueError):
        validate_batch(batch, context)


def test_child_must_use_previously_evaluated_parent(context):
    parent = candidate("prior")
    context.update(next_generation=1, history=[parent])
    batch = proposal(context)
    for c in batch["candidates"]:
        c["parents"] = ["prior"]
    batch["candidates"][4]["formula"] = "-returns(close, 20)"
    validate_batch(batch, context)
    batch["candidates"][1]["parents"] = ["c0"]
    with pytest.raises(ValueError, match="earlier generations"):
        validate_batch(batch, context)


@pytest.mark.parametrize("value", [False, 0.0, "0"])
def test_generation_requires_exact_integer(context, value):
    batch = proposal(context)
    batch["generation"] = value
    with pytest.raises(ValueError, match="Wrong generation"):
        validate_batch(batch, context)


def test_unhashable_parent_rejected_as_contract_error(context):
    batch = proposal(context)
    batch["candidates"][0]["parents"] = [{}]
    with pytest.raises(ValueError, match="parents"):
        validate_batch(batch, context)


def test_gate_and_worst_fold_objective():
    rules = read(HERE / "protocol.json")["gate"]
    good = dict(rank_ic_mean=.02, spread_mean=.001, annual_excess=.1, max_drawdown=-.2,
                factor_coverage=.99, label_coverage=.99, pool_coverage=.9)
    assert gate([good, good], rules)
    assert not gate([good, {**good, "annual_excess": -.01}], rules)
    assert not gate([{**good, "rank_ic_mean": None}], rules)
    assert not gate([{**good, "pool_coverage": .1}], rules)
    assert aggregate([good, {**good, "annual_excess": -.1, "max_drawdown": -.4}], 20) == pytest.approx(-.202)


def test_controls_work_with_arbitrary_agent_ids_and_reserved_id_rejected(context):
    assert len(fixed_controls([candidate("any_name")])) == 3
    assert "any_name" in fixed_controls([candidate("any_name")])
    assert "baseline_lowvol60" in fixed_controls([])
    for name in ("equal_weight", "baseline_lowvol60"):
        batch = proposal(context)
        batch["candidates"][0]["id"] = name
        with pytest.raises(ValueError):
            validate_batch(batch, context)


def test_freeze_stops_mutation_and_seals_history(tmp_path):
    protocol = read(HERE / "protocol.json")
    history = [{**candidate(f"g{i}"), "generation": i, "development_pass": True, "objective": i / 10} for i in range(3)]
    write(tmp_path / "protocol.json", protocol)
    write(tmp_path / "state.json", {"phase": "evolving", "next_generation": 2, "history": history})
    with pytest.raises(ValueError):
        freeze(tmp_path)
    write(tmp_path / "state.json", {"phase": "evolving", "next_generation": 3, "history": history})
    freeze(tmp_path)
    assert read(tmp_path / "freeze.json")["history_sha256"] == digest(history)
    context = context_for(tmp_path)
    with pytest.raises(ValueError, match="frozen"):
        validate_batch(proposal(context), context)


def test_external_agent_protocol_and_bad_json(tmp_path, context):
    stub = tmp_path / "stub.py"
    stub.write_text("import json,sys\nx=json.load(sys.stdin)\nprint(json.dumps({'context_sha256':x['context_sha256']}))\n")
    assert run_agent([sys.executable, str(stub)], context)["context_sha256"] == digest(context)
    stub.write_text("print('not JSON')\n")
    with pytest.raises(json.JSONDecodeError):
        run_agent([sys.executable, str(stub)], context)


def synthetic_tools():
    tools = Tools.__new__(Tools)
    tools.protocol = read(HERE / "protocol.json")
    tools.config = read(HERE.parent / "lesson-04/assignment/protocol.json")
    rng = np.random.default_rng(8)
    dates = pd.bdate_range("2025-01-01", periods=100)
    prices = pd.DataFrame(10 * np.exp(rng.normal(0, .008, (100, 60)).cumsum(axis=0)), index=dates,
                          columns=[f"S{i}" for i in range(60)])
    tools.panels = {"close": prices, "open": prices, "high": prices * 1.02, "low": prices * .98,
                    "amt": prices * 1e8, "num_trades": prices * 100, "cumadj": prices * 0 + 1}
    tools.market = {"dates": dates, "symbols": prices.columns, "close": prices, "open": prices.to_numpy(),
                    "mark": prices.to_numpy(), "eligible": np.ones(prices.shape, bool), "gap": prices.to_numpy() * 0,
                    "amount20": prices * 1e8, "stale": np.zeros(prices.shape, int)}
    tools.state = np.ones(prices.shape, np.int8)
    tools.baselines = {}
    return tools


def test_real_engine_condition_and_future_perturbation():
    tools = synthetic_tools()
    period = ["2025-01-02", "2025-04-15"]
    c = candidate()
    first, daily = tools.run(c, period)
    altered = synthetic_tools()
    for key, frame in altered.panels.items():
        frame.loc["2025-04-16":] *= 5
    for key in ("open", "mark"):
        altered.market[key][75:] *= 5
    again, daily2 = altered.run(c, period)
    pd.testing.assert_frame_equal(daily, daily2)
    assert first["annual_excess"] == pytest.approx(again["annual_excess"])
    assert all(first["checks"].values())
    c["condition"] = "False"
    result, cash = tools.run(c, period)
    assert result["pool_coverage"] == 0
    assert cash.holdings.eq(0).all()
    assert cash.equity.eq(1e9).all()


def test_baseline_is_recomputed_for_capital_and_cost_scenario():
    tools = synthetic_tools()
    period = ["2025-01-02", "2025-04-15"]
    c = candidate()
    for scenario in ("base", "cost_stress", "small_cash"):
        result, daily = tools.run(c, period, scenario)
        baseline = tools.baselines[(tuple(period), scenario)]
        assert result["annual_excess"] == pytest.approx((daily["return"] - baseline["return"]).mean() * 252)
        assert len(baseline) == len(daily)
    assert tools.baselines[(tuple(period), "small_cash")].equity.iloc[0] < 2e6


def test_full_auto_loop_with_synthetic_data_and_stub_agent(tmp_path, monkeypatch):
    """Protocol integration only: the stub is explicitly not a real LLM experiment."""
    data, status, config, adapter = [tmp_path / name for name in ("data", "status", "protocol.json", "agent.py")]
    data.write_text("synthetic test only")
    status.write_text("synthetic test only")
    protocol = read(HERE / "protocol.json")
    protocol.update(generations=2, batch_size=2, shortlist_size=2,
                    development={"a": ["2025-01-02", "2025-01-31"], "b": ["2025-02-03", "2025-02-28"]},
                    validation=["2025-03-03", "2025-03-31"], followup=["2025-04-01", "2025-05-20"])
    write(config, protocol)
    def tool_factory(output, *_):
        tools = synthetic_tools()
        tools.protocol = read(output / "protocol.json")
        return tools
    monkeypatch.setattr(harness, "Tools", tool_factory)
    adapter.write_text("""import json,sys
x=json.load(sys.stdin); g=x['next_generation']; parents=[x['history'][0]['id']] if g else []
c=[dict(id=f'arbitrary_{g}_{i}',name='stub',formula=f'-returns(close, {1+g*2+i})',condition='False' if i else 'True',top_n=50,rebalance_every=5,parents=parents,hypothesis='stub',change='stub') for i in range(2)]
print(json.dumps(dict(generation=g,context_sha256=x['context_sha256'],agent='test-only stub, not LLM',candidates=c)))
""")
    output = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["harness.py", "auto", "--output", str(output), "--data", str(data), "--status", str(status),
                                     "--protocol", str(config), "--agent-command", json.dumps([sys.executable, str(adapter)])])
    harness.main()
    assert read(output / "state.json")["phase"] == "complete"
    assert len(read(output / "state.json")["history"]) == 4
    for folder in (output / "backtests").glob("*/*"):
        pd.read_csv(folder / "orders.csv.gz")
        pd.read_csv(folder / "holdings.csv.gz")
    assert "baseline_lowvol60" in pd.read_csv(output / "followup.csv").id.tolist()
