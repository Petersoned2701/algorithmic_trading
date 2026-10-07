import copy
import logging

import polars as pl
import pytest

from options_bt.data.market import MarketData
from options_bt.data.store import QuoteStore
from options_bt.errors import ConfigError
from options_bt.sweep import expand, robustness, run_sweep
from tests.helpers import PCS_NO_FILTERS


def sweepable_pcs(profit: list) -> dict:
    raw = copy.deepcopy(PCS_NO_FILTERS)
    raw["entry"]["schedule"] = {}
    raw["entry"]["max_open_positions"] = 1
    raw["account"] = {"initial_cash": 100_000}
    raw["exits"] = {"profit_target_pct": {"sweep": profit}}
    return raw


def test_expand_marker_not_plain_lists():
    raw = {
        "underlyings": ["SPY"],
        "exits": {"profit_target_pct": {"sweep": [25, 50]}, "dte_exit": {"sweep": [14, 21]}},
        "entry": {"legs": [{"dte": [30, 45]}]},
    }
    grid, combos = expand(raw)
    assert grid == {"exits.profit_target_pct": [25, 50], "exits.dte_exit": [14, 21]}
    assert len(combos) == 4 and combos[0][1]["entry"]["legs"][0]["dte"] == [30, 45]


def test_expand_product_order_params_and_concrete_values():
    raw = {"a": {"sweep": [1, 2]}, "b": {"sweep": ["x", "y"]}}
    _, combos = expand(raw)
    assert [params for params, _ in combos] == [
        {"a": 1, "b": "x"},
        {"a": 1, "b": "y"},
        {"a": 2, "b": "x"},
        {"a": 2, "b": "y"},
    ]
    assert combos[3][1] == {"a": 2, "b": "y"}


def test_expand_list_index_path_and_no_mutation():
    raw = {"entry": {"legs": [{"delta": {"sweep": [0.2, 0.3]}}, {"delta": 0.1}]}}
    original = copy.deepcopy(raw)
    grid, combos = expand(raw)
    assert grid == {"entry.legs.0.delta": [0.2, 0.3]}
    assert combos[1][1]["entry"]["legs"] == [{"delta": 0.3}, {"delta": 0.1}]
    assert raw == original


def test_expand_without_markers_is_single_combination():
    raw = {"a": 1, "b": [1, 2]}
    grid, combos = expand(raw)
    assert grid == {} and combos == [({}, raw)]
    assert combos[0][1] is not raw


def test_expand_empty_sweep_names_path():
    with pytest.raises(ConfigError, match="exits.profit_target_pct"):
        expand({"exits": {"profit_target_pct": {"sweep": []}}})


def test_expand_dict_with_extra_keys_is_not_a_marker():
    raw = {"a": {"sweep": [1, 2], "other": 3}}
    grid, combos = expand(raw)
    assert grid == {} and combos == [({}, raw)]


def test_robustness():
    grid = {"a": [1, 2, 3]}
    rows = [
        {"a": 1, "net_return": 0.1, "annualized_return": 0.05},
        {"a": 2, "net_return": 0.2, "annualized_return": 0.09},
        {"a": 3, "net_return": -0.1, "annualized_return": -0.02},
    ]
    assert robustness(rows, grid) == pytest.approx(0.5)


def test_robustness_two_axes_uses_chebyshev_neighbours():
    grid = {"a": [1, 2, 3], "b": [10, 20, 30]}
    rows = [
        {"a": a, "b": b, "net_return": 0.1 if (a, b) != (3, 30) else -0.1, "annualized_return": 0.0}
        for a in grid["a"]
        for b in grid["b"]
    ]
    rows[4]["annualized_return"] = 1.0
    rows[0]["net_return"] = -0.1
    # best is (2, 20): its 8 neighbours include (1, 10) and (3, 30), both negative
    assert robustness(rows, grid) == pytest.approx(6 / 8)


def test_robustness_ties_first_in_order_and_none_excluded():
    grid = {"a": [1, 2, 3]}
    rows = [
        {"a": 1, "net_return": -0.1, "annualized_return": None},
        {"a": 2, "net_return": 0.2, "annualized_return": 0.1},
        {"a": 3, "net_return": -0.2, "annualized_return": 0.1},
    ]
    # best is a=2 (first of the tie); neighbours a=1 (negative) and a=3 (negative)
    assert robustness(rows, grid) == pytest.approx(0.0)


def test_robustness_none_without_neighbours_or_candidates():
    assert robustness([{"a": 1, "net_return": 0.1, "annualized_return": 0.1}], {"a": [1]}) is None
    assert robustness([{"a": 1, "net_return": 0.1, "annualized_return": None}], {"a": [1]}) is None


def test_run_sweep_rows(tmp_path, make_store):
    raw = sweepable_pcs(profit=[25, 50])
    df = run_sweep(raw, QuoteStore(make_store({"SPY": [100.0] * 20})), MarketData({}), tmp_path)
    assert df.height == 2 and (tmp_path / "sweep_results.csv").exists()


def test_run_sweep_columns_parquet_and_progress_log(tmp_path, make_store, caplog):
    raw = sweepable_pcs(profit=[25, 50])
    original = copy.deepcopy(raw)
    store = QuoteStore(make_store({"SPY": [100.0] * 20}))
    with caplog.at_level(logging.INFO, logger="options_bt.sweep"):
        df = run_sweep(raw, store, MarketData({}), tmp_path)
    assert df.columns == [
        "exits.profit_target_pct",
        "net_return",
        "annualized_return",
        "max_drawdown",
        "sharpe",
        "trades",
    ]
    assert df["exits.profit_target_pct"].to_list() == [25, 50]
    assert pl.read_parquet(tmp_path / "sweep_results.parquet").height == 2
    assert "sweep 2/2 {'exits.profit_target_pct': 50}" in caplog.text
    assert raw == original


def test_run_sweep_invalid_combination_fails_fast_naming_params(tmp_path, make_store):
    raw = sweepable_pcs(profit=[25, "bad"])
    store = QuoteStore(make_store({"SPY": [100.0] * 20}))
    with pytest.raises(ConfigError, match=r"exits.profit_target_pct.*bad"):
        run_sweep(raw, store, MarketData({}), tmp_path)
