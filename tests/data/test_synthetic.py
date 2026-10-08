import math
from datetime import date

import polars as pl
import pytest

from options_bt.data.adapters.synthetic import bs_delta, bs_price, convert, generate_chains
from options_bt.data.schema import NEW_YORK, snapshot_ts, validate
from options_bt.data.store import QuoteStore
from options_bt.errors import DataError


def test_bs_put_call_parity():
    c = bs_price(100, 100, 0.5, 0.03, 0.2, "C")
    p = bs_price(100, 100, 0.5, 0.03, 0.2, "P")
    assert c - p == pytest.approx(100 - 100 * math.exp(-0.03 * 0.5), abs=1e-9)


def test_expiry_day_is_intrinsic():
    assert bs_price(95, 100, 0.0, 0.0, 0.2, "P") == 5.0
    assert bs_price(95, 100, 0.0, 0.0, 0.2, "C") == 0.0


def test_expiry_day_delta_is_step():
    assert bs_delta(95, 100, 0.0, 0.0, 0.2, "P") == -1.0
    assert bs_delta(95, 100, 0.0, 0.0, 0.2, "C") == 0.0
    assert bs_delta(105, 100, 0.0, 0.0, 0.2, "C") == 1.0
    assert bs_delta(105, 100, 0.0, 0.0, 0.2, "P") == 0.0


def test_atm_call_delta_is_about_half():
    assert bs_delta(100, 100, 0.25, 0.0, 0.2, "C") == pytest.approx(0.5, abs=0.03)


def test_generated_chain_shape_and_delta_sign():
    df = generate_chains("SPY", [(date(2024, 1, 2), 100.0)])
    assert set(df["right"]) == {"C", "P"}
    assert (df.filter(pl.col("right") == "P")["delta"] <= 0).all()
    assert (df["ask"] - df["bid"] <= 0.10 + 1e-9).all()


def test_generated_chain_expirations_and_strikes():
    df = generate_chains("SPY", [(date(2024, 1, 2), 100.0)], max_dte=14, strike_step=5.0)
    assert sorted(df["expiration"].unique()) == [
        date(2024, 1, 5),
        date(2024, 1, 12),
    ]
    assert sorted(df["strike"].unique()) == [
        80.0,
        85.0,
        90.0,
        95.0,
        100.0,
        105.0,
        110.0,
        115.0,
        120.0,
    ]
    assert (df["underlying_price"] == 100.0).all()
    assert (df["multiplier"] == 100).all()
    assert (df["iv"] == 0.20).all()
    assert df["style"].unique().to_list() == ["american"]
    assert df["settlement"].unique().to_list() == ["physical"]


def test_generated_chain_lists_expiry_day_and_uses_kwargs():
    df = generate_chains(
        "SPX", [(date(2024, 1, 5), 100.0)], max_dte=7, style="european", settlement="cash"
    )
    assert sorted(df["expiration"].unique()) == [date(2024, 1, 5), date(2024, 1, 12)]
    assert df["style"].unique().to_list() == ["european"]
    assert df["settlement"].unique().to_list() == ["cash"]


def test_generated_rows_match_scalar_black_scholes_in_order():
    days = [(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 101.5)]
    df = generate_chains("SPY", days, rate=0.03, vol=0.25, max_dte=10, strike_step=5.0)
    strikes = {0: range(80, 121, 5), 1: range(85, 121, 5)}
    expected_keys = [
        (snapshot_ts(d), exp, right, float(strike))
        for i, (d, _) in enumerate(days)
        for exp in (date(2024, 1, 5), date(2024, 1, 12))
        for right in "CP"
        for strike in strikes[i]
    ]
    assert list(df.select("ts", "expiration", "right", "strike").iter_rows()) == expected_keys
    for row in df.iter_rows(named=True):
        t = (row["expiration"] - row["ts"].astimezone(NEW_YORK).date()).days / 365
        args = (row["underlying_price"], row["strike"], t, 0.03, 0.25, row["right"])
        theo = bs_price(*args)
        assert row["bid"] == pytest.approx(max(0.0, theo - 0.05), abs=1e-12)
        assert row["ask"] == pytest.approx(theo + 0.05, abs=1e-12)
        assert row["delta"] == pytest.approx(bs_delta(*args), abs=1e-12)


def test_generated_chain_is_valid_and_utc_snapshot():
    df = generate_chains("SPY", [(date(2024, 1, 2), 100.0)])
    out, dropped = validate(df)
    assert dropped == 0 and out.height == df.height
    assert df["ts"][0].isoformat() == "2024-01-02T20:45:00+00:00"


def test_synthetic_convert_second_import_needs_replace(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text("date,underlying,close\n2024-01-02,SPY,100\n")
    root = tmp_path / "data"
    first = convert(raw, root, max_dte=7)
    with pytest.raises(DataError, match="--replace"):
        convert(raw, root, max_dte=7)
    again = convert(raw, root, replace=True, max_dte=7)
    assert again.rows_written == first.rows_written
    assert QuoteStore(root).fingerprint()["quotes/underlying=SPY/year=2024"]["files"] == 1


def test_convert_reads_csv_and_writes_each_underlying(tmp_path):
    raw = tmp_path / "closes.csv"
    raw.write_text(
        "date,underlying,close\n2024-01-02,SPY,100\n2024-01-03,SPY,101\n2024-01-02,QQQ,50\n"
    )
    root = tmp_path / "data"
    s = convert(raw, root, max_dte=7)
    assert s.partitions == 2 and s.rows_written > 0
    assert (root / "quotes/underlying=SPY/year=2024").is_dir()
    assert (root / "quotes/underlying=QQQ/year=2024").is_dir()


def test_convert_bad_csv_is_data_error(tmp_path):
    raw = tmp_path / "closes.csv"
    raw.write_text("date,symbol\n2024-01-02,SPY\n")
    with pytest.raises(DataError):
        convert(raw, tmp_path / "data")


def test_make_store_fixture(make_store):
    root = make_store({"SPY": [100.0, 101.0, 102.0, 103.0]}, max_dte=14)
    df = pl.read_parquet(root / "quotes/underlying=SPY/year=2024/part-0.parquet")
    dates = sorted(df["ts"].dt.convert_time_zone("America/New_York").dt.date().unique())
    assert dates == [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]
    assert df.filter(pl.col("ts") == df["ts"].max())["underlying_price"][0] == 103.0
