import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime

import polars as pl

from options_bt.data.chain import ContractKey, index_quotes
from options_bt.data.history import History
from options_bt.data.market import MarketData
from options_bt.data.schema import NEW_YORK
from options_bt.data.store import QuoteStore
from options_bt.engine.portfolio import Portfolio
from options_bt.engine.position import TradeRecord, leg_value
from options_bt.errors import DataError
from options_bt.execution.costs import commission
from options_bt.execution.fills import FillModel, Quotes, mid_prices
from options_bt.execution.settlement import intrinsic
from options_bt.risk.margin import margin_model
from options_bt.risk.sizing import size
from options_bt.strategy.base import (
    CloseOrder,
    OpenOrder,
    RunStats,
    StepContext,
    Strategy,
)
from options_bt.strategy.config import StrategyConfig
from options_bt.strategy.rule_strategy import RuleStrategy

log = logging.getLogger(__name__)

_UTC_US = pl.Datetime("us", "UTC")
TRADE_SCHEMA = {
    "position_id": pl.Int64,
    "underlying": pl.Utf8,
    "opened_ts": _UTC_US,
    "closed_ts": _UTC_US,
    "legs": pl.Utf8,
    "quantity": pl.Int64,
    "entry_net": pl.Float64,
    "exit_value": pl.Float64,
    "commissions": pl.Float64,
    "pnl": pl.Float64,
    "exit_reason": pl.Utf8,
    "max_loss": pl.Float64,
}
EQUITY_SCHEMA = {
    "ts": _UTC_US,
    "equity": pl.Float64,
    "cash": pl.Float64,
    "open_positions": pl.Int64,
    "requirement": pl.Float64,
    "tbill": pl.Float64,
}


@dataclass
class RunResult:
    trades: pl.DataFrame
    equity: pl.DataFrame
    stats: RunStats


class _Run:
    def __init__(self, config: StrategyConfig, store: QuoteStore, market: MarketData):
        self.config = config
        self.store = store
        self.market = market
        self.portfolio = Portfolio(config.account.initial_cash)
        self.fills = FillModel(config.costs.fill_fraction, config.costs.fill_fraction_override)
        self.margin = margin_model(config.margin_model)
        self.stats = RunStats()
        self.chains: dict[str, pl.DataFrame] = {}
        self.quotes: dict[str, dict[ContractKey, tuple[float, float]]] = {}
        self.last_spot: dict[str, float] = {}

    def commission(self, legs, quantity: int) -> float:
        costs = self.config.costs
        return commission(legs, quantity, costs.commission_per_contract, costs.per_order_fee)

    def mark_value(self) -> float:
        return self.portfolio.mark(self.quotes)[0]

    def step(
        self,
        ts: datetime,
        previous: datetime | None,
        tbill: float | None,
        strategy: Strategy,
    ) -> None:
        portfolio = self.portfolio
        spots = {u: float(chain["underlying_price"][0]) for u, chain in self.chains.items()}
        self.last_spot.update(spots)

        for record in portfolio.settle_expired(ts, spots, self.config.account.session_close):
            _log_closed(record)

        mark_value, stale = portfolio.mark(self.quotes)
        self.stats.stale_marks += stale

        if self.config.account.cash_interest and tbill is not None and previous is not None:
            days = (ts.astimezone(NEW_YORK).date() - previous.astimezone(NEW_YORK).date()).days
            portfolio.cash *= 1 + tbill / 100 * days / 365

        ctx = StepContext(
            ts=ts,
            chains=self.chains,
            quotes=self.quotes,
            positions=portfolio.positions,
            equity=portfolio.cash + mark_value,
            market=self.market,
            history=History(self.store, ts),
            fill_model=self.fills,
            stats=self.stats,
        )
        orders = strategy.on_step(ctx)
        for order in orders:
            if isinstance(order, CloseOrder):
                self.close(order, ts)
        for order in orders:
            if isinstance(order, OpenOrder):
                self.open(order, ts)

    def close(self, order: CloseOrder, ts: datetime) -> None:
        position = self.portfolio.positions.get(order.position_id)
        if position is None:
            return
        quotes = self.quotes.get(position.underlying, {})
        prices = self.fills.prices(quotes, position.legs, opening=False)
        if prices is None:
            self.stats.deferred_closes += 1
            log.warning("close of position %d deferred: no quotes at %s", position.id, ts)
            return
        self.add_spread_cost(quotes, position.legs, prices, position.quantity)
        fee = self.commission(position.legs, position.quantity)
        _log_closed(self.portfolio.close(position.id, prices, ts, fee, order.reason))

    def open(self, order: OpenOrder, ts: datetime) -> None:
        quotes = self.quotes.get(order.underlying, {})
        prices = self.fills.prices(quotes, order.legs, opening=True)
        if prices is None:
            self.stats.skipped_entries += 1
            log.debug("%s: no quotes to open at %s", order.underlying, ts)
            return
        for leg, price in zip(order.legs, prices, strict=True):
            leg.entry_price = price
        net = -leg_value(order.legs, prices)
        req = self.margin.requirement(order.legs, net)

        portfolio = self.portfolio
        equity = portfolio.cash + self.mark_value()
        quantity, reason = size(
            req,
            equity=equity,
            cash=portfolio.cash,
            current_requirement=portfolio.requirement(self.margin),
            max_loss_pct_equity=self.config.sizing.max_loss_pct_equity,
            max_total_max_loss_pct=self.config.portfolio_caps.max_total_max_loss_pct,
        )
        if quantity == 0:
            self.stats.reject(reason)
            level = logging.WARNING if reason == "undefined_risk" else logging.DEBUG
            log.log(level, "%s: entry rejected at %s: %s", order.underlying, ts, reason)
            return
        self.add_spread_cost(quotes, order.legs, prices, quantity)
        position = portfolio.open(
            order.underlying,
            order.legs,
            quantity,
            ts,
            self.commission(order.legs, quantity),
            req,
            order.tags,
        )
        log.info(
            "opened %s %s x%d net %.2f at %s",
            order.underlying,
            "; ".join(f"{leg.qty:+d} {leg.key.right} {leg.key.strike}" for leg in order.legs),
            quantity,
            position.entry_net,
            ts,
        )

    def add_spread_cost(self, quotes: Quotes, legs, prices, quantity: int) -> None:
        mids = mid_prices(quotes, legs)
        self.stats.spread_cost += abs(leg_value(legs, prices) - leg_value(legs, mids)) * quantity

    def close_all_at_end(self, ts: datetime) -> None:
        for position in list(self.portfolio.positions.values()):
            quotes = self.quotes.get(position.underlying, {})
            prices = self.fills.prices(quotes, position.legs, opening=False)
            if prices is not None:
                self.add_spread_cost(quotes, position.legs, prices, position.quantity)
                fee = self.commission(position.legs, position.quantity)
            else:
                prices = [
                    intrinsic(leg.key.right, leg.key.strike, self.last_spot[leg.key.underlying])
                    for leg in position.legs
                ]
                fee = 0.0
                log.warning(
                    "position %d (%s) closed at intrinsic value: no quotes at the last step",
                    position.id,
                    position.underlying,
                )
            _log_closed(self.portfolio.close(position.id, prices, ts, fee, "end_of_data"))


