import json
from datetime import UTC, date, datetime

import polars as pl
import pytest

from options_bt.data.adapters.synthetic import generate_chains
from options_bt.data.chain import ContractKey, index_quotes
from options_bt.data.schema import QUOTE_SCHEMA, snapshot_ts
from options_bt.data.store import ImportSummary, QuoteStore, write_quotes
from options_bt.errors import DataError
from tests.helpers import first_chain


def _quote(d, exp, strike, right, iv, price=100.0, underlying="SPY"):
    return {
        "ts": snapshot_ts(d),
        "underlying": underlying,
        "underlying_price": price,
        "expiration": exp,
        "strike": strike,
        "right": right,
        "style": "american",
        "settlement": "physical",
        "bid": 1.0,
        "ask": 1.1,
        "delta": 0.5,
        "iv": iv,
        "multiplier": 100,
    }


def _store(tmp_path, rows):
    write_quotes(pl.DataFrame(rows, schema=QUOTE_SCHEMA), tmp_path)
    return QuoteStore(tmp_path)


def test_timestamps_and_chain(make_store):
    root = make_store({"SPY": [100.0] * 5})
    st = QuoteStore(root)
    ts = st.timestamps(["SPY"])
    assert len(ts) == 5 and ts == sorted(ts)
    assert st.chain("SPY", ts[0])["underlying"].unique().to_list() == ["SPY"]


def test_chain_missing_ts_raises(make_store):
    st = QuoteStore(make_store({"SPY": [100.0] * 2}))
    with pytest.raises(DataError):
        st.chain("SPY", datetime(2030, 1, 1, tzinfo=UTC))


def test_chain_unknown_underlying_raises(make_store):
    st = QuoteStore(make_store({"SPY": [100.0]}))
    with pytest.raises(DataError):
        st.timestamps(["QQQ"])
    with pytest.raises(DataError):
        st.chain("QQQ", st.timestamps(["SPY"])[0])


def test_chain_has_only_requested_ts_and_schema_order(make_store):
    st = QuoteStore(make_store({"SPY": [100.0, 101.0]}))
    ts = st.timestamps(["SPY"])
    c = st.chain("SPY", ts[1])
    assert c["ts"].unique().to_list() == [ts[1]]
    assert c.columns == list(QUOTE_SCHEMA)
    assert c["underlying_price"].unique().to_list() == [101.0]


@pytest.fixture
def parquet_reads(monkeypatch) -> list:
    """Arguments of every `pl.read_parquet` call made during the test."""
    calls = []
    real = pl.read_parquet
    monkeypatch.setattr(pl, "read_parquet", lambda *a, **k: calls.append(a) or real(*a, **k))
    return calls


def test_chain_reads_each_year_once(make_store, parquet_reads):
    st = QuoteStore(make_store({"SPY": [100.0] * 3}))
    for t in st.timestamps(["SPY"]):
        st.chain("SPY", t)
    assert len(parquet_reads) == 1


def test_chain_alternating_underlyings_reads_each_once(make_store, parquet_reads):
    st = QuoteStore(make_store({"SPY": [100.0] * 3, "QQQ": [50.0] * 3}))
    ts = st.timestamps(["SPY", "QQQ"])
    for t in ts:
        assert st.chain("SPY", t)["underlying"].unique().to_list() == ["SPY"]
        assert st.chain("QQQ", t)["underlying"].unique().to_list() == ["QQQ"]
    assert len(parquet_reads) == 2


def test_chain_across_year_boundary(make_store):
    root = make_store({"SPY": [100.0] * 4}, start=date(2024, 12, 30))
    assert sorted(p.name for p in (root / "quotes/underlying=SPY").iterdir()) == [
        "year=2024",
        "year=2025",
    ]
    st = QuoteStore(root)
    ts = st.timestamps(["SPY"])
    assert len(ts) == 4
    for t in ts:
        assert st.chain("SPY", t)["ts"].unique().to_list() == [t]


