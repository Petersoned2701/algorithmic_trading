import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import polars as pl

from options_bt.data.schema import NEW_YORK, QUOTE_SCHEMA, ny_date_expr, validate
from options_bt.errors import DataError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportSummary:
    rows_written: int
    rows_dropped: int
    partitions: int


def write_quotes(df: pl.DataFrame, data_root: Path, replace: bool = False) -> ImportSummary:
    """Validate and write quotes to `quotes/underlying=<U>/year=<Y>/part-0.parquet`.

    A (underlying, year) partition that already holds data is an error unless `replace`, which
    deletes that partition's files first. Each call appends a line to `import_log.jsonl`.
    """
    clean, dropped = validate(df)
    year = pl.col("ts").dt.convert_time_zone(NEW_YORK.key).dt.year().alias("year")
    partitions = clean.with_columns(year).partition_by(["underlying", "year"], as_dict=True)

    targets = {
        key: data_root / "quotes" / f"underlying={key[0]}" / f"year={key[1]}" for key in partitions
    }
    existing = {key: sorted(d.glob("*.parquet")) for key, d in targets.items() if d.is_dir()}
    existing = {key: files for key, files in existing.items() if files}
    if existing and not replace:
        names = ", ".join(sorted(f"underlying={u}/year={y}" for u, y in existing))
        raise DataError(
            f"quote data already exists for {names} under {data_root}; "
            "pass --replace to overwrite those partitions"
        )
    for files in existing.values():
        for path in files:
            path.unlink()
        log.warning("replaced %s: removed %s", files[0].parent, ", ".join(p.name for p in files))

    for key, part in partitions.items():
        targets[key].mkdir(parents=True, exist_ok=True)
        part.drop("year").write_parquet(targets[key] / "part-0.parquet")

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
        self._chain_cache: dict[str, tuple[int, dict[datetime, pl.DataFrame]]] = {}
        self._underlying_cache: dict[str, pl.DataFrame] = {}
        self._atm_iv_cache: dict[tuple[str, int], pl.DataFrame] = {}
        self._ts_cache: dict[tuple, list[datetime]] = {}

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
        ts = pl.concat([self._scan(u).select("ts") for u in underlyings]).unique()
        if start is not None:
            ts = ts.filter(ny_date_expr() >= start)
        if end is not None:
            ts = ts.filter(ny_date_expr() <= end)
        return ts.collect()["ts"].sort().to_list()

    def chain(self, underlying: str, ts: datetime) -> pl.DataFrame:
        year = ts.astimezone(NEW_YORK).year
        cached = self._chain_cache.get(underlying)
        if cached is None or cached[0] != year:
            year_dir = self._underlying_dir(underlying) / f"year={year}"
            if not year_dir.is_dir():
                raise DataError(f"no quotes for {underlying} in {year}")
            frame = pl.read_parquet(year_dir / "*.parquet", hive_partitioning=False)
            by_ts = frame.select(list(QUOTE_SCHEMA)).partition_by("ts", as_dict=True)
            cached = (year, {key[0]: part for key, part in by_ts.items()})
            self._chain_cache[underlying] = cached
        rows = cached[1].get(ts)
        if rows is None:
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
            quotes = (
                self._scan(underlying)
                .select("ts", "underlying_price", "expiration", "strike", "iv")
                .drop_nulls()
                .with_columns(
                    dte_gap=(
                        (pl.col("expiration") - ny_date_expr()).dt.total_days() - target_dte
                    ).abs(),
                    strike_gap=(pl.col("strike") - pl.col("underlying_price")).abs(),
                )
            )
            # DTE-gap ties go to the earlier expiration, strike-gap ties to the lower strike.
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

    def series_ts(
        self, kind: Literal["underlying", "atm_iv"], underlying: str, target_dte: int = 30
    ) -> list[datetime]:
        """Sorted `ts` list of `underlying_series` or `atm_iv_series`, cached with them."""
        key = (kind, underlying, target_dte)
        if key not in self._ts_cache:
            if kind == "underlying":
                frame = self.underlying_series(underlying)
            else:
                frame = self.atm_iv_series(underlying, target_dte)
            self._ts_cache[key] = frame["ts"].to_list()
        return self._ts_cache[key]

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
