import json
import math
from datetime import date

import polars as pl
import pytest

from options_bt.data.adapters.synthetic import bs_delta, bs_price, convert, generate_chains
from options_bt.data.store import ImportSummary, write_quotes
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


def test_generated_chain_is_valid_and_utc_snapshot():
    from options_bt.data.schema import validate

    df = generate_chains("SPY", [(date(2024, 1, 2), 100.0)])
    out, dropped = validate(df)
    assert dropped == 0 and out.height == df.height
    assert df["ts"][0].isoformat() == "2024-01-02T20:45:00+00:00"


def test_write_quotes_partitions_and_log(tmp_path):
    df = generate_chains("SPY", [(date(2024, 12, 31), 100.0), (date(2025, 1, 2), 100.0)])
    s = write_quotes(df, tmp_path)
    assert s.partitions == 2 and s.rows_dropped >= 0
    assert (tmp_path / "quotes/underlying=SPY/year=2025").is_dir()
    assert len((tmp_path / "import_log.jsonl").read_text().splitlines()) == 1


def test_write_quotes_does_not_overwrite_and_appends_log(tmp_path):
    df = generate_chains("SPY", [(date(2024, 1, 2), 100.0)])
    s1 = write_quotes(df, tmp_path)
    s2 = write_quotes(df, tmp_path)
    part_dir = tmp_path / "quotes/underlying=SPY/year=2024"
    assert sorted(p.name for p in part_dir.iterdir()) == ["part-0.parquet", "part-1.parquet"]
    lines = (tmp_path / "import_log.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {
        "rows_written": s1.rows_written,
        "rows_dropped": 0,
        "partitions": 1,
    }
    assert s1 == s2 == ImportSummary(df.height, 0, 1)
    assert pl.read_parquet(part_dir / "part-0.parquet").height == df.height


def test_write_quotes_counts_dropped_rows(tmp_path):
    df = generate_chains("SPY", [(date(2024, 1, 2), 100.0)])
    bad = df.with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(-1.0).otherwise(pl.col("bid")).alias("bid")
    )
    s = write_quotes(bad, tmp_path)
    assert s.rows_dropped == 1 and s.rows_written == df.height - 1


def test_write_quotes_missing_columns_is_data_error(tmp_path):
    with pytest.raises(DataError):
        write_quotes(pl.DataFrame({"ts": [1]}), tmp_path)


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
