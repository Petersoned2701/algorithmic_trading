import logging

import pytest

from options_bt.errors import ConfigError
from options_bt.risk.margin import DefinedRiskMargin, margin_model
from options_bt.risk.sizing import size
from tests.helpers import L


def _size(req, **kw):
    params = dict(
        equity=100_000,
        cash=100_000,
        current_requirement=0,
        max_loss_pct_equity=2.0,
        max_total_max_loss_pct=15,
    )
    return size(req, **{**params, **kw})


def test_size_by_max_loss_pct():
    assert _size(400.0, equity=20_000, cash=20_000) == (1, None)


def test_capped_by_portfolio_total():
    assert _size(400.0, current_requirement=14_000, max_loss_pct_equity=5.0) == (2, None)


def test_small_account_rejected_size_zero():
    assert _size(400.0, equity=5_000, cash=5_000) == (0, "size_zero")


def test_undefined_risk_rejected_by_defined_risk_margin():
    req = DefinedRiskMargin().requirement([L(-1, "C", 100)], 200.0)
    assert _size(req, equity=1e6, cash=1e6) == (0, "undefined_risk")


def test_unknown_margin_model():
    with pytest.raises(ConfigError):
        margin_model("reg_t")


def test_defined_risk_margin_is_max_loss_of_spread():
    legs = [L(-1, "P", 100), L(1, "P", 95)]
    # credit of $150 on a $5 wide spread: max loss = 500 - 150
    assert DefinedRiskMargin().requirement(legs, 150.0) == pytest.approx(350.0)
    assert isinstance(margin_model("defined_risk"), DefinedRiskMargin)


def test_portfolio_cap_exhausted():
    assert _size(400.0, current_requirement=15_000) == (0, "portfolio_cap")
    assert _size(400.0, current_requirement=16_000) == (0, "portfolio_cap")


def test_room_below_one_unit_is_portfolio_cap():
    assert _size(400.0, current_requirement=14_800) == (0, "portfolio_cap")


def test_insufficient_cash():
    assert _size(400.0, cash=300.0) == (0, "insufficient_cash")


def test_capped_by_cash():
    assert _size(400.0, cash=1_000.0) == (2, None)


@pytest.mark.parametrize("req", [0.0, -50.0])
def test_non_positive_requirement_is_size_zero(req, caplog):
    with caplog.at_level(logging.DEBUG, logger="options_bt.risk.sizing"):
        assert _size(req) == (0, "size_zero")
    assert any(r.levelno == logging.DEBUG for r in caplog.records)


def test_exact_boundary_is_not_undersized_by_float_error():
    assert _size(350.0, equity=50_000, cash=50_000, max_loss_pct_equity=0.7) == (1, None)
