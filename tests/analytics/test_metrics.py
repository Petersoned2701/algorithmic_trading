import json
import math
from datetime import date

import polars as pl
import pytest

from options_bt.analytics.metrics import (
    annualized_return,
    compute_metrics,
    max_drawdown,
    periods_per_year,
    sharpe,
    sortino,
    trade_stats,
)
from options_bt.data.schema import snapshot_ts
from options_bt.strategy.base import RunStats
from tests.helpers import eq


def test_max_drawdown():
    assert max_drawdown(eq([100, 110, 99, 120]))[0] == pytest.approx(0.1)


def test_max_drawdown_days_recovered():
    # peak 110 on Jan 3, regained 120 on Jan 5
    assert max_drawdown(eq([100, 110, 99, 120])) == (pytest.approx(0.1), 2)


def test_max_drawdown_days_never_recovered_counts_to_last_ts():
    # peak 110 on Jan 3, last ts Jan 9
    dd, days = max_drawdown(eq([100, 110, 99, 105, 100, 90]))
    assert dd == pytest.approx(20 / 110)
    assert days == 6


def test_max_drawdown_longest_stretch_not_deepest():
    # deep short dip (1 day) then shallow long dip (4 days)
    dd, days = max_drawdown(eq([100, 50, 100, 110, 109, 109, 109, 110]))
    assert dd == pytest.approx(0.5)
    assert days == 6


def test_max_drawdown_monotonic_and_short():
    assert max_drawdown(eq([100, 101, 102])) == (0.0, 0)
    assert max_drawdown(eq([100])) == (0.0, 0)


def test_periods_per_year():
    e = eq([100.0] * 6)
    assert periods_per_year(e["ts"]) == pytest.approx(5 / (7 / 365.25))


def test_annualized_return_one_year():
    e = pl.DataFrame(
        {
            "ts": [snapshot_ts(date(2024, 1, 2)), snapshot_ts(date(2025, 1, 1))],
            "equity": [100.0, 110.0],
        }
    )
    assert annualized_return(e) == pytest.approx(0.10, rel=1e-2)


def test_annualized_return_zero_span_is_zero():
    assert annualized_return(eq([100.0])) == 0.0


def test_sharpe_none_for_constant_equity():
    assert sharpe(eq([100.0] * 10)) is None


def test_sharpe_none_for_too_few_returns():
    assert sharpe(eq([100.0, 101.0])) is None


def test_sharpe_matches_manual_with_and_without_tbill():
    values = [100.0, 101.0, 100.5, 102.0, 103.0]
    e = eq(values)
    rets = [b / a - 1 for a, b in zip(values, values[1:], strict=False)]
    ppy = periods_per_year(e["ts"])
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
    assert sharpe(e) == pytest.approx(mean / sd * math.sqrt(ppy))
    rf = 0.05 / ppy
    ex = [r - rf for r in rets]
    mean = sum(ex) / len(ex)
    assert sharpe(eq(values, tbill=5.0)) == pytest.approx(mean / sd * math.sqrt(ppy))


def test_sharpe_accepts_frame_without_tbill_column():
    assert sharpe(eq([100.0, 101.0, 100.5, 102.0]).drop("tbill")) is not None


def test_sortino_matches_manual():
    values = [100.0, 101.0, 100.0, 102.0, 101.0]
    e = eq(values)
    rets = [b / a - 1 for a, b in zip(values, values[1:], strict=False)]
    ppy = periods_per_year(e["ts"])
    dd = math.sqrt(sum(min(r, 0.0) ** 2 for r in rets) / len(rets))
    expected = sum(rets) / len(rets) / dd * math.sqrt(ppy)
    assert sortino(e) == pytest.approx(expected)


def test_sortino_none_without_downside():
    assert sortino(eq([100.0, 101.0, 102.0, 103.0])) is None


def test_trade_stats_empty_is_safe():
    s = trade_stats(pl.DataFrame(schema={"pnl": pl.Float64, "commissions": pl.Float64}))
    assert s["trades"] == 0 and s["win_rate"] is None
    assert s["avg_win"] is None and s["avg_loss"] is None
    assert s["profit_factor"] is None and s["worst_trade"] is None
    assert s["total_commissions"] == 0.0


