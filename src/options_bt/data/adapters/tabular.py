import logging
from datetime import time
from pathlib import Path
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, model_validator

from options_bt.data.schema import QUOTE_SCHEMA, snapshot_ts
from options_bt.data.store import ImportSummary, write_quotes
from options_bt.errors import DataError
from options_bt.loaders import load_yaml, read_table, validate_model

log = logging.getLogger(__name__)

_SHARED = ("underlying", "underlying_price", "expiration", "strike")
_PER_RIGHT = ("bid", "ask", "delta", "iv")
_SIDE_REQUIRED = ("bid", "ask", "delta")
_REQUIRED = (*_SHARED, "right", "bid", "ask", "delta", "style", "settlement", "multiplier")


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["csv", "parquet"]
    layout: Literal["long", "wide"]
    date_column: str
    date_format: str | None = None
    snapshot_time: time = time(15, 45)
    columns: dict[str, str]
    right_values: dict[str, str] = {"C": "C", "P": "P"}
    call: dict[str, str] | None = None
    put: dict[str, str] | None = None
    put_delta_from_call: bool = False
    defaults: dict[str, Any] = {}
    verified: bool = False

    @model_validator(mode="after")
    def _check_keys(self):
        long = self.layout == "long"
        allowed = {*_SHARED, *_PER_RIGHT, "right"} if long else set(_SHARED)
        _reject_unknown("columns", self.columns, allowed)
        _reject_unknown("defaults", self.defaults, set(QUOTE_SCHEMA) - {"ts"})
        if set(self.right_values) != {"C", "P"}:
            raise ValueError("right_values must have exactly the keys C and P")
        if not long:
            if self.call is None or self.put is None:
                raise ValueError("wide layout needs both 'call' and 'put' sub-mappings")
            _reject_unknown("call", self.call, set(_PER_RIGHT))
            _reject_unknown("put", self.put, set(_PER_RIGHT))
            for side_name, side in (("call", self.call), ("put", self.put)):
                waived = {"delta"} if side_name == "put" and self.put_delta_from_call else set()
                missing = sorted(set(_SIDE_REQUIRED) - set(side) - waived)
                if missing:
                    raise ValueError(f"'{side_name}' mapping is missing required keys {missing}")
            if self.put_delta_from_call and "delta" not in self.call:
                raise ValueError("put_delta_from_call needs a 'call.delta' mapping")
        elif self.call is not None or self.put is not None:
            raise ValueError("'call'/'put' sub-mappings are only valid in wide layout")
        return self


def _reject_unknown(section: str, values: dict, allowed: set[str]) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"unknown {section} keys {unknown}; allowed: {sorted(allowed)}")


def load_mapping(path: str | Path) -> Mapping:
    return validate_model(Mapping, load_yaml(path), f"mapping {path}")


def _to_date(col: pl.Series, label: str, fmt: str | None, raw_path: Path) -> pl.Series:
    if col.null_count():
        raise DataError(f"{col.null_count()} null values in column '{label}' of {raw_path}")
    try:
        if col.dtype == pl.Utf8:
            return col.str.strip_chars().str.to_date(fmt, strict=True)
        return col.cast(pl.Date, strict=True)
    except pl.exceptions.PolarsError as exc:
        raise DataError(f"cannot parse date column '{label}' in {raw_path}: {exc}") from exc


def _pick(frame: pl.DataFrame, source: dict[str, str], raw_path: Path, prefix: str = "") -> dict:
    out = {}
    for canonical, column in source.items():
        if column not in frame.columns:
            raise DataError(
                f"source column '{column}' (mapped to canonical '{prefix}{canonical}') "
                f"not found in {raw_path}; available: {', '.join(frame.columns)}"
            )
        out[canonical] = frame[column]
    return out


