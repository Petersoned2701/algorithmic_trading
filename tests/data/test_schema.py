from datetime import UTC, date, datetime

import polars as pl
import pytest

from options_bt.data.schema import (
    QUOTE_SCHEMA,
    ny_date,
    ny_date_expr,
    snapshot_ts,
    validate,
)
from options_bt.errors import DataError


def _rows(**overrides) -> pl.DataFrame:
    ts = datetime(2026, 1, 5, 20, 45, tzinfo=UTC)
    data = {
        "ts": [ts] * 3,
        "underlying": ["SPY"] * 3,
        "underlying_price": [500.0] * 3,
        "expiration": [date(2026, 2, 20)] * 3,
        "strike": [490.0, 495.0, 500.0],
        "right": ["P", "P", "P"],
        "style": ["european"] * 3,
        "settlement": ["physical"] * 3,
        "bid": [1.0, 1.5, 2.0],
        "ask": [1.2, 1.7, 2.2],
        "delta": [-0.2, -0.3, -0.4],
        "iv": [0.2, 0.21, None],
        "multiplier": [100] * 3,
    }
    data.update(overrides)
    return pl.DataFrame(data)


def test_valid_frame_is_cast_to_schema_in_column_order():
    out, dropped = validate(_rows().select(reversed(QUOTE_SCHEMA)))
    assert dropped == 0
    assert out.schema == pl.Schema(QUOTE_SCHEMA)


@pytest.mark.parametrize("column", ["delta", "iv"])
def test_missing_column_raises_data_error(column):
    with pytest.raises(DataError, match=column):
        validate(_rows().drop(column))


def test_uncastable_column_raises_data_error_naming_column():
    with pytest.raises(DataError, match="strike"):
        validate(_rows(strike=["a", "b", "c"]))


def test_bad_quotes_dropped_and_counted():
    df = _rows(bid=[1.0, 2.0, -1.0], ask=[1.2, 1.5, 0.5])  # row1 bid>ask, row2 negative
    out, dropped = validate(df)
    assert out.height == 1 and dropped == 2


def test_zero_ask_dropped():
    _, dropped = validate(_rows(ask=[0.0, 1.0, 1.0], bid=[0.0, 0.9, 0.9]))
    assert dropped == 1


def test_null_quote_dropped():
    out, dropped = validate(_rows(bid=[None, 0.9, 0.9], ask=[1.0, 1.0, 1.0]))
    assert out.height == 2 and dropped == 1


@pytest.mark.parametrize(
    "column, value",
    [
        ("bid", float("nan")),
        ("ask", float("inf")),
        ("bid", float("-inf")),
        ("strike", None),
        ("strike", 0.0),
        ("strike", -5.0),
        ("underlying_price", None),
        ("underlying_price", 0.0),
        ("multiplier", None),
        ("multiplier", 0),
        ("ts", None),
        ("expiration", None),
        ("right", None),
        ("right", "X"),
        ("style", "asian"),
        ("style", None),
        ("settlement", "pm"),
        ("settlement", None),
    ],
)
def test_invalid_row_is_dropped_and_counted(column, value):
    base = _rows()
    values = base[column].to_list()
    values[0] = value
    out, dropped = validate(base.with_columns(pl.Series(column, values, dtype=base[column].dtype)))
    assert dropped == 1 and out.height == 2


def test_null_delta_and_iv_rows_are_kept():
    out, dropped = validate(_rows(delta=[None, float("nan"), -0.4], iv=[None, None, None]))
    assert dropped == 0 and out.height == 3


def test_dropped_rows_are_logged_as_warning(caplog):
    with caplog.at_level("WARNING", logger="options_bt.data.schema"):
        validate(_rows(ask=[0.0, 1.0, 1.0], bid=[0.0, 0.9, 0.9]))
    assert "dropped 1 invalid or duplicate quote rows of 3" in caplog.messages


def test_duplicate_contract_rows_keep_last():
    df = pl.concat([_rows().head(1), _rows(bid=[0.5, 0.5, 0.5]).head(1)])
    out, dropped = validate(df)
    assert out.height == 1 and dropped == 1 and out["bid"][0] == 0.5


def test_snapshot_ts_handles_dst():
    assert snapshot_ts(date(2026, 1, 5)).hour == 20  # EST
    assert snapshot_ts(date(2026, 7, 6)).hour == 19  # EDT


def test_snapshot_ts_is_utc_aware():
    ts = snapshot_ts(date(2026, 1, 5))
    assert ts.tzinfo is UTC and ts.minute == 45


def test_ny_date_uses_new_york_calendar_day():
    late_utc = datetime(2026, 1, 6, 2, 30, tzinfo=UTC)  # 21:30 on Jan 5 in New York
    assert ny_date(late_utc) == date(2026, 1, 5)
    frame = pl.DataFrame({"ts": [late_utc]}, schema={"ts": QUOTE_SCHEMA["ts"]})
    assert frame.select(ny_date_expr())["ts"].to_list() == [date(2026, 1, 5)]
