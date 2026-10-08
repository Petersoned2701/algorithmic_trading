from datetime import date, time

import pytest

from options_bt.data.chain import ContractKey, index_quotes
from options_bt.data.schema import snapshot_ts
from options_bt.engine.portfolio import Portfolio
from options_bt.execution.settlement import intrinsic, is_due
from tests.helpers import E1, E2, EXPIRY_TS, T0, T1, L

CLOSE = time(15, 45)


class FakeModel:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def requirement(self, legs, net_premium):
        self.calls.append((legs, net_premium))
        return self.value


def _open(p, legs, quantity=1, commission=0.0, max_loss=None, *, tags=None, underlying="SPY"):
    """Open at the prices the test legs were built with (`L(..., price=)`)."""
    prices = [leg.entry_price for leg in legs]
    return p.open(
        underlying,
        legs,
        quantity,
        T0,
        prices=prices,
        commission=commission,
        max_loss=max_loss,
        tags=tags,
    )


def _open_pcs(qty=1, commission=0.0):
    """A $100-credit, $400-max-loss put spread on a fresh 10k portfolio."""
    p = Portfolio(10_000)
    legs = [L(-1, "P", 95, price=2.0), L(1, "P", 90, price=1.0)]
    return p, _open(p, legs, qty, commission, 400.0)


def test_open_close_cash_and_pnl():
    p, pos = _open_pcs(2, 2.6)
    assert p.cash == pytest.approx(10_000 + 200 - 2.6)
    tr = p.close(pos.id, [0.5, 0.2], T1, 2.6, "profit_target")
    assert tr.pnl == pytest.approx((100 - 30) * 2 - 5.2)
    assert p.cash == pytest.approx(10_000 + tr.pnl)
    assert tr.commissions == pytest.approx(5.2)
    assert tr.exit_value == pytest.approx(-30)
    assert tr.legs == "-1 P 95.0 2024-02-16, +1 P 90.0 2024-02-16"
    assert (tr.opened_ts, tr.closed_ts, tr.exit_reason, tr.max_loss) == (
        T0,
        T1,
        "profit_target",
        400.0,
    )
    assert p.positions == {} and p.trades == [tr]


def test_open_prices_legs_on_copies():
    p = Portfolio(10_000)
    legs = [L(-1, "P", 95), L(1, "P", 90)]
    pos = p.open("SPY", legs, 2, T0, prices=[2.0, 1.0], commission=2.6, max_loss=400.0, tags={})
    assert [leg.entry_price for leg in pos.legs] == [2.0, 1.0]
    assert [leg.entry_price for leg in legs] == [0.0, 0.0]
    assert pos.entry_net == pytest.approx(100.0)
    assert p.cash == pytest.approx(10_000 + 200 - 2.6)


def test_position_ids_are_sequential_from_one():
    p = Portfolio(10_000)
    a = _open(p, [L(-1, "P", 95, price=1.0)])
    b = _open(p, [L(-1, "P", 96, price=1.0)], tags={"k": "v"})
    assert (a.id, b.id) == (1, 2)
    assert b.tags == {"k": "v"}


def test_settlement_needs_only_spot_not_quote():
    p, _ = _open_pcs()
    trades = p.settle_expired(EXPIRY_TS, {"SPY": 92.0}, CLOSE)
    assert trades[0].pnl == pytest.approx(100 - 300)
    assert trades[0].exit_reason == "assignment"
    assert trades[0].closed_ts == EXPIRY_TS
    assert trades[0].exit_value == pytest.approx(-300)
    assert p.cash == pytest.approx(10_000 + 100 - 300)
    assert p.positions == {}


def test_out_of_the_money_expiry_is_expired():
    p, _ = _open_pcs()
    trades = p.settle_expired(EXPIRY_TS, {"SPY": 100.0}, CLOSE)
    assert trades[0].exit_reason == "expired"
    assert trades[0].pnl == pytest.approx(100)


def test_cash_settled_short_is_expired_not_assignment():
    p = Portfolio(10_000)
    _open(p, [L(-1, "P", 95, price=2.0, underlying="SPX", settlement="cash")], underlying="SPX")
    trades = p.settle_expired(EXPIRY_TS, {"SPX": 92.0}, CLOSE)
    assert trades[0].exit_reason == "expired"
    assert trades[0].pnl == pytest.approx(200 - 300)


def test_long_in_the_money_is_not_assignment():
    p = Portfolio(10_000)
    _open(p, [L(1, "P", 95, price=2.0)])
    trades = p.settle_expired(EXPIRY_TS, {"SPY": 92.0}, CLOSE)
    assert trades[0].exit_reason == "expired"
    assert trades[0].pnl == pytest.approx(-200 + 300)


