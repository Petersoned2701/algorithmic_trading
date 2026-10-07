"""Performance statistics from a run's equity curve and trade log."""

import math

import polars as pl

from options_bt.strategy.base import RunStats


def _years(ts: pl.Series) -> float:
    if len(ts) < 2:
        return 0.0
    return (ts[-1].date() - ts[0].date()).days / 365.25


def periods_per_year(ts: pl.Series) -> float:
    years = _years(ts)
    return (len(ts) - 1) / years if years > 0 else 0.0


def annualized_return(equity: pl.DataFrame) -> float:
    years = _years(equity["ts"])
    if years == 0:
        return 0.0
    if equity["equity"][-1] <= 0:
        return -1.0
    return float((equity["equity"][-1] / equity["equity"][0]) ** (1 / years) - 1)


def net_return(equity: pl.DataFrame) -> float:
    if len(equity) < 2:
        return 0.0
    return float(equity["equity"][-1] / equity["equity"][0] - 1)


def annualized_tbill(equity: pl.DataFrame) -> float | None:
    if "tbill" not in equity.columns:
        return None
    mean = equity["tbill"].mean()
    return None if mean is None else float(mean) / 100


def max_drawdown(equity: pl.DataFrame) -> tuple[float, int]:
    """Deepest drawdown (positive fraction) and longest underwater stretch in calendar days."""
    if len(equity) < 2:
        return 0.0, 0
    peak = equity["equity"][0]
    peak_date = equity["ts"][0].date()
    worst = 0.0
    longest = 0
    underwater = False
    for ts, value in zip(equity["ts"], equity["equity"], strict=True):
        day = ts.date()
        if value >= peak:
            if underwater:
                longest = max(longest, (day - peak_date).days)
            peak, peak_date, underwater = value, day, False
        else:
            worst = max(worst, (peak - value) / peak)
            underwater = True
    if underwater:
        longest = max(longest, (day - peak_date).days)
    return float(worst), longest


def _excess_returns(equity: pl.DataFrame) -> list[float]:
    ppy = periods_per_year(equity["ts"])
    if ppy <= 0:
        return []
    tbill = equity["tbill"] if "tbill" in equity.columns else pl.Series([None] * len(equity))
    rf = tbill.cast(pl.Float64).fill_null(0.0) / 100 / ppy
    excess = equity["equity"].pct_change() - rf
    return excess.drop_nulls().to_list()


def sharpe(equity: pl.DataFrame) -> float | None:
    excess = pl.Series(_excess_returns(equity), dtype=pl.Float64)
    if len(excess) < 2:
        return None
    std = excess.std(ddof=1)
    if not std:
        return None
    return float(excess.mean() / std * math.sqrt(periods_per_year(equity["ts"])))


def sortino(equity: pl.DataFrame) -> float | None:
    excess = pl.Series(_excess_returns(equity), dtype=pl.Float64)
    if len(excess) < 2:
        return None
    downside = math.sqrt(sum(min(x, 0.0) ** 2 for x in excess) / len(excess))
    if downside == 0:
        return None
    return float(excess.mean() / downside * math.sqrt(periods_per_year(equity["ts"])))


def trade_stats(trades: pl.DataFrame) -> dict:
    pnl = trades["pnl"]
    wins = pnl.filter(pnl > 0)
    losses = pnl.filter(pnl < 0)
    n = len(pnl)
    loss_sum = float(losses.sum())
    return {
        "trades": n,
        "win_rate": len(wins) / n if n else None,
        "avg_win": float(wins.mean()) if len(wins) else None,
        "avg_loss": float(losses.mean()) if len(losses) else None,
        "profit_factor": float(wins.sum()) / abs(loss_sum) if len(losses) else None,
        "worst_trade": float(pnl.min()) if n else None,
        "total_commissions": float(trades["commissions"].sum()),
    }


def compute_metrics(
    equity: pl.DataFrame, trades: pl.DataFrame, stats: RunStats, dropped_rows: int
) -> dict:
    tstats = trade_stats(trades)
    drawdown, drawdown_days = max_drawdown(equity)
    annual = annualized_return(equity)
    tbill = annualized_tbill(equity)
    costs = tstats["total_commissions"] + stats.spread_cost
    denominator = float(trades["pnl"].sum()) + costs
    return {
        "net_return": net_return(equity),
        "annualized_return": annual,
        "annualized_tbill": tbill,
        "excess_annualized_return": None if tbill is None else annual - tbill,
        "sharpe": sharpe(equity),
        "sortino": sortino(equity),
        "max_drawdown": drawdown,
        "max_drawdown_days": drawdown_days,
        **tstats,
        "stale_marks": stats.stale_marks,
        "deferred_closes": stats.deferred_closes,
        "skipped_entries": stats.skipped_entries,
        "rejections": dict(stats.rejections),
        "dropped_rows": dropped_rows,
        "total_spread_cost": float(stats.spread_cost),
        "costs_pct_gross_pnl": costs / denominator if denominator > 0 else None,
    }
