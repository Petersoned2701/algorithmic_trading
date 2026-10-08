import copy
import dataclasses
import logging
from datetime import date

import polars as pl
import pytest

from options_bt.data.adapters.synthetic import generate_chains
from options_bt.data.market import MarketData
from options_bt.data.store import QuoteStore, write_quotes
from options_bt.engine.loop import run
from options_bt.engine.position import TradeRecord
from options_bt.engine.stats import RunStats
from options_bt.strategy.base import CloseOrder, OpenOrder
from options_bt.strategy.config import StrategyConfig, parse_config
from options_bt.strategy.rule_strategy import RuleStrategy
from tests.helpers import PCS_NO_FILTERS, L, daily_pcs


def no_exit_cfg(initial_cash=100_000) -> StrategyConfig:
    return parse_config(daily_pcs(exits={}, account={"initial_cash": initial_cash}))


def pt_cfg(pct, costs: dict | None = None) -> StrategyConfig:
    return parse_config(
        daily_pcs(exits={"profit_target_pct": pct}, costs=costs or PCS_NO_FILTERS["costs"])
    )


def test_flat_path_spread_expires_worthless(make_store):
    root = make_store({"SPY": [100.0] * 60}, vol=0.2)
    res = run(no_exit_cfg(), QuoteStore(root), MarketData({}))
    first = res.trades.row(0, named=True)
    assert first["exit_reason"] == "expired"
    assert first["pnl"] == pytest.approx(
        first["entry_net"] * first["quantity"] - first["commissions"]
    )


def test_crash_path_loses_max_loss_plus_costs(make_store):
    root = make_store({"SPY": [100.0] * 5 + [70.0] * 55})
    res = run(no_exit_cfg(), QuoteStore(root), MarketData({}))
    t = res.trades.row(0, named=True)
    assert t["pnl"] == pytest.approx(-t["max_loss"] * t["quantity"] - t["commissions"])


def test_profit_target_closes_early(make_store):
    root = make_store({"SPY": [100 + i for i in range(60)]})
    res = run(pt_cfg(50), QuoteStore(root), MarketData({}))
    assert res.trades["exit_reason"][0] == "profit_target"


def test_open_positions_closed_at_end_of_data(make_store):
    root = make_store({"SPY": [100.0] * 10})
    res = run(no_exit_cfg(), QuoteStore(root), MarketData({}))
    assert res.trades["exit_reason"].to_list()[-1] == "end_of_data"
    assert res.equity["equity"][-1] == pytest.approx(100_000 + res.trades["pnl"].sum())


def test_tiny_account_runs_with_zero_trades(make_store):
    cfg = no_exit_cfg(initial_cash=1_000)
    res = run(cfg, QuoteStore(make_store({"SPY": [100.0] * 10})), MarketData({}))
    assert res.trades.height == 0 and res.stats.rejections["size_zero"] > 0


def test_result_frames_have_fixed_columns_even_without_trades(make_store):
    cfg = no_exit_cfg(initial_cash=1_000)
    res = run(cfg, QuoteStore(make_store({"SPY": [100.0] * 10})), MarketData({}))
    assert res.trades.columns == [f.name for f in dataclasses.fields(TradeRecord)]
    assert res.equity.columns == ["ts", "equity", "cash", "open_positions", "requirement", "tbill"]
    assert res.equity.height == 10 and res.equity["tbill"].null_count() == 10
    assert res.equity.schema["tbill"] == pl.Float64


def test_cash_interest_accrues_by_calendar_days_between_steps(make_store):
    raw = copy.deepcopy(PCS_NO_FILTERS)
    raw["account"] = {"initial_cash": 1_000, "cash_interest": True}
    tbill = pl.DataFrame({"date": [date(2024, 1, 1)], "value": [5.0]})
    res = run(
        parse_config(raw),
        QuoteStore(make_store({"SPY": [100.0] * 10})),
        MarketData({"tbill": tbill}),
    )
    days = (
        res.equity["ts"].dt.convert_time_zone("America/New_York").dt.date().diff().dt.total_days()
    )
    expected = 1_000.0
    for d in days.drop_nulls():
        expected *= 1 + 5.0 / 100 * d / 365
    assert res.equity["cash"][-1] == pytest.approx(expected)
    assert res.equity["tbill"].to_list() == [5.0] * 10


def test_end_of_data_falls_back_to_intrinsic_when_underlying_has_no_final_chain(make_store, caplog):
    raw = copy.deepcopy(no_exit_cfg().model_dump(mode="json"))
    raw["underlyings"] = ["QQQ", "SPY"]
    cfg = parse_config(raw)
    root = make_store({"QQQ": [100.0] * 5, "SPY": [100.0] * 10})
    with caplog.at_level(logging.WARNING, logger="options_bt"):
        res = run(cfg, QuoteStore(root), MarketData({}))
    t = res.trades.row(0, named=True)
    assert t["underlying"] == "QQQ" and t["exit_reason"] == "end_of_data"
    assert t["closed_ts"] == res.equity["ts"][-1]
    assert t["pnl"] == pytest.approx(t["entry_net"] * t["quantity"] - t["commissions"])
    assert res.equity["cash"][-1] == pytest.approx(100_000 + res.trades["pnl"].sum())
    assert res.equity["equity"][-1] == pytest.approx(res.equity["cash"][-1])
    assert "intrinsic" in caplog.text