def test_timestamps_union_and_date_filter(make_store):
    st = QuoteStore(make_store({"SPY": [100.0] * 5, "QQQ": [50.0] * 3}))
    all_ts = st.timestamps(["SPY", "QQQ"])
    assert len(all_ts) == 5 and all_ts == sorted(all_ts)
    # 2024-01-02 .. 2024-01-08 are the five SPY days
    got = st.timestamps(["SPY"], start=date(2024, 1, 3), end=date(2024, 1, 5))
    assert [t.date() for t in got] == [date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]
    assert st.timestamps(["SPY"], start=date(2024, 1, 5)) == all_ts[3:]
    assert st.timestamps(["SPY"], end=date(2024, 1, 3)) == all_ts[:2]


def test_index_quotes_maps_every_contract_to_bid_ask(make_store):
    c = first_chain(make_store({"SPY": [100.0]}))
    index = index_quotes(c)
    assert len(index) == c.height
    row = c.row(0, named=True)
    key = ContractKey(row["underlying"], row["expiration"], row["strike"], row["right"])
    assert index[key] == (row["bid"], row["ask"])
    assert ContractKey("SPY", date(2099, 1, 1), 1.0, "P") not in index


def test_underlying_series(make_store):
    st = QuoteStore(make_store({"SPY": [100.0, 101.5, 99.0]}))
    s = st.underlying_series("SPY")
    assert s.columns == ["ts", "underlying_price"]
    assert s["underlying_price"].to_list() == [100.0, 101.5, 99.0]
    assert s["ts"].to_list() == st.timestamps(["SPY"])


def test_series_ts_matches_series_and_is_cached(make_store):
    st = QuoteStore(make_store({"SPY": [100.0, 101.5, 99.0]}))
    expected = st.timestamps(["SPY"])
    assert st.series_ts("underlying", "SPY") == expected
    assert st.series_ts("atm_iv", "SPY", 30) == expected
    assert st.series_ts("underlying", "SPY") is st.series_ts("underlying", "SPY")


def test_atm_iv_series_basic(make_store):
    st = QuoteStore(make_store({"SPY": [100.0] * 3}, vol=0.25))
    s = st.atm_iv_series("SPY")
    assert s.columns == ["ts", "atm_iv"]
    assert len(s) == 3
    assert s["atm_iv"].to_list() == pytest.approx([0.25] * 3)


def test_atm_iv_series_picks_closest_dte_nearest_strike_and_means_call_put(tmp_path):
    d = date(2024, 1, 2)
    rows = [
        # 25 and 35 DTE equidistant from 30 -> earlier expiration (25 DTE: Jan 27) wins
        _quote(d, date(2024, 1, 27), 100.0, "C", 0.10),
        _quote(d, date(2024, 1, 27), 100.0, "P", 0.20),
        _quote(d, date(2024, 2, 6), 100.0, "C", 0.90),
        _quote(d, date(2024, 2, 6), 100.0, "P", 0.90),
        # strike 100 is nearer spot (100.0) than 98
        _quote(d, date(2024, 1, 27), 98.0, "C", 0.70),
        _quote(d, date(2024, 1, 27), 98.0, "P", 0.70),
    ]
    st = _store(tmp_path, rows)
    assert st.atm_iv_series("SPY")["atm_iv"].to_list() == pytest.approx([0.15])


def test_atm_iv_series_strike_tie_picks_lower(tmp_path):
    d = date(2024, 1, 2)
    rows = [
        _quote(d, date(2024, 2, 1), 99.0, "C", 0.30),
        _quote(d, date(2024, 2, 1), 101.0, "C", 0.50),
    ]
    st = _store(tmp_path, rows)
    assert st.atm_iv_series("SPY")["atm_iv"].to_list() == pytest.approx([0.30])


def test_atm_iv_series_skips_null_iv_and_uses_nonnull_leg(tmp_path):
    d1, d2 = date(2024, 1, 2), date(2024, 1, 3)
    rows = [
        _quote(d1, date(2024, 2, 1), 100.0, "C", None),
        _quote(d1, date(2024, 2, 1), 100.0, "P", 0.40),
        _quote(d2, date(2024, 2, 1), 100.0, "C", None),
        _quote(d2, date(2024, 2, 1), 100.0, "P", None),
    ]
    st = _store(tmp_path, rows)
    s = st.atm_iv_series("SPY")
    assert s["ts"].to_list() == [snapshot_ts(d1)]
    assert s["atm_iv"].to_list() == pytest.approx([0.40])


