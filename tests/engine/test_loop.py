import copy
import dataclasses
from datetime import date

import polars as pl
import pytest

from options_bt.data.market import MarketData
from options_bt.data.store import QuoteStore
from options_bt.engine.loop import run
from options_bt.engine.position import TradeRecord
from options_bt.strategy.config import StrategyConfig, parse_config
from tests.helpers import PCS_NO_FILTERS


def _cfg(exits: dict, initial_cash: float) -> StrategyConfig:
    raw = copy.deepcopy(PCS_NO_FILTERS)
    raw["entry"]["schedule"] = {}
    raw["entry"]["max_open_positions"] = 1
    raw["exits"] = exits
    raw["account"] = {"initial_cash": initial_cash}
    return parse_config(raw)


def no_exit_cfg(initial_cash=100_000) -> StrategyConfig:
    return _cfg({}, initial_cash)


def pt_cfg(pct) -> StrategyConfig:
    return _cfg({"profit_target_pct": pct}, 100_000)


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
