import logging
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from functools import cached_property
from pathlib import Path

import polars as pl

from options_bt.data.schema import NEW_YORK
from options_bt.errors import DataError

log = logging.getLogger(__name__)


def _read_series(path: Path) -> pl.DataFrame:
    try:
        df = pl.read_csv(path, schema_overrides={"date": pl.Utf8, "value": pl.Utf8})
        return df.select(
            pl.col("date").str.to_date("%Y-%m-%d", strict=True),
            pl.col("value").cast(pl.Float64, strict=True),
        ).sort("date")
    except (pl.exceptions.PolarsError, OSError) as exc:
        raise DataError(f"cannot read market series {path.name}: {exc}") from exc


@dataclass(frozen=True)
class MarketData:
    series: dict[str, pl.DataFrame]

    @classmethod
    def load(cls, data_root: Path) -> "MarketData":
        folder = Path(data_root) / "market"
        series = {p.stem: _read_series(p) for p in sorted(folder.glob("*.csv"))}
        log.info("loaded market series: %s", ", ".join(series) or "none")
        return cls(series)

    def asof(self, name: str, ts: datetime) -> float | None:
        """Last value on or before the New York date of `ts`, or None if there is none."""
        if name not in self.series:
            raise DataError(f"market series '{name}' not loaded")
        dates, values = self._lists[name]
        i = bisect_right(dates, ts.astimezone(NEW_YORK).date())
        return values[i - 1] if i else None

    @cached_property
    def _lists(self) -> dict[str, tuple[list[date], list[float]]]:
        return {
            name: (df["date"].to_list(), df["value"].to_list()) for name, df in self.series.items()
        }
