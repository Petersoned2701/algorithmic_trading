import pytest

from options_bt.data.chain import index_quotes
from options_bt.execution.costs import commission
from options_bt.execution.fills import FillModel, mid_prices
from tests.helpers import L


def test_fraction_half_is_mid_and_one_is_cross():
    assert FillModel(override=0.5).leg_price(1.0, 1.2, True, 2) == pytest.approx(1.1)
    assert FillModel(override=1.0).leg_price(1.0, 1.2, False, 2) == pytest.approx(1.0)


def test_two_leg_default_fraction():
    assert FillModel().leg_price(1.0, 2.0, True, 2) == pytest.approx(1.66)
    assert FillModel().leg_price(1.0, 2.0, False, 2) == pytest.approx(1.34)


def test_more_than_four_legs_uses_largest_key():
    assert FillModel().fraction(6) == 0.53


def test_prices_none_when_quote_missing(spy_chain):
    leg = L(-1, "P", 12345.0)
    assert FillModel().prices(index_quotes(spy_chain), [leg], opening=True) is None


def _existing_legs(chain):
    row = chain.row(0, named=True)
    strike, exp = row["strike"], row["expiration"]
    return (
        L(1, "C", strike, exp, underlying=row["underlying"]),
        L(-1, "C", strike, exp, underlying=row["underlying"]),
        row,
    )


def test_prices_opening_buys_longs_and_sells_shorts(spy_chain):
    long, short, row = _existing_legs(spy_chain)
    bid, ask = row["bid"], row["ask"]
    spread = ask - bid
    opening = FillModel().prices(index_quotes(spy_chain), [long, short], opening=True)
    assert opening == pytest.approx([bid + 0.66 * spread, ask - 0.66 * spread])


def test_prices_closing_reverses_sides(spy_chain):
    long, short, _ = _existing_legs(spy_chain)
    model = FillModel()
    opening = model.prices(index_quotes(spy_chain), [long, short], opening=True)
    closing = model.prices(index_quotes(spy_chain), [long, short], opening=False)
    assert closing == pytest.approx([opening[1], opening[0]])


def test_mid_prices(spy_chain):
    long, short, row = _existing_legs(spy_chain)
    mid = (row["bid"] + row["ask"]) / 2
    assert mid_prices(index_quotes(spy_chain), [long, short]) == pytest.approx([mid, mid])
    assert mid_prices(index_quotes(spy_chain), [long, L(1, "P", 12345.0)]) is None


def test_commission():
    assert commission([L(-1, "P", 95), L(1, "P", 90)], 3, 0.65, 1.0) == pytest.approx(4.9)
