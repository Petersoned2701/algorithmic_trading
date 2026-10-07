from datetime import date

import polars as pl
import pytest

from options_bt.errors import NoContractFound
from options_bt.strategy.config import LegSpec, parse_config
from options_bt.strategy.selectors import select_legs
from tests.helpers import PCS, TS, TS_DATE

PCS_SPECS = parse_config(PCS).entry.legs


def _chain(rows: list[tuple[date, float, str, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "underlying": ["SPY"] * len(rows),
            "expiration": [r[0] for r in rows],
            "strike": [r[1] for r in rows],
            "right": [r[2] for r in rows],
            "style": ["american"] * len(rows),
            "settlement": ["physical"] * len(rows),
            "delta": [r[3] for r in rows],
            "multiplier": [100] * len(rows),
        }
    )


def test_put_credit_spread_selection(spy_chain):
    legs = select_legs(spy_chain, PCS_SPECS, TS)
    short, long = legs
    assert short.qty == -1 and long.qty == 1
    assert long.key.strike == short.key.strike - 5
    assert 30 <= (short.key.expiration - TS_DATE).days <= 45
    assert long.key.expiration == short.key.expiration
    assert short.entry_price == long.entry_price == 0.0


def test_short_leg_delta_is_closest_to_target(spy_chain):
    short, _ = select_legs(spy_chain, PCS_SPECS, TS)
    puts = spy_chain.filter(
        (pl.col("expiration") == short.key.expiration) & (pl.col("right") == "P")
    )
    errors = puts.select(strike="strike", err=(pl.col("delta").abs() - 0.25).abs()).sort("err")
    assert short.key.strike == errors["strike"][0]


def test_expiration_closest_to_midpoint(spy_chain):
    short, _ = select_legs(spy_chain, PCS_SPECS, TS)
    assert (short.key.expiration - TS_DATE).days == 38


def test_expiration_midpoint_tie_goes_to_earlier():
    chain = _chain(
        [
            (date(2024, 1, 12), 100.0, "P", -0.25),
            (date(2024, 1, 16), 100.0, "P", -0.25),
        ]
    )
    spec = LegSpec(right="P", side="short", dte=(10, 14), delta=0.25)
    (leg,) = select_legs(chain, [spec], TS)
    assert leg.key.expiration == date(2024, 1, 12)


def test_delta_tie_picks_lower_strike_for_puts_higher_for_calls():
    exp = date(2024, 2, 9)
    chain = _chain(
        [
            (exp, 95.0, "P", -0.20),
            (exp, 96.0, "P", -0.30),
            (exp, 104.0, "C", 0.20),
            (exp, 105.0, "C", 0.30),
        ]
    )
    put = LegSpec(right="P", side="short", dte=(30, 45), delta=0.25)
    call = LegSpec(right="C", side="short", dte=(30, 45), delta=0.25)
    (p,) = select_legs(chain, [put], TS)
    (c,) = select_legs(chain, [call], TS)
    assert p.key.strike == 95.0
    assert c.key.strike == 105.0


def test_leg_attributes_come_from_chain_row():
    exp = date(2024, 2, 9)
    chain = _chain([(exp, 100.0, "C", 0.25)]).with_columns(
        style=pl.lit("european"), settlement=pl.lit("cash"), multiplier=pl.lit(50)
    )
    spec = LegSpec(right="C", side="long", ratio=2, dte=(30, 45), delta=0.25)
    (leg,) = select_legs(chain, [spec], TS)
    assert (leg.qty, leg.style, leg.settlement, leg.multiplier) == (2, "european", "cash", 50)
    assert leg.key.underlying == "SPY" and leg.key.right == "C"


def test_ref_leg_uses_dte_rule_when_given(spy_chain):
    specs = [
        PCS_SPECS[0],
        LegSpec(right="P", side="long", dte=(60, 70), ref=0, strike_offset=-5),
    ]
    short, long = select_legs(spy_chain, specs, TS)
    assert (long.key.expiration - TS_DATE).days > (short.key.expiration - TS_DATE).days
    assert long.key.strike == short.key.strike - 5


def test_ref_to_earlier_ref_leg(spy_chain):
    specs = [
        *PCS_SPECS,
        LegSpec(right="P", side="long", ref=1, strike_offset=-5),
    ]
    short, long, wing = select_legs(spy_chain, specs, TS)
    assert wing.key.strike == long.key.strike - 5
    assert wing.key.expiration == short.key.expiration


def test_no_expiration_in_range_raises(spy_chain):
    spec = LegSpec(right="put", side="short", dte=(400, 500), delta=0.25)
    with pytest.raises(NoContractFound, match="leg 0"):
        select_legs(spy_chain, [spec], TS)


def test_no_strikes_for_right_raises():
    chain = _chain([(date(2024, 2, 9), 100.0, "C", 0.25)])
    spec = LegSpec(right="P", side="short", dte=(30, 45), delta=0.25)
    with pytest.raises(NoContractFound, match="leg 0"):
        select_legs(chain, [spec], TS)


def test_offset_outside_tolerance_raises(spy_chain):
    specs = [PCS_SPECS[0], LegSpec(right="put", side="long", ref=0, strike_offset=-0.3)]
    with pytest.raises(NoContractFound, match="leg 1"):
        select_legs(spy_chain, specs, TS)


def test_ref_strike_not_listed_raises():
    exp = date(2024, 2, 9)
    chain = _chain([(exp, 100.0, "P", -0.25), (exp, 90.0, "P", -0.10)])
    specs = [
        LegSpec(right="P", side="short", dte=(30, 45), delta=0.25),
        LegSpec(right="P", side="long", ref=0, strike_offset=-5),
    ]
    with pytest.raises(NoContractFound, match="leg 1"):
        select_legs(chain, specs, TS)
