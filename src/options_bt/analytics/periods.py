"""Stress periods and the in/out-of-sample split."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
import yaml

from options_bt.analytics.metrics import annualized_return, max_drawdown, net_return
from options_bt.data.schema import ny_date_expr
from options_bt.errors import ConfigError


@dataclass(frozen=True)
class Period:
    name: str
    start: date
    end: date


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"not a date: {value!r}")


def load_periods(path: Path | str) -> list[Period]:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise ConfigError(f"cannot read stress periods {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise ConfigError(f"stress periods {path} must be a YAML list")
    periods = []
    for i, item in enumerate(raw):
        try:
            period = Period(str(item["name"]), _as_date(item["start"]), _as_date(item["end"]))
        except (TypeError, KeyError, ValueError) as exc:
            raise ConfigError(
                f"stress periods {path}, entry {i}: need name, start, end as ISO dates ({exc!r})"
            ) from exc
        if period.end < period.start:
            raise ConfigError(f"stress periods {path}, entry {i}: end is before start")
        periods.append(period)
    return periods


def stress_table(equity: pl.DataFrame, periods: list[Period]) -> list[dict]:
    rows = []
    for period in periods:
        window = equity.filter(ny_date_expr("ts").is_between(period.start, period.end))
        if len(window) < 2:
            rows.append({"name": period.name, "return": None, "max_drawdown": None})
        else:
            rows.append(
                {
                    "name": period.name,
                    "return": net_return(window),
                    "max_drawdown": max_drawdown(window)[0],
                }
            )
    return rows


def _side_metrics(equity: pl.DataFrame, trades: pl.DataFrame) -> dict:
    return {
        "net_return": net_return(equity),
        "annualized_return": annualized_return(equity),
        "max_drawdown": max_drawdown(equity)[0],
        "trades": len(trades),
    }


def split_metrics(equity: pl.DataFrame, trades: pl.DataFrame, oos_start: date) -> dict:
    is_oos = ny_date_expr("ts") >= oos_start
    trade_oos = ny_date_expr("closed_ts") >= oos_start
    return {
        "in_sample": _side_metrics(equity.filter(~is_oos), trades.filter(~trade_oos)),
        "out_of_sample": _side_metrics(equity.filter(is_oos), trades.filter(trade_oos)),
    }
