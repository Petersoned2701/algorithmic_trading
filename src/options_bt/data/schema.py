import logging
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import polars as pl

from options_bt.errors import DataError

log = logging.getLogger(__name__)

NEW_YORK = ZoneInfo("America/New_York")

QUOTE_SCHEMA: dict[str, pl.DataType] = {
    "ts": pl.Datetime("us", "UTC"),
    "underlying": pl.Utf8,
    "underlying_price": pl.Float64,
    "expiration": pl.Date,
    "strike": pl.Float64,
    "right": pl.Utf8,
    "style": pl.Utf8,
    "settlement": pl.Utf8,
    "bid": pl.Float64,
    "ask": pl.Float64,
    "delta": pl.Float64,
    "iv": pl.Float64,
    "multiplier": pl.Int32,
}

KEY_COLUMNS = ["ts", "underlying", "expiration", "strike", "right"]


def validate(df: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """Cast to QUOTE_SCHEMA, drop bad quotes and duplicate contracts; return (frame, dropped)."""
    missing = [c for c in QUOTE_SCHEMA if c not in df.columns]
    if missing:
        raise DataError(f"quote data is missing required columns: {', '.join(missing)}")

    casts = []
    for name, dtype in QUOTE_SCHEMA.items():
        try:
            casts.append(df[name].cast(dtype, strict=True))
        except pl.exceptions.PolarsError as exc:
            raise DataError(f"cannot cast column '{name}' to {dtype}: {exc}") from exc
    out = pl.DataFrame(casts)

    bad = (pl.col("bid") < 0) | (pl.col("ask") <= 0) | (pl.col("bid") > pl.col("ask"))
    out = out.filter(~bad.fill_null(True))
    out = out.unique(subset=KEY_COLUMNS, keep="last", maintain_order=True)

    dropped = df.height - out.height
    if dropped:
        log.warning("dropped %d invalid or duplicate quote rows of %d", dropped, df.height)
    return out, dropped


def snapshot_ts(d: date, at: time = time(15, 45)) -> datetime:
    """`d` at `at` New York local time, as a UTC-aware datetime."""
    return datetime.combine(d, at, tzinfo=NEW_YORK).astimezone(UTC)
