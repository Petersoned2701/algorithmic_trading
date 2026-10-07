import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import polars as pl

from options_bt.data.schema import NEW_YORK, QUOTE_SCHEMA, validate
from options_bt.errors import DataError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportSummary:
    rows_written: int
    rows_dropped: int
    partitions: int


def write_quotes(df: pl.DataFrame, data_root: Path) -> ImportSummary:
    """Validate and write quotes to `quotes/underlying=<U>/year=<Y>/part-<n>.parquet`.

    Each call writes new part files (never overwriting) and appends a line to `import_log.jsonl`.
    """
    clean, dropped = validate(df)
    year = pl.col("ts").dt.convert_time_zone(NEW_YORK.key).dt.year().alias("year")
    partitions = clean.with_columns(year).partition_by(["underlying", "year"], as_dict=True)

    for (underlying, year_value), part in partitions.items():
        part_dir = data_root / "quotes" / f"underlying={underlying}" / f"year={year_value}"
        part_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        while (part_dir / f"part-{n}.parquet").exists():
            n += 1
        part.drop("year").write_parquet(part_dir / f"part-{n}.parquet")

    summary = ImportSummary(clean.height, dropped, len(partitions))
    data_root.mkdir(parents=True, exist_ok=True)
    with (data_root / "import_log.jsonl").open("a") as f:
        f.write(json.dumps(asdict(summary)) + "\n")
    log.info(
        "wrote %d quote rows (%d dropped) to %d partitions under %s",
        summary.rows_written,
        summary.rows_dropped,
        summary.partitions,
        data_root,
    )
    return summary


class QuoteStore:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self._chain_cache: tuple[tuple[str, int], pl.DataFrame] | None = None
        self._underlying_cache: dict[str, pl.DataFrame] = {}
        self._atm_iv_cache: dict[tuple[str, int], pl.DataFrame] = {}

    def _underlying_dir(self, underlying: str) -> Path:
        path = self.data_root / "quotes" / f"underlying={underlying}"
        if not path.is_dir():
            raise DataError(f"no quote data for underlying '{underlying}' under {self.data_root}")
        return path

    def _scan(self, underlying: str) -> pl.LazyFrame:
        glob = self._underlying_dir(underlying) / "**" / "*.parquet"
        return pl.scan_parquet(glob, hive_partitioning=False)

    def timestamps(
        self, underlyings: Sequence[str], start: date | None = None, end: date | None = None
    ) -> list[datetime]:
        """Sorted union of snapshot times whose New York date lies within [start, end]."""
        frames = [self._scan(u).select("ts") for u in underlyings]
        ts = pl.concat(frames).unique().collect()["ts"]
        et_date = ts.dt.convert_time_zone(NEW_YORK.key).dt.date()
        keep = pl.Series([True] * len(ts))
        if start is not None:
            keep &= et_date >= start
        if end is not None:
            keep &= et_date <= end
        return ts.filter(keep).sort().to_list()

    def chain(self, underlying: str, ts: datetime) -> pl.DataFrame:
        year = ts.astimezone(NEW_YORK).year
        key = (underlying, year)
        if self._chain_cache is None or self._chain_cache[0] != key:
            year_dir = self._underlying_dir(underlying) / f"year={year}"
            if not year_dir.is_dir():
                raise DataError(f"no quotes for {underlying} in {year}")
            frame = pl.read_parquet(year_dir / "*.parquet", hive_partitioning=False)
            self._chain_cache = (key, frame.select(list(QUOTE_SCHEMA)))
        rows = self._chain_cache[1].filter(pl.col("ts") == ts)
        if rows.is_empty():
            raise DataError(f"no quotes for {underlying} at {ts.isoformat()}")
        return rows

    def underlying_series(self, underlying: str) -> pl.DataFrame:
        if underlying not in self._underlying_cache:
            self._underlying_cache[underlying] = (
                self._scan(underlying)
                .group_by("ts")
                .agg(pl.col("underlying_price").first())
                .sort("ts")
                .collect()
            )
        return self._underlying_cache[underlying]

    def atm_iv_series(self, underlying: str, target_dte: int = 30) -> pl.DataFrame:
        """Per snapshot, mean iv of the call and put at the strike nearest spot, on the
        expiration whose calendar-day DTE (New York date) is closest to `target_dte`."""
        key = (underlying, target_dte)
        if key not in self._atm_iv_cache:
            et_date = pl.col("ts").dt.convert_time_zone(NEW_YORK.key).dt.date()
            quotes = (
                self._scan(underlying)
                .select("ts", "underlying_price", "expiration", "strike", "iv")
                .drop_nulls()
                .with_columns(
                    dte_gap=((pl.col("expiration") - et_date).dt.total_days() - target_dte).abs(),
                    strike_gap=(pl.col("strike") - pl.col("underlying_price")).abs(),
                )
            )
            with_expiry = quotes.filter(
                pl.col("dte_gap") == pl.col("dte_gap").min().over("ts")
            ).filter(pl.col("expiration") == pl.col("expiration").min().over("ts"))
            self._atm_iv_cache[key] = (
                with_expiry.filter(pl.col("strike_gap") == pl.col("strike_gap").min().over("ts"))
                .filter(pl.col("strike") == pl.col("strike").min().over("ts"))
                .group_by("ts")
                .agg(pl.col("iv").mean().alias("atm_iv"))
                .sort("ts")
                .collect()
            )
        return self._atm_iv_cache[key]

    def fingerprint(self) -> dict[str, dict]:
        """Per partition directory (relative to data_root): file count and total bytes."""
        out: dict[str, dict] = {}
        for part_dir in sorted((self.data_root / "quotes").glob("underlying=*/year=*")):
            files = list(part_dir.glob("*.parquet"))
            out[part_dir.relative_to(self.data_root).as_posix()] = {
                "files": len(files),
                "bytes": sum(f.stat().st_size for f in files),
            }
        return out

    def dropped_rows(self) -> int:
        log_path = self.data_root / "import_log.jsonl"
        if not log_path.exists():
            return 0
        lines = log_path.read_text().splitlines()
        return sum(json.loads(line)["rows_dropped"] for line in lines if line.strip())
