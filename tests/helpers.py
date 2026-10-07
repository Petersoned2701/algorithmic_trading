"""Shared test helpers."""

from datetime import date, datetime

from options_bt.data.chain import ContractKey
from options_bt.data.schema import snapshot_ts
from options_bt.engine.position import Leg

E1 = date(2024, 2, 16)
E2 = date(2024, 3, 15)

T0 = snapshot_ts(date(2024, 1, 2))
T1 = snapshot_ts(date(2024, 1, 3))
EXPIRY_TS = snapshot_ts(E1)


def expiry_ts(d: date) -> datetime:
    return snapshot_ts(d)


def L(
    qty: int,
    right: str,
    strike: float,
    exp: date = E1,
    *,
    price: float = 0.0,
    underlying: str = "SPY",
    style: str = "american",
    settlement: str = "physical",
) -> Leg:
    return Leg(
        key=ContractKey(underlying, exp, float(strike), right),
        qty=qty,
        style=style,
        settlement=settlement,
        entry_price=price,
    )