def test_atm_iv_series_cached(make_store, monkeypatch):
    st = QuoteStore(make_store({"SPY": [100.0] * 2}))
    first = st.atm_iv_series("SPY")
    monkeypatch.setattr(pl, "scan_parquet", lambda *a, **k: pytest.fail("rescanned"))
    assert st.atm_iv_series("SPY") is first


def test_fingerprint(make_store):
    root = make_store({"SPY": [100.0]})
    fp = QuoteStore(root).fingerprint()
    assert len(fp) == 1
    ((path, info),) = fp.items()
    assert "underlying=SPY" in path and "year=2024" in path
    assert info["files"] == 1 and info["bytes"] > 0


def test_fingerprint_changes_when_data_added(make_store, tmp_path):
    root = make_store({"SPY": [100.0]})
    before = QuoteStore(root).fingerprint()
    write_quotes(
        pl.DataFrame(
            [_quote(date(2025, 3, 1), date(2025, 4, 5), 100.0, "C", 0.2)], schema=QUOTE_SCHEMA
        ),
        root,
    )
    assert QuoteStore(root).fingerprint() != before


def test_dropped_rows(tmp_path):
    st = QuoteStore(tmp_path)
    assert st.dropped_rows() == 0
    (tmp_path / "import_log.jsonl").write_text(
        json.dumps({"rows_written": 5, "rows_dropped": 2, "partitions": 1})
        + "\n"
        + json.dumps({"rows_written": 5, "rows_dropped": 3, "partitions": 1})
        + "\n"
    )
    assert st.dropped_rows() == 5


def test_write_quotes_partitions_and_log(tmp_path):
    df = generate_chains("SPY", [(date(2024, 12, 31), 100.0), (date(2025, 1, 2), 100.0)])
    s = write_quotes(df, tmp_path)
    assert s.partitions == 2 and s.rows_dropped == 0
    assert (tmp_path / "quotes/underlying=SPY/year=2025").is_dir()
    assert len((tmp_path / "import_log.jsonl").read_text().splitlines()) == 1


def test_write_quotes_into_existing_partition_raises_unless_replace(tmp_path):
    df = generate_chains("SPY", [(date(2024, 1, 2), 100.0)])
    write_quotes(df, tmp_path)
    with pytest.raises(DataError, match=r"underlying=SPY.*year=2024.*--replace"):
        write_quotes(df, tmp_path)
    part_dir = tmp_path / "quotes/underlying=SPY/year=2024"
    assert [p.name for p in part_dir.iterdir()] == ["part-0.parquet"]
    assert len((tmp_path / "import_log.jsonl").read_text().splitlines()) == 1


def test_write_quotes_replace_swaps_partition_and_new_values_win(tmp_path, caplog):
    df = generate_chains("SPY", [(date(2024, 1, 2), 100.0)])
    s1 = write_quotes(df, tmp_path)
    changed = df.with_columns(pl.col("bid") * 0 + 0.01, pl.col("ask") * 0 + 0.02)
    with caplog.at_level("WARNING", logger="options_bt.data.store"):
        s2 = write_quotes(changed, tmp_path, replace=True)
    assert "part-0.parquet" in caplog.text
    part_dir = tmp_path / "quotes/underlying=SPY/year=2024"
    assert [p.name for p in part_dir.iterdir()] == ["part-0.parquet"]
    stored = pl.read_parquet(part_dir / "part-0.parquet")
    assert stored.height == s1.rows_written == s2.rows_written
    assert set(stored["bid"]) == {0.01}
    lines = (tmp_path / "import_log.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {
        "rows_written": s1.rows_written,
        "rows_dropped": 0,
        "partitions": 1,
    }
    assert s1 == ImportSummary(df.height, 0, 1)


def test_write_quotes_replace_only_touches_target_partitions(tmp_path):
    write_quotes(generate_chains("SPY", [(date(2023, 1, 3), 100.0)]), tmp_path)
    write_quotes(generate_chains("SPY", [(date(2024, 1, 2), 100.0)]), tmp_path)
    write_quotes(generate_chains("SPY", [(date(2024, 1, 2), 100.0)]), tmp_path, replace=True)
    assert (tmp_path / "quotes/underlying=SPY/year=2023/part-0.parquet").exists()


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
