import logging

from options_bt.data.schema import NEW_YORK
from options_bt.engine.position import Position, leg_value
from options_bt.errors import NoContractFound
from options_bt.strategy import filters
from options_bt.strategy.base import CloseOrder, OpenOrder, Order, StepContext
from options_bt.strategy.config import StrategyConfig
from options_bt.strategy.exits import ExitInputs, exit_reason
from options_bt.strategy.selectors import select_legs

log = logging.getLogger(__name__)

_WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


class RuleStrategy:
    def __init__(self, config: StrategyConfig):
        filters.validate_filters(config.entry.filters)
        self.config = config
        self._step = 0

    def on_step(self, ctx: StepContext) -> list[Order]:
        step, self._step = self._step, self._step + 1
        mine = [p for p in ctx.positions.values() if p.tags.get("strategy") == self.config.name]
        orders: list[Order] = [o for p in mine if (o := self._exit(ctx, p)) is not None]
        if self._scheduled(ctx, step):
            orders.extend(self._entries(ctx, len(mine)))
        return orders

    def _exit(self, ctx: StepContext, position: Position) -> CloseOrder | None:
        chain = ctx.chains.get(position.underlying)
        if chain is None:
            return None
        prices = ctx.fill_model.prices(chain, position.legs, opening=False)
        if prices is None:
            return None
        today = ctx.ts.astimezone(NEW_YORK).date()
        inputs = ExitInputs(
            pnl_per_unit=position.entry_net
            + leg_value(position.legs, prices)
            + position.realized / position.quantity,
            basis=abs(position.entry_net),
            dte=(position.earliest_expiration - today).days,
        )
        reason = exit_reason(inputs, self.config.exits)
        return CloseOrder(position.id, reason) if reason else None

    def _scheduled(self, ctx: StepContext, step: int) -> bool:
        schedule = self.config.entry.schedule
        weekday = _WEEKDAYS[ctx.ts.astimezone(NEW_YORK).weekday()]
        if schedule.weekdays is not None and weekday not in schedule.weekdays:
            return False
        return schedule.every_n_steps is None or step % schedule.every_n_steps == 0

    def _entries(self, ctx: StepContext, open_count: int) -> list[OpenOrder]:
        entry = self.config.entry
        orders: list[OpenOrder] = []
        for underlying in self.config.underlyings:
            if entry.max_open_positions is not None and (
                open_count + len(orders) >= entry.max_open_positions
            ):
                break
            chain = ctx.chains.get(underlying)
            if chain is None:
                continue
            rejected = next(
                (f for f in entry.filters if not filters.check(f, ctx, underlying)), None
            )
            if rejected is not None:
                log.debug(
                    "%s: %s filter rejected entry at %s", underlying, rejected["type"], ctx.ts
                )
                continue
            try:
                legs = select_legs(chain, entry.legs, ctx.ts)
            except NoContractFound as exc:
                log.debug("%s: no entry at %s: %s", underlying, ctx.ts, exc)
                ctx.stats.skipped_entries += 1
                continue
            orders.append(OpenOrder(underlying, legs, "entry", {"strategy": self.config.name}))
        return orders
