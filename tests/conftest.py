import logging
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from options_bt.data.adapters.synthetic import generate_chains
from options_bt.data.schema import validate
from options_bt.data.store import write_quotes


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
