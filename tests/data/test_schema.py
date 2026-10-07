from datetime import UTC, date, datetime

import polars as pl
import pytest

from options_bt.data.schema import KEY_COLUMNS, QUOTE_SCHEMA, snapshot_ts, validate
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
        "settlement": ["pm"] * 3,
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
    assert KEY_COLUMNS == ["ts", "underlying", "expiration", "strike", "right"]


def test_missing_column_raises_data_error():
    with pytest.raises(DataError, match="delta"):
        validate(_rows().drop("delta"))


def test_missing_iv_column_raises_data_error():
    with pytest.raises(DataError, match="iv"):
        validate(_rows().drop("iv"))


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


def test_dropped_rows_are_logged_as_warning(caplog):
    with caplog.at_level("WARNING", logger="options_bt.data.schema"):
        validate(_rows(ask=[0.0, 1.0, 1.0], bid=[0.0, 0.9, 0.9]))
    assert "1" in caplog.text


def test_duplicate_contract_rows_keep_last():  # Review Focus 5
    df = pl.concat([_rows().head(1), _rows(bid=[0.5, 0.5, 0.5]).head(1)])
    out, dropped = validate(df)
    assert out.height == 1 and dropped == 1 and out["bid"][0] == 0.5


def test_snapshot_ts_handles_dst():
    assert snapshot_ts(date(2026, 1, 5)).hour == 20  # EST
    assert snapshot_ts(date(2026, 7, 6)).hour == 19  # EDT


def test_snapshot_ts_is_utc_aware():
    ts = snapshot_ts(date(2026, 1, 5))
    assert ts.tzinfo is UTC and ts.minute == 45