def test_before_session_close_nothing_settles():
    p = Portfolio(10_000)
    _open(p, [L(-1, "P", 95, price=2.0)])
    early = snapshot_ts(E1, time(10, 0))
    assert p.settle_expired(early, {"SPY": 92.0}, CLOSE) == []
    assert len(p.positions) == 1


def test_holiday_expiration_settles_next_step():
    assert is_due(date(2024, 3, 29), snapshot_ts(date(2024, 4, 1)), CLOSE)
    assert not is_due(date(2024, 4, 5), snapshot_ts(date(2024, 4, 4)), CLOSE)


def test_is_due_same_day_depends_on_session_close():
    assert not is_due(E1, snapshot_ts(E1, time(15, 44)), CLOSE)
    assert is_due(E1, snapshot_ts(E1, CLOSE), CLOSE)


def test_intrinsic():
    assert intrinsic("C", 100, 105) == 5
    assert intrinsic("C", 100, 95) == 0
    assert intrinsic("P", 100, 95) == 5
    assert intrinsic("P", 100, 105) == 0


def test_calendar_front_leg_settles_back_leg_stays():
    p = Portfolio(10_000)
    pos = _open(p, [L(-1, "P", 100, E1, price=1.0), L(1, "P", 100, E2, price=2.5)], max_loss=150.0)
    assert p.settle_expired(EXPIRY_TS, {"SPY": 101.0}, CLOSE) == []
    assert len(p.positions[pos.id].legs) == 1
    tr = p.close(pos.id, [2.0], T1, 0.0, "time_exit")
    assert tr.legs == "-1 P 100.0 2024-02-16, +1 P 100.0 2024-03-15"
    assert tr.pnl == pytest.approx(-150 + 200)
    assert tr.exit_value == pytest.approx(200)
    assert p.cash == pytest.approx(10_000 + tr.pnl)


def test_partial_settlement_with_realized_loss_flows_into_pnl():
    p = Portfolio(10_000)
    legs = [L(-1, "P", 100, E1, price=1.0), L(1, "P", 100, E2, price=2.5)]
    pos = _open(p, legs, 2, 1.0, 150.0)
    p.settle_expired(EXPIRY_TS, {"SPY": 98.0}, CLOSE)
    assert pos.realized == pytest.approx(-400)
    tr = p.close(pos.id, [2.0], T1, 1.0, "time_exit")
    assert tr.pnl == pytest.approx(-150 * 2 + 200 * 2 - 400 - 2.0)
    assert p.cash == pytest.approx(10_000 + tr.pnl)
    assert tr.exit_value == pytest.approx(0.0)


def test_due_leg_without_spot_waits_for_a_step_that_has_it():
    p = Portfolio(10_000)
    pos = _open(
        p, [L(-1, "P", 100, price=1.0, underlying="SPX")], max_loss=9_900.0, underlying="SPX"
    )
    assert p.settle_expired(EXPIRY_TS, {"SPY": 90.0}, CLOSE) == []
    assert pos.id in p.positions and p.cash == pytest.approx(10_100)
    (tr,) = p.settle_expired(snapshot_ts(date(2024, 2, 20)), {"SPX": 92.0}, CLOSE)
    assert tr.pnl == pytest.approx(100 - 800)


def test_stale_mark_counted(spy_chain):
    p = Portfolio(10_000)
    _open(p, [L(-1, "P", 12345.0, price=2.0)])
    value, stale = p.mark({"SPY": index_quotes(spy_chain)})
    assert stale == 1 and value == pytest.approx(-200.0)


def test_mark_uses_mid_then_last_known_mid(spy_chain):
    row = spy_chain.row(0, named=True)
    key = ContractKey(row["underlying"], row["expiration"], row["strike"], row["right"])
    mid = (row["bid"] + row["ask"]) / 2
    leg = L(-1, row["right"], row["strike"], row["expiration"], price=0.01)
    assert leg.key == key
    p = Portfolio(10_000)
    _open(p, [leg], 3)
    value, stale = p.mark({"SPY": index_quotes(spy_chain)})
    assert stale == 0 and value == pytest.approx(-mid * 100 * 3)
    value, stale = p.mark({})
    assert stale == 1 and value == pytest.approx(-mid * 100 * 3)


def test_requirement_sums_model_over_positions_ignoring_none():
    p, _ = _open_pcs(3)
    model = FakeModel(400.0)
    assert p.requirement(model) == pytest.approx(1200.0)
    assert model.calls[0][1] == pytest.approx(100.0)
    assert p.requirement(FakeModel(None)) == 0.0