def test_profit_factor():
    s = trade_stats(pl.DataFrame({"pnl": [100.0, -50.0, 50.0], "commissions": [1.0] * 3}))
    assert s["profit_factor"] == pytest.approx(3.0) and s["win_rate"] == pytest.approx(2 / 3)
    assert s["avg_win"] == pytest.approx(75.0) and s["avg_loss"] == pytest.approx(-50.0)
    assert s["worst_trade"] == -50.0 and s["total_commissions"] == 3.0


def test_trade_stats_all_winners():
    s = trade_stats(pl.DataFrame({"pnl": [10.0, 5.0], "commissions": [1.0, 1.0]}))
    assert s["profit_factor"] is None and s["avg_loss"] is None
    assert s["win_rate"] == 1.0


def test_spread_cost_in_metrics():
    m = compute_metrics(
        eq([100.0, 101.0]),
        pl.DataFrame({"pnl": [10.0], "commissions": [2.0]}),
        RunStats(spread_cost=8.0),
        dropped_rows=0,
    )
    assert m["costs_pct_gross_pnl"] == pytest.approx(0.5)
    assert m["total_spread_cost"] == 8.0


def test_costs_pct_none_when_denominator_not_positive():
    m = compute_metrics(
        eq([100.0, 99.0]),
        pl.DataFrame({"pnl": [-30.0], "commissions": [2.0]}),
        RunStats(spread_cost=8.0),
        dropped_rows=0,
    )
    assert m["costs_pct_gross_pnl"] is None


def test_compute_metrics_full_and_json_serialisable():
    stats = RunStats(stale_marks=3, deferred_closes=1, skipped_entries=2, rejections={"cap": 4})
    trades = pl.DataFrame({"pnl": [100.0, -50.0], "commissions": [1.0, 1.0]})
    e = eq([100.0, 102.0, 101.0, 104.0], tbill=4.0)
    m = compute_metrics(e, trades, stats, dropped_rows=7)
    assert m["net_return"] == pytest.approx(0.04)
    assert m["annualized_tbill"] == pytest.approx(0.04)
    assert m["excess_annualized_return"] == pytest.approx(m["annualized_return"] - 0.04)
    assert m["max_drawdown"] == pytest.approx(1 / 102)
    assert m["max_drawdown_days"] == 2
    assert m["stale_marks"] == 3 and m["deferred_closes"] == 1 and m["skipped_entries"] == 2
    assert m["rejections"] == {"cap": 4} and m["dropped_rows"] == 7
    assert m["trades"] == 2 and m["total_commissions"] == 2.0
    json.dumps(m)


def test_compute_metrics_without_tbill_or_trades():
    m = compute_metrics(
        eq([100.0, 101.0]).drop("tbill"),
        pl.DataFrame(schema={"pnl": pl.Float64, "commissions": pl.Float64}),
        RunStats(),
        dropped_rows=0,
    )
    assert m["annualized_tbill"] is None and m["excess_annualized_return"] is None
    assert m["costs_pct_gross_pnl"] is None
    json.dumps(m)


def test_compute_metrics_short_equity():
    m = compute_metrics(
        eq([100.0]),
        pl.DataFrame(schema={"pnl": pl.Float64, "commissions": pl.Float64}),
        RunStats(),
        dropped_rows=0,
    )
    assert m["net_return"] == 0.0 and m["max_drawdown"] == 0.0 and m["max_drawdown_days"] == 0
    assert m["sharpe"] is None and m["sortino"] is None


def test_sharpe_sortino_none_for_zero_span():
    e = pl.DataFrame(
        {
            "ts": [snapshot_ts(date(2024, 1, 2))] * 4,
            "equity": [100.0, 101.0, 100.0, 102.0],
            "tbill": [5.0] * 4,
        }
    )
    assert sharpe(e) is None and sortino(e) is None


def test_annualized_return_wiped_out_does_not_raise():
    assert annualized_return(eq([100, 50, -10])) == -1.0
    m = compute_metrics(
        eq([100, 50, -10]),
        pl.DataFrame(schema={"pnl": pl.Float64, "commissions": pl.Float64}),
        RunStats(),
        dropped_rows=0,
    )
    assert m["annualized_return"] == -1.0 and m["net_return"] == pytest.approx(-1.1)
    json.dumps(m)