def _log_closed(record: TradeRecord) -> None:
    log.info(
        "closed position %d (%s) reason %s pnl %.2f",
        record.position_id,
        record.underlying,
        record.exit_reason,
        record.pnl,
    )


def _warn_no_trades(name: str, stats: RunStats) -> None:
    ranked = sorted(stats.rejections.items(), key=lambda item: (-item[1], item[0]))
    reasons = ", ".join(f"{reason} x{count}" for reason, count in ranked[:3]) or "none recorded"
    log.warning(
        "run %s opened 0 trades; rejections: %s. Try narrower spreads, XSP, or a higher "
        "sizing.max_loss_pct_equity",
        name,
        reasons,
    )


def run(
    config: StrategyConfig,
    store: QuoteStore,
    market: MarketData,
    strategy: Strategy | None = None,
    start: date | None = None,
    end: date | None = None,
) -> RunResult:
    if strategy is None:
        strategy = RuleStrategy(config)
    timestamps = store.timestamps(config.underlyings, start, end)
    if not timestamps:
        raise DataError(f"no snapshots for {', '.join(config.underlyings)} in the requested range")
    available = {u: set(store.timestamps([u])) for u in config.underlyings}
    has_tbill = "tbill" in market.series
    if config.account.cash_interest and not has_tbill:
        log.warning(
            "cash_interest is on but no 'tbill' market series is loaded; no interest accrues"
        )
    log.info("run %s: %d steps", config.name, len(timestamps))

    state = _Run(config, store, market)
    portfolio = state.portfolio
    rows = []
    previous: datetime | None = None
    for i, ts in enumerate(timestamps):
        state.chains = {u: store.chain(u, ts) for u in config.underlyings if ts in available[u]}
        state.quotes = {u: index_quotes(chain) for u, chain in state.chains.items()}
        tbill = market.asof("tbill", ts) if has_tbill else None
        state.step(ts, previous, tbill, strategy)
        if i == len(timestamps) - 1:
            state.close_all_at_end(ts)
        rows.append(
            {
                "ts": ts,
                "equity": portfolio.cash + state.mark_value(),
                "cash": portfolio.cash,
                "open_positions": len(portfolio.positions),
                "requirement": portfolio.requirement(state.margin),
                "tbill": tbill,
            }
        )
        previous = ts

    trades = pl.DataFrame([asdict(t) for t in portfolio.trades], schema=TRADE_SCHEMA)
    equity = pl.DataFrame(rows, schema=EQUITY_SCHEMA)
    if trades.is_empty():
        _warn_no_trades(config.name, state.stats)
    log.info(
        "run %s done: %d trades, final equity %.2f", config.name, trades.height, rows[-1]["equity"]
    )
    return RunResult(trades, equity, state.stats)
