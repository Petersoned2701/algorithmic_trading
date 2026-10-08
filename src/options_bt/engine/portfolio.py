import logging
from collections.abc import Mapping
from datetime import datetime, time

from options_bt.data.chain import ContractKey, Quotes
from options_bt.engine.position import Leg, Position, TradeRecord, format_legs, leg_value
from options_bt.execution.fills import mid_prices
from options_bt.execution.settlement import intrinsic, is_due

log = logging.getLogger(__name__)


class Portfolio:
    def __init__(self, initial_cash: float):
        self.cash = initial_cash
        self.positions: dict[int, Position] = {}
        self.trades: list[TradeRecord] = []
        self._next_id = 1
        self._opened_legs: dict[int, str] = {}
        self._last_mid: dict[ContractKey, float] = {}

    def open(
        self,
        underlying: str,
        legs: list[Leg],
        quantity: int,
        ts: datetime,
        commission: float,
        max_loss: float | None,
        tags: dict,
    ) -> Position:
        entry_net = -leg_value(legs, [leg.entry_price for leg in legs])
        position = Position(
            id=self._next_id,
            underlying=underlying,
            legs=list(legs),
            quantity=quantity,
            opened_ts=ts,
            entry_net=entry_net,
            commissions=commission,
            max_loss=max_loss,
            tags=tags,
        )
        self._next_id += 1
        self.positions[position.id] = position
        self._opened_legs[position.id] = format_legs(legs)
        self.cash += entry_net * quantity - commission
        return position

    def close(
        self, position_id: int, prices: list[float], ts: datetime, commission: float, reason: str
    ) -> TradeRecord:
        position = self.positions[position_id]
        self.cash += leg_value(position.legs, prices) * position.quantity - commission
        position.commissions += commission
        return self._finish(position, prices, ts, reason)

    def settle_expired(
        self, ts: datetime, spots: Mapping[str, float], session_close: time
    ) -> list[TradeRecord]:
        closed = []
        for position in list(self.positions.values()):
            due = [
                leg
                for leg in position.legs
                if leg.key.underlying in spots and is_due(leg.key.expiration, ts, session_close)
            ]
            if not due:
                continue
            assigned = False
            for leg in due:
                spot = spots[leg.key.underlying]
                value = intrinsic(leg.key.right, leg.key.strike, spot)
                amount = leg.qty * value * leg.multiplier * position.quantity
                self.cash += amount
                position.realized += amount
                if value > 0 and leg.settlement == "physical":
                    log.info(
                        "physical settlement of %+d %s %s %s expiring %s at spot %.2f",
                        leg.qty,
                        leg.key.underlying,
                        leg.key.right,
                        leg.key.strike,
                        leg.key.expiration,
                        spot,
                    )
                    assigned = assigned or leg.qty < 0
            position.legs = [leg for leg in position.legs if leg not in due]
            if not position.legs:
                reason = "assignment" if assigned else "expired"
                closed.append(self._finish(position, [], ts, reason))
        return closed

    def mark(self, quotes: Mapping[str, Quotes]) -> tuple[float, int]:
        total, stale = 0.0, 0
        for position in self.positions.values():
            prices = []
            for leg in position.legs:
                mid = mid_prices(quotes.get(leg.key.underlying, {}), [leg])
                if mid is not None:
                    self._last_mid[leg.key] = mid[0]
                    prices.append(mid[0])
                else:
                    stale += 1
                    prices.append(self._last_mid.get(leg.key, leg.entry_price))
            total += leg_value(position.legs, prices) * position.quantity
        return total, stale

    def requirement(self, model) -> float:
        total = 0.0
        for position in self.positions.values():
            required = model.requirement(position.legs, position.entry_net)
            if required is not None:
                total += required * position.quantity
        return total

    def _finish(
        self, position: Position, prices: list[float], ts: datetime, reason: str
    ) -> TradeRecord:
        q = position.quantity
        pnl = (
            position.entry_net * q
            + leg_value(position.legs, prices) * q
            + position.realized
            - position.commissions
        )
        record = TradeRecord(
            position_id=position.id,
            underlying=position.underlying,
            opened_ts=position.opened_ts,
            closed_ts=ts,
            legs=self._opened_legs.pop(position.id),
            quantity=q,
            entry_net=position.entry_net,
            exit_value=(pnl + position.commissions) / q - position.entry_net,
            commissions=position.commissions,
            pnl=pnl,
            exit_reason=reason,
            max_loss=position.max_loss,
        )
        del self.positions[position.id]
        self.trades.append(record)
        return record
