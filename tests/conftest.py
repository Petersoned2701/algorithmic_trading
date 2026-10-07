import logging
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from options_bt.data.adapters.synthetic import generate_chains
from options_bt.data.history import History
from options_bt.data.market import MarketData
from options_bt.data.schema import NEW_YORK, snapshot_ts, validate
from options_bt.data.store import QuoteStore, write_quotes
from options_bt.execution.fills import FillModel
from options_bt.strategy.base import RunStats, StepContext


@pytest.fixture(autouse=True)
def _reset_options_bt_logger():
    yield
    logger = logging.getLogger("options_bt")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = True


@pytest.fixture
def make_store(tmp_path: Path) -> Callable[..., Path]:
    def _make(paths: dict[str, list[float]], start: date = date(2024, 1, 2), **gen_kwargs) -> Path:
        frames = []
        for underlying, closes in paths.items():
            days, d = [], start
            while len(days) < len(closes):
                if d.weekday() < 5:
                    days.append(d)
                d += timedelta(days=1)
            frames.append(
                generate_chains(underlying, list(zip(days, closes, strict=True)), **gen_kwargs)
            )
        write_quotes(pl.concat(frames), tmp_path)
        return tmp_path

    return _make


@pytest.fixture
def spy_chain() -> pl.DataFrame:
    raw = generate_chains("SPY", [(date(2024, 1, 2), 100.0)])
    chain, _ = validate(raw)
    return chain


@pytest.fixture
def ctx_factory(make_store) -> Callable[..., StepContext]:
    def _make(
        on: date | None = None, *, vix: float = 15.0, vix3m: float = 17.0, days: int | None = None
    ) -> StepContext:
        start = date(2024, 1, 2)
        if days is None:
            days = 1
            if on is not None:
                days = sum(
                    1 for n in range((on - start).days + 1) if (start + timedelta(n)).weekday() < 5
                )
        root = make_store({"SPY": [100.0] * days})
        store = QuoteStore(root)
        if on is None:
            on = store.timestamps(["SPY"])[-1].astimezone(NEW_YORK).date()
        ts = snapshot_ts(on)
        series = {
            name: pl.DataFrame({"date": [start], "value": [value]})
            for name, value in (("vix", vix), ("vix3m", vix3m))
        }
        return StepContext(
            ts=ts,
            chains={"SPY": store.chain("SPY", ts)},
            positions={},
            equity=100_000.0,
            market=MarketData(series),
            history=History(store, ts),
            fill_model=FillModel(),
            stats=RunStats(),
        )

    return _make
