import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mining import PROTOCOL, block_excess, by_adjust, rank_correlation, residualize, select_candidates
from shared import evaluate, validate_expression


def test_by_adjust_known_values_and_missing():
    np.testing.assert_allclose(by_adjust([.01, .04, .03]), [.055, .073333333333, .073333333333])
    assert np.isnan(by_adjust([np.nan])[0])


def test_selection_uses_development_validation_and_redundancy_only():
    names = ["a", "b", "c", "old"]
    dev = pd.DataFrame({"factor": names, "rank_ic_mean": [.1, .1, -.1, .1], "spread_mean": [.01] * 4})
    val = pd.DataFrame({"factor": names, "rank_ic_ci_low": [.09, .08, .07, .2], "rank_ic_mean": [.1] * 4,
                        "spread_mean": [.01] * 4, "factor_coverage": [1.] * 4,
                        "label_coverage": [1.] * 4, "by_q": [.01] * 4})
    correlation = pd.DataFrame(np.eye(4), index=names, columns=names)
    correlation.loc["a", "b"] = correlation.loc["b", "a"] = .95
    selected, decisions = select_candidates(dev, val, correlation, ["a", "b", "c"], PROTOCOL["selection"])
    assert selected == ["a"]
    assert decisions.set_index("factor").loc["b", "decision"] == "redundant or unavailable correlation"
    dev["rank_ic_mean"] = -.1
    assert select_candidates(dev, val, correlation, ["a", "b", "c"], PROTOCOL["selection"])[0] == []


def test_proxy_residuals_remove_known_exposure_and_do_not_use_future():
    rng = np.random.default_rng(4)
    x = rng.normal(size=(60, 100))
    y = 2 * x + 3
    eligible = np.ones_like(x, dtype=bool)
    assert np.isnan(residualize(y, [x], eligible)).all()
    mixed = y + rng.normal(size=y.shape)
    actual = residualize(mixed, [x], eligible)
    np.testing.assert_allclose(actual[:30], residualize(mixed[:30], [x[:30]], eligible[:30]), equal_nan=True)
    np.testing.assert_allclose(np.nanmean(actual, axis=1), 0, atol=1e-7)


def test_common_cross_section_correlation_ties_and_missing():
    base = np.tile(np.arange(40, dtype=float), (2, 1))
    score = {"a": base, "b": -base, "c": np.ones_like(base)}
    matrix, coverage = rank_correlation(score, np.ones_like(base, dtype=bool), list(score))
    assert matrix.loc["a", "b"] == pytest.approx(-1)
    assert np.isnan(matrix.loc["a", "c"])
    assert coverage.common_count.eq(40).all()


def test_paired_block_bootstrap_and_alignment():
    result = block_excess(np.ones(60) * .002, np.ones(60) * .001, 20, 100, 1)
    assert result["annual_arithmetic_excess"] == pytest.approx(.252)
    assert result["excess_ci_low"] == pytest.approx(.252)
    with pytest.raises(ValueError):
        block_excess(np.array([np.nan] * 60), np.zeros(60), 20, 100, 1)


def test_all_new_formulas_are_causal_and_parser_supported():
    rng = np.random.default_rng(1)
    close = pd.DataFrame(np.exp(rng.normal(0, .01, (150, 35)).cumsum(axis=0)) * 10)
    panels = {"close": close, "open": close * .99, "low": close * .97, "high": close * 1.01,
              "amt": close * 1e7, "num_trades": close * 1e3, "cumadj": close * 0 + 1}
    market = {"close": close, "eligible": np.ones(close.shape, dtype=bool)}
    for formula in PROTOCOL["new_candidates"].values():
        validate_expression(formula)
        result = evaluate(formula, panels, market)
        prefix = evaluate(formula, {k: v.iloc[:130] for k, v in panels.items()},
                          {"close": close.iloc[:130], "eligible": market["eligible"][:130]})
        np.testing.assert_allclose(result[:130], prefix, equal_nan=True)
