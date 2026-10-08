import copy
from datetime import time
from pathlib import Path

import pytest
import yaml

from options_bt.errors import ConfigError
from options_bt.execution.fills import DEFAULT_FILL_FRACTION
from options_bt.loaders import load_yaml
from options_bt.strategy.config import parse_config
from tests.helpers import PCS, PCS_NO_FILTERS


def _set(raw, path, value):
    """Deep copy of `raw` with `value` at `path`, creating missing dicts on the way."""
    raw = copy.deepcopy(raw)
    target = raw
    for key in path[:-1]:
        if isinstance(target, dict):
            target.setdefault(key, {})
        target = target[key]
    target[path[-1]] = value
    return raw


def test_example_config_parses_with_expected_values():
    cfg = parse_config(PCS)
    assert cfg.entry.legs[0].right == "P" and cfg.entry.legs[1].ref == 0
    assert cfg.entry.legs[0].dte == (30, 45)
    assert cfg.entry.schedule.weekdays == ["MON", "THU"]
    assert cfg.account.initial_cash == 15000.0
    assert cfg.account.session_close == time(15, 45)
    assert cfg.margin_model == "defined_risk"
    assert cfg.costs.fill_fraction == DEFAULT_FILL_FRACTION
    assert parse_config(PCS_NO_FILTERS).entry.filters == []


@pytest.mark.parametrize("right", ["put", "P", "call", "C"])
def test_right_is_normalised(right):
    raw = _set(
        _set(PCS, ["entry", "legs", 0, "right"], right), ["entry", "legs", 1, "right"], right
    )
    assert parse_config(raw).entry.legs[0].right == right[0].upper()


def test_bad_right_rejected():
    with pytest.raises(ConfigError, match="right"):
        parse_config(_set(PCS, ["entry", "legs", 0, "right"], "straddle"))


def test_typo_names_the_field():
    bad = {**PCS, "exits": {"profit_target_pc": 50}}
    with pytest.raises(ConfigError, match="profit_target_pc"):
        parse_config(bad)


def test_error_lists_dotted_loc_one_per_line():
    bad = _set(_set(PCS, ["exits"], {"profit_target_pc": 50}), ["sizing"], {})
    with pytest.raises(ConfigError) as exc:
        parse_config(bad)
    lines = str(exc.value).splitlines()
    assert any(line.startswith("exits.profit_target_pc: ") for line in lines)
    assert any(line.startswith("sizing.max_loss_pct_equity: ") for line in lines)


def test_leg_needs_selector():
    bad = copy.deepcopy(PCS)
    bad["entry"]["legs"][0].pop("delta")
    with pytest.raises(ConfigError, match="legs"):
        parse_config(bad)


def test_leg_rejects_both_selectors():
    bad = _set(_set(PCS, ["entry", "legs", 1, "delta"], 0.1), ["entry", "legs", 1, "dte"], [30, 45])
    with pytest.raises(ConfigError, match="legs"):
        parse_config(bad)


def test_ref_leg_may_carry_dte():
    cfg = parse_config(_set(PCS, ["entry", "legs", 1, "dte"], [60, 90]))
    assert cfg.entry.legs[1].dte == (60, 90)


def test_forward_ref_rejected():
    with pytest.raises(ConfigError, match="earlier"):
        parse_config(_set(PCS, ["entry", "legs", 1, "ref"], 1))


def test_ref_on_first_leg_rejected():
    leg = {"right": "put", "side": "long", "ref": 0, "strike_offset": -5}
    with pytest.raises(ConfigError, match="earlier"):
        parse_config(_set(PCS, ["entry", "legs"], [leg]))


@pytest.mark.parametrize("delta", [0, 1, -0.2, 1.5])
def test_delta_must_be_in_open_unit_interval(delta):
    with pytest.raises(ConfigError, match="delta"):
        parse_config(_set(PCS, ["entry", "legs", 0, "delta"], delta))


@pytest.mark.parametrize("dte", [[45, 30], [-1, 30]])
def test_dte_range_validated(dte):
    with pytest.raises(ConfigError, match="dte"):
        parse_config(_set(PCS, ["entry", "legs", 0, "dte"], dte))


def test_ratio_must_be_positive():
    with pytest.raises(ConfigError, match="ratio"):
        parse_config(_set(PCS, ["entry", "legs", 0, "ratio"], 0))


def test_entry_needs_a_leg():
    with pytest.raises(ConfigError, match="legs"):
        parse_config(_set(PCS, ["entry", "legs"], []))


def test_filter_needs_type():
    with pytest.raises(ConfigError, match="filters"):
        parse_config(_set(PCS, ["entry", "filters"], [{"min": 20}]))


def test_unknown_weekday_rejected():
    with pytest.raises(ConfigError, match="weekdays"):
        parse_config(_set(PCS, ["entry", "schedule", "weekdays"], ["SAT"]))


def _with_account(text):
    return _set(PCS, ["account"], yaml.safe_load(text))


def test_unquoted_session_close_is_rejected():
    with pytest.raises(ConfigError, match=r"account\.session_close: .*quote"):
        parse_config(_with_account("session_close: 15:45"))


def test_quoted_session_close_parses():
    cfg = parse_config(_with_account('session_close: "15:45"'))
    assert cfg.account.session_close == time(15, 45)


def test_tz_aware_session_close_rejected():
    with pytest.raises(ConfigError, match="session_close"):
        parse_config(_with_account('session_close: "15:45:00+00:00"'))


@pytest.mark.parametrize(
    "path, value",
    [
        (["sizing", "max_loss_pct_equity"], 0),
        (["sizing", "max_loss_pct_equity"], -1),
        (["sizing", "max_loss_pct_equity"], 101),
        (["portfolio_caps", "max_total_max_loss_pct"], 0),
        (["portfolio_caps", "max_total_max_loss_pct"], 100.5),
        (["exits", "profit_target_pct"], 0),
        (["exits", "profit_target_pct"], -50),
        (["exits", "stop_loss_multiple"], 0),
        (["exits", "stop_loss_multiple"], -2),
        (["exits", "dte_exit"], -1),
        (["underlyings"], []),
        (["costs", "fill_fraction"], {}),
        (["costs", "fill_fraction"], {0: 0.5}),
        (["costs", "fill_fraction"], {1: 1.5}),
        (["costs", "fill_fraction"], {1: -0.1}),
        (["costs", "fill_fraction_override"], 1.2),
        (["costs", "fill_fraction_override"], -0.1),
        (["costs", "commission_per_contract"], -0.65),
        (["costs", "per_order_fee"], -1),
        (["account", "initial_cash"], 0),
        (["account", "initial_cash"], -100),
    ],
)
def test_out_of_range_values_are_rejected(path, value):
    with pytest.raises(ConfigError, match=path[-1]):
        parse_config(_set(PCS, path, value))


@pytest.mark.parametrize(
    "path, value",
    [
        (["sizing", "max_loss_pct_equity"], 100),
        (["portfolio_caps", "max_total_max_loss_pct"], 100),
        (["exits", "dte_exit"], 0),
        (["costs", "fill_fraction_override"], 0),
        (["costs", "fill_fraction_override"], 1),
        (["costs", "commission_per_contract"], 0),
        (["costs", "fill_fraction"], {1: 1.0, 2: 0.0}),
    ],
)
def test_boundary_values_are_accepted(path, value):
    parse_config(_set(PCS, path, value))


def test_shipped_pcs_spy_config_parses():
    config = parse_config(load_yaml(Path("configs/pcs_spy_45dte.yaml")))
    assert config.name == "pcs_spy_45dte" and config.underlyings == ["SPY"]
