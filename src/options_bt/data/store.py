import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import polars as pl

from options_bt.data.schema import NEW_YORK, validate

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