def _long_rows(frame: pl.DataFrame, m: Mapping, raw_path: Path) -> pl.DataFrame:
    picked = _pick(frame, m.columns, raw_path)
    if "right" in picked:
        to_canonical = {source: canonical for canonical, source in m.right_values.items()}
        source_rights = picked["right"].cast(pl.Utf8)
        unexpected = sorted(set(source_rights.drop_nulls()) - set(to_canonical))
        if unexpected or source_rights.null_count():
            listed = ", ".join(map(repr, unexpected)) + (
                ", null" if source_rights.null_count() else ""
            )
            raise DataError(
                f"column '{m.columns['right']}' in {raw_path} has values {listed} not in "
                f"right_values {m.right_values}; check the mapping"
            )
        picked["right"] = source_rights.replace_strict(to_canonical)
    return pl.DataFrame(picked)


def _pick_floats(
    frame: pl.DataFrame, source: dict[str, str], raw_path: Path, prefix: str
) -> dict[str, pl.Series]:
    out = {}
    for canonical, col in _pick(frame, source, raw_path, prefix).items():
        try:
            out[canonical] = col.cast(pl.Float64, strict=True)
        except pl.exceptions.PolarsError as exc:
            raise DataError(
                f"cannot read column '{source[canonical]}' (canonical '{prefix}{canonical}') "
                f"of {raw_path} as numbers: {exc}"
            ) from exc
    return out


def _wide_rows(frame: pl.DataFrame, m: Mapping, raw_path: Path) -> pl.DataFrame:
    shared = _pick(frame, m.columns, raw_path)
    call = _pick_floats(frame, m.call, raw_path, "call.")
    put_map = {k: v for k, v in m.put.items() if not (k == "delta" and m.put_delta_from_call)}
    put = _pick_floats(frame, put_map, raw_path, "put.")
    if m.put_delta_from_call:
        put["delta"] = call["delta"] - 1.0
    sides = [
        pl.DataFrame({**shared, **side}).with_columns(right=pl.lit(right))
        for right, side in (("C", call), ("P", put))
    ]
    try:
        return pl.concat(sides, how="diagonal")
    except pl.exceptions.PolarsError as exc:
        raise DataError(f"cannot combine call and put columns of {raw_path}: {exc}") from exc


def convert(
    raw_path: Path, mapping_path: Path, data_root: Path, replace: bool = False
) -> ImportSummary:
    raw_path = Path(raw_path)
    mapping = load_mapping(mapping_path)
    if not mapping.verified:
        log.warning(
            "mapping %s is unverified; check a sample before trusting results",
            Path(mapping_path).stem,
        )
    frame = read_table(raw_path, f"{mapping.format} file", mapping.format)
    if mapping.date_column not in frame.columns:
        raise DataError(f"date column '{mapping.date_column}' not found in {raw_path}")

    rows = (_long_rows if mapping.layout == "long" else _wide_rows)(frame, mapping, raw_path)
    days = _to_date(frame[mapping.date_column], mapping.date_column, mapping.date_format, raw_path)
    if mapping.layout == "wide":
        days = pl.concat([days, days])
    rows = rows.with_columns(day=days)
    if "expiration" in rows.columns:
        label = mapping.columns["expiration"]
        expiry = _to_date(rows["expiration"], label, mapping.date_format, raw_path)
        rows = rows.with_columns(expiry.alias("expiration"))

    unique_days = rows["day"].unique().to_list()
    stamps = pl.DataFrame(
        {"day": unique_days, "ts": [snapshot_ts(d, mapping.snapshot_time) for d in unique_days]},
        schema={"day": pl.Date, "ts": QUOTE_SCHEMA["ts"]},
    )
    rows = rows.join(stamps, on="day", how="left").drop("day")

    for name in QUOTE_SCHEMA:
        if name in rows.columns:
            continue
        if name in mapping.defaults:
            rows = rows.with_columns(pl.lit(mapping.defaults[name]).alias(name))
        elif name in _REQUIRED:
            raise DataError(
                f"required canonical column '{name}' is neither mapped nor defaulted "
                f"in {mapping_path}"
            )
        else:
            rows = rows.with_columns(pl.lit(None).alias(name))
    return write_quotes(rows.select(list(QUOTE_SCHEMA)), data_root, replace=replace)
