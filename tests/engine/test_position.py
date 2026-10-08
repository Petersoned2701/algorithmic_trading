from datetime import UTC, datetime

import pytest

from options_bt.engine.position import (
    Position,
    format_legs,
    leg_value,
    max_loss,
    payoff_at_expiry,
)
from tests.helpers import E1, E2, L


def test_put_credit_spread_max_loss():
    legs = [L(-1, "P", 95), L(1, "P", 90)]
    assert max_loss(legs, net_premium=100.0) == 400.0  # 5-wide, $1.00 credit


def test_iron_condor_max_loss_is_one_wing():
    legs = [L(-1, "P", 95), L(1, "P", 90), L(-1, "C", 105), L(1, "C", 110)]
    assert max_loss(legs, net_premium=150.0) == 350.0


def test_long_butterfly_max_loss_is_debit():
    legs = [L(1, "C", 95), L(-2, "C", 100), L(1, "C", 105)]
    assert max_loss(legs, net_premium=-120.0) == 120.0


def test_naked_put_and_call_are_unbounded_or_large():
    assert max_loss([L(-1, "C", 100)], 200.0) is None
    assert max_loss([L(-1, "P", 100)], 200.0) == 9800.0  # bounded at spot 0


def test_calendar_and_diagonal():
    assert max_loss([L(-1, "P", 100, E1), L(1, "P", 100, E2)], -150.0) == 150.0
    assert max_loss([L(-1, "P", 100, E1), L(1, "P", 95, E2)], -50.0) == 550.0
    assert max_loss([L(-1, "P", 100, E2), L(1, "P", 100, E1)], 50.0) is None


def test_leg_value_sign_convention():
    legs = [L(-1, "P", 95), L(1, "P", 90)]
    assert leg_value(legs, [2.0, 1.0]) == -100.0


def test_payoff_at_expiry_is_intrinsic_only():
    legs = [L(-1, "P", 95), L(1, "P", 90)]
    assert payoff_at_expiry(legs, 100.0) == 0.0
    assert payoff_at_expiry(legs, 92.0) == -300.0
    assert payoff_at_expiry(legs, 80.0) == -500.0
    assert payoff_at_expiry([L(2, "C", 100)], 103.0) == 600.0


def test_net_short_calls_unbounded_even_when_hedged_by_puts():
    legs = [L(-2, "C", 100), L(1, "C", 105), L(1, "P", 90)]
    assert max_loss(legs, 100.0) is None


@pytest.mark.parametrize(
    "legs",
    [
        [L(-2, "P", 100, E1), L(1, "P", 95, E2)],  # short without a matching long
        [L(-1, "P", 100, E1), L(-1, "P", 100, E1), L(1, "P", 95, E2)],  # each long covers one short
    ],
)
def test_multi_expiry_uncovered_short_is_unbounded(legs):
    assert max_loss(legs, 0.0) is None


def test_multi_expiry_call_gap_and_floor_at_zero():
    legs = [L(-1, "C", 100, E1), L(1, "C", 105, E2)]
    assert max_loss(legs, 100.0) == 400.0
    assert max_loss([L(-1, "C", 100, E1), L(1, "C", 95, E2)], 100.0) == 0.0


def test_multi_expiry_without_shorts_is_net_debit():
    legs = [L(1, "C", 100, E1), L(1, "C", 100, E2)]
    assert max_loss(legs, -300.0) == 300.0
    assert max_loss(legs, 50.0) == 0.0


def test_position_earliest_expiration_and_defaults():
    pos = Position(
        id=1,
        underlying="SPY",
        legs=[L(-1, "P", 100, E2), L(1, "P", 95, E1)],
        quantity=1,
        opened_ts=datetime(2024, 1, 2, 15, tzinfo=UTC),
        entry_net=50.0,
        commissions=1.3,
        max_loss=450.0,
    )
    assert pos.earliest_expiration == E1
    assert pos.realized == 0.0
    assert pos.tags == {}


def test_format_legs_matches_trade_record_format():
    legs = [L(-1, "P", 95), L(1, "P", 90)]
    assert format_legs(legs) == "-1 P 95.0 2024-02-16, +1 P 90.0 2024-02-16"
