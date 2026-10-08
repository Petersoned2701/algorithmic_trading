import logging
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from functools import cached_property
from pathlib import Path

import polars as pl

from options_bt.data.schema import ny_date
from options_bt.errors import DataError
from options_bt.loaders import read_dated_csv

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketData:
    series: dict[str, pl.DataFrame]

    @classmethod
    def load(cls, data_root: Path) -> "MarketData":
        folder = Path(data_root) / "market"
        series = {
            p.stem: read_dated_csv(p, "market series", ["value"])
            for p in sorted(folder.glob("*.csv"))
        }
        log.info("loaded market series: %s", ", ".join(series) or "none")
        return cls(series)

    def asof(self, name: str, ts: datetime) -> float | None:
        """Last value on or before the New York date of `ts`, or None if there is none."""
        if name not in self.series:
            raise DataError(f"market series '{name}' not loaded")
        dates, values = self._lists[name]
        i = bisect_right(dates, ny_date(ts))
        return values[i - 1] if i else None

    @cached_property
    def _lists(self) -> dict[str, tuple[list[date], list[float]]]:
        return {
            name: (df["date"].to_list(), df["value"].to_list()) for name, df in self.series.items()
        }