def test_spread_cost_is_a_statistic_and_does_not_change_cash(make_store):
    root = make_store({"SPY": [100 + i for i in range(60)]})
    res = run(pt_cfg(50), QuoteStore(root), MarketData({}))
    assert res.trades.height >= 2 and res.stats.spread_cost > 0
    assert res.stats.skipped_entries == 0
    assert res.equity["cash"][-1] == pytest.approx(100_000 + res.trades["pnl"].sum())

    mid = {"fill_fraction_override": 0.5}
    res = run(pt_cfg(50, costs=mid), QuoteStore(root), MarketData({}))
    assert res.trades.height >= 2
    assert res.stats.spread_cost == pytest.approx(0.0, abs=1e-6)
    assert res.equity["cash"][-1] == pytest.approx(100_000 + res.trades["pnl"].sum())


class _OpenThenScript:
    """Opens via the rule strategy, then adds scripted closes at chosen step indexes."""

    def __init__(self, cfg, closes_at: dict[int, list[int]]):
        self.inner = RuleStrategy(cfg)
        self.closes_at = closes_at
        self.step = 0

    def on_step(self, ctx):
        orders = self.inner.on_step(ctx)
        orders += [CloseOrder(i, "scripted") for i in self.closes_at.get(self.step, [])]
        self.step += 1
        return orders


def test_close_orders_for_missing_or_unquotable_positions(make_store, caplog):
    raw = no_exit_cfg().model_dump(mode="json")
    raw["underlyings"] = ["QQQ", "SPY"]
    cfg = parse_config(raw)
    root = make_store({"SPY": [100.0] * 10})
    gap_days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    gap_days += [date(2024, 1, d) for d in range(8, 13)]
    write_quotes(generate_chains("QQQ", [(d, 100.0) for d in gap_days]), root)
    # QQQ has no chain at step 3 (Jan 5); position 1 opens at step 0.
    strategy = _OpenThenScript(cfg, {3: [1, 999], 4: [1], 5: [1, 999]})
    with caplog.at_level(logging.WARNING, logger="options_bt"):
        res = run(cfg, QuoteStore(root), MarketData({}), strategy)
    assert res.stats.deferred_closes == 1
    assert "deferred" in caplog.text
    first = res.trades.row(0, named=True)
    assert first["exit_reason"] == "scripted"
    assert first["closed_ts"] == res.equity["ts"][4]
    assert res.trades["exit_reason"].to_list().count("scripted") == 1


class _OneOpen:
    def __init__(self, legs):
        self.legs = legs
        self.done = False

    def on_step(self, ctx):
        if self.done:
            return []
        self.done = True
        return [OpenOrder("SPY", self.legs, "entry", {})]


def test_undefined_risk_rejection_is_a_warning(make_store, caplog):
    root = make_store({"SPY": [100.0] * 3})
    strategy = _OneOpen([L(-1, "C", 100)])
    with caplog.at_level(logging.WARNING, logger="options_bt"):
        res = run(no_exit_cfg(), QuoteStore(root), MarketData({}), strategy)
    assert res.trades.height == 0 and res.stats.rejections == {"undefined_risk": 1}
    assert "undefined_risk" in caplog.text


def test_order_legs_are_never_mutated(make_store):
    root = make_store({"SPY": [100.0] * 3})
    rejected = [L(-1, "C", 100)]
    accepted = [L(-1, "P", 95), L(1, "P", 90)]
    for legs in (rejected, accepted):
        res = run(no_exit_cfg(), QuoteStore(root), MarketData({}), _OneOpen(legs))
        assert res.trades.height == len(legs) - 1
        assert [leg.entry_price for leg in legs] == [0.0] * len(legs)


def test_zero_trade_run_warns_with_dominant_rejection_and_hint(make_store, caplog):
    cfg = no_exit_cfg(initial_cash=1_000)
    with caplog.at_level(logging.WARNING, logger="options_bt.engine.loop"):
        run(cfg, QuoteStore(make_store({"SPY": [100.0] * 10})), MarketData({}))
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "0 trades" in m and "size_zero" in m and "max_loss_pct_equity" in m for m in warnings
    )


def test_zero_trade_run_blocked_by_filter_names_it_without_sizing_hint(make_store, caplog):
    raw = daily_pcs()
    raw["entry"]["filters"] = [{"type": "vix_term_structure", "max_ratio": 0.5}]
    series = {
        name: pl.DataFrame({"date": [date(2024, 1, 1)], "value": [value]})
        for name, value in (("vix", 20.0), ("vix3m", 17.0))
    }
    with caplog.at_level(logging.WARNING, logger="options_bt.engine.loop"):
        res = run(
            parse_config(raw), QuoteStore(make_store({"SPY": [100.0] * 10})), MarketData(series)
        )
    assert res.stats.rejections == {"filter:vix_term_structure": 10}
    [message] = [r.getMessage() for r in caplog.records if "0 trades" in r.getMessage()]
    assert "filter:vix_term_structure x10" in message
    assert "max_loss_pct_equity" not in message


def test_run_with_trades_does_not_warn_about_zero_trades(make_store, caplog):
    with caplog.at_level(logging.WARNING, logger="options_bt.engine.loop"):
        run(no_exit_cfg(), QuoteStore(make_store({"SPY": [100.0] * 10})), MarketData({}))
    assert "0 trades" not in caplog.text


def test_run_stats_reject_counts_by_reason():
    stats = RunStats()
    stats.reject("no_contract")
    stats.reject("no_contract")
    stats.reject("cap")
    assert stats.rejections == {"no_contract": 2, "cap": 1}
    assert RunStats().rejections == {}
