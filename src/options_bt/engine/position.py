import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from options_bt.data.chain import ContractKey

log = logging.getLogger(__name__)


@dataclass
class Leg:
    key: ContractKey
    qty: int
    style: str
    settlement: str
    multiplier: int = 100
    entry_price: float = 0.0


@dataclass
class Position:
    id: int
    underlying: str
    legs: list[Leg]
    quantity: int
    opened_ts: datetime
    entry_net: float
    commissions: float
    max_loss: float | None
    realized: float = 0.0
    tags: dict = field(default_factory=dict)

    @property
    def earliest_expiration(self) -> date:
        return min(leg.key.expiration for leg in self.legs)


@dataclass
class TradeRecord:
    position_id: int
    underlying: str
    opened_ts: datetime
    closed_ts: datetime
    legs: str
    quantity: int
    entry_net: float
    exit_value: float
    commissions: float
    pnl: float
    exit_reason: str
    max_loss: float | None


def leg_value(legs: Sequence[Leg], prices: Sequence[float]) -> float:
    return sum(leg.qty * price * leg.multiplier for leg, price in zip(legs, prices, strict=True))


def _intrinsic(leg: Leg, spot: float) -> float:
    if leg.key.right == "C":
        return max(spot - leg.key.strike, 0.0)
    return max(leg.key.strike - spot, 0.0)


def payoff_at_expiry(legs: Sequence[Leg], spot: float) -> float:
    """Dollars per unit at `spot`, intrinsic value only (premium excluded)."""
    return sum(leg.qty * _intrinsic(leg, spot) * leg.multiplier for leg in legs)


def max_loss(legs: Sequence[Leg], net_premium: float) -> float | None:
    """Worst-case loss in dollars per unit (>= 0), or None if unbounded or unprovable.

    `net_premium` is dollars per unit, positive for a credit.
    """
    if len({leg.key.expiration for leg in legs}) == 1:
        return _single_expiry_max_loss(legs, net_premium)
    return _multi_expiry_max_loss(legs, net_premium)


def _single_expiry_max_loss(legs: Sequence[Leg], net_premium: float) -> float | None:
    if sum(leg.qty for leg in legs if leg.key.right == "C") < 0:
        return None
    spots = [0.0, *(leg.key.strike for leg in legs)]
    worst = min(payoff_at_expiry(legs, s) + net_premium for s in spots)
    return round(max(0.0, -worst), 6)


def _multi_expiry_max_loss(legs: Sequence[Leg], net_premium: float) -> float | None:
    longs = [leg for leg in legs if leg.qty > 0]
    used: set[int] = set()
    gap_total = 0.0
    for short in (leg for leg in legs if leg.qty < 0):
        match = next(
            (
                i
                for i, long in enumerate(longs)
                if i not in used
                and long.key.right == short.key.right
                and long.qty >= -short.qty
                and long.key.expiration >= short.key.expiration
            ),
            None,
        )
        if match is None:
            return None
        used.add(match)
        long = longs[match]
        if short.key.right == "P":
            gap = max(0.0, short.key.strike - long.key.strike)
        else:
            gap = max(0.0, long.key.strike - short.key.strike)
        gap_total += gap * -short.qty * short.multiplier
    return round(max(0.0, gap_total - net_premium), 6)


def format_legs(legs: Sequence[Leg]) -> str:
    return ", ".join(
        f"{leg.qty:+d} {leg.key.right} {leg.key.strike} {leg.key.expiration.isoformat()}"
        for leg in legs
    )
