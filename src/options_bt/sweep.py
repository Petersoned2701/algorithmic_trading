"""Parameter sweeps: expand `{sweep: [...]}` markers into a grid of runs."""

import copy
import itertools
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from options_bt.analytics.metrics import compute_metrics
from options_bt.data.market import MarketData
from options_bt.data.store import QuoteStore
from options_bt.engine.loop import run
from options_bt.errors import ConfigError
from options_bt.strategy.config import parse_config

log = logging.getLogger(__name__)

_METRIC_COLUMNS = ("net_return", "annualized_return", "max_drawdown", "sharpe", "trades")


def _find_axes(node: Any, path: tuple[str, ...], axes: dict[tuple[str, ...], list]) -> None:
    if isinstance(node, dict):
        if set(node) == {"sweep"}:
            values = node["sweep"]
            dotted = ".".join(path)
            if not path:
                raise ConfigError("a sweep marker cannot be the whole config")
            if not isinstance(values, list) or not values:
                raise ConfigError(f"sweep at '{dotted}' must be a non-empty list")
            axes[path] = values
            return
        for key, child in node.items():
            _find_axes(child, (*path, str(key)), axes)
    elif isinstance(node, list):
        for i, child in enumerate(node):
            _find_axes(child, (*path, str(i)), axes)


def _assign(root: Any, path: tuple[str, ...], value: Any) -> None:
    node = root
    for key in path[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    if isinstance(node, list):
        node[int(path[-1])] = value
    else:
        node[path[-1]] = value


def expand(raw: dict) -> tuple[dict[str, list], list[tuple[dict[str, Any], dict]]]:
    """Return the sweep grid and one `(params, concrete_raw)` per combination.

    Combinations follow `itertools.product` order over the axes in document order.
    """
    axes: dict[tuple[str, ...], list] = {}
    _find_axes(raw, (), axes)
    grid = {".".join(path): values for path, values in axes.items()}
    combos = []
    for values in itertools.product(*axes.values()):
        concrete = copy.deepcopy(raw)
        for path, value in zip(axes, values, strict=True):
            _assign(concrete, path, copy.deepcopy(value))
        combos.append((dict(zip(grid, values, strict=True)), concrete))
    return grid, combos


def robustness(rows: list[dict], grid: dict[str, list]) -> float | None:
    """Fraction of the best row's grid neighbours with a positive net return.

    The best row has the highest `annualized_return` (first in order on ties, `None` ignored);
    neighbours differ from it by exactly one grid step on at least one axis and by at most one
    on every axis.
    """
    candidates = [row for row in rows if row["annualized_return"] is not None]
    if not candidates:
        return None
    best = max(candidates, key=lambda row: row["annualized_return"])

    def index(row: dict) -> list[int]:
        return [values.index(row[axis]) for axis, values in grid.items()]

    best_index = index(best)
    neighbours = [
        row
        for row in rows
        if max((abs(a - b) for a, b in zip(index(row), best_index, strict=True)), default=0) == 1
    ]
    if not neighbours:
        return None
    return sum(1 for row in neighbours if row["net_return"] > 0) / len(neighbours)


def _scalar(value: Any) -> Any:
    return json.dumps(value) if isinstance(value, list | dict) else value


def run_sweep(
    raw: dict,
    store: QuoteStore,
    market: MarketData,
    out_dir: Path,
    start: date | None = None,
    end: date | None = None,
    source: str = "",
) -> pl.DataFrame:
    grid, combos = expand(raw)
    rows = []
    for i, (params, concrete) in enumerate(combos, start=1):
        log.info("sweep %d/%d %s", i, len(combos), params)
        try:
            config = parse_config(concrete, source)
        except ConfigError as exc:
            raise ConfigError(f"sweep combination {params}: {exc}") from exc
        result = run(config, store, market, start=start, end=end)
        metrics = compute_metrics(result.equity, result.trades, result.stats, store.dropped_rows())
        rows.append({**params, **{key: metrics[key] for key in _METRIC_COLUMNS}})
    frame = pl.DataFrame(
        [{**row, **{axis: _scalar(row[axis]) for axis in grid}} for row in rows],
        infer_schema_length=None,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(out_dir / "sweep_results.parquet")
    frame.write_csv(out_dir / "sweep_results.csv")
    return frame
