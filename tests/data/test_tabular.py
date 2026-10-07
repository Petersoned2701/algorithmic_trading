import logging
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from options_bt.cli import main
from options_bt.data.adapters.tabular import convert, load_mapping
from options_bt.data.schema import snapshot_ts
from options_bt.data.store import QuoteStore
from options_bt.errors import ConfigError, DataError

SAMPLES = Path(__file__).parent / "samples"


def _first_chain(root, underlying="SPY"):
    st = QuoteStore(root)
    return st.chain(underlying, st.timestamps([underlying])[0])


def test_long_layout(tmp_path):
    s = convert(SAMPLES / "long_sample.csv", SAMPLES / "long_mapping.yaml", tmp_path)
    assert s.rows_written == 4
    st = QuoteStore(tmp_path)
    assert set(st.chain("SPY", st.timestamps(["SPY"])[0])["right"]) == {"C", "P"}


def test_long_layout_values(tmp_path):
    convert(SAMPLES / "long_sample.csv", SAMPLES / "long_mapping.yaml", tmp_path)
    c = _first_chain(tmp_path)
    assert c["ts"][0] == snapshot_ts(date(2024, 1, 2))
    assert c["expiration"][0] == date(2024, 1, 19)
    put = c.filter(pl.col("right") == "P").row(0, named=True)
    assert (put["bid"], put["delta"], put["iv"], put["style"], put["multiplier"]) == (
        4.9,
        -0.48,
        0.19,
        "american",
        100,
    )


def test_wide_layout_put_delta_from_call(tmp_path):
    convert(SAMPLES / "wide_sample.csv", SAMPLES / "wide_mapping.yaml", tmp_path)
    c = _first_chain(tmp_path)
    assert c.height == 4
    put = c.filter((pl.col("right") == "P") & (pl.col("strike") == 470)).row(0, named=True)
    assert put["delta"] == pytest.approx(0.4 - 1)
    assert put["bid"] == 4.9 and put["iv"] == 0.19
    call = c.filter((pl.col("right") == "C") & (pl.col("strike") == 470)).row(0, named=True)
    assert call["delta"] == 0.4 and call["ask"] == 5.3


def test_wide_layout_explicit_put_delta(tmp_path):
    raw = tmp_path / "wide.csv"
    raw.write_text(
        "d,u,px,e,k,cb,ca,cd,pb,pa,pd\n2024-01-02,SPY,470,2024-01-19,470,5.1,5.3,0.4,4.9,5.1,-0.6\n"
    )
    mapping = tmp_path / "m.yaml"
    mapping.write_text(
        "format: csv\nlayout: wide\ndate_column: d\ndate_format: null\n"
        "columns: {underlying: u, underlying_price: px, expiration: e, strike: k}\n"
        "call: {bid: cb, ask: ca, delta: cd}\nput: {bid: pb, ask: pa, delta: pd}\n"
        "defaults: {style: european, settlement: AM, multiplier: 100}\n"
    )
    convert(raw, mapping, tmp_path / "data")
    c = _first_chain(tmp_path / "data")
    assert c.filter(pl.col("right") == "P")["delta"][0] == -0.6
    assert c["iv"].null_count() == 2
    assert set(c["style"]) == {"european"}


def test_parquet_input(tmp_path):
    raw = tmp_path / "long.parquet"
    pl.read_csv(SAMPLES / "long_sample.csv").write_parquet(raw)
    mapping = tmp_path / "m.yaml"
    mapping.write_text((SAMPLES / "long_mapping.yaml").read_text().replace("csv", "parquet", 1))
    assert convert(raw, mapping, tmp_path / "data").rows_written == 4


def test_missing_column_names_it(tmp_path):
    with pytest.raises(DataError, match="delta"):
        convert(SAMPLES / "long_sample_no_delta.csv", SAMPLES / "long_mapping.yaml", tmp_path)


def test_canonical_column_absent_from_mapping_names_it(tmp_path):
    mapping = tmp_path / "m.yaml"
    lines = (SAMPLES / "long_mapping.yaml").read_text().splitlines()
    mapping.write_text("\n".join(line for line in lines if "Bid" not in line))
    with pytest.raises(DataError, match="bid"):
        convert(SAMPLES / "long_sample.csv", mapping, tmp_path / "data")


def test_unexpected_right_values_listed(tmp_path):
    mapping = tmp_path / "m.yaml"
    mapping.write_text((SAMPLES / "long_mapping.yaml").read_text().replace("P: put", "P: PUT"))
    with pytest.raises(DataError, match="'put'"):
        convert(SAMPLES / "long_sample.csv", mapping, tmp_path / "data")


def test_unreadable_file_names_path(tmp_path):
    missing = tmp_path / "nope.csv"
    with pytest.raises(DataError, match="nope.csv"):
        convert(missing, SAMPLES / "long_mapping.yaml", tmp_path / "data")


def test_bad_date_is_data_error(tmp_path):
    mapping = tmp_path / "m.yaml"
    mapping.write_text((SAMPLES / "long_mapping.yaml").read_text().replace("%m/%d/%Y", "%Y-%m-%d"))
    with pytest.raises(DataError, match="Date"):
        convert(SAMPLES / "long_sample.csv", mapping, tmp_path / "data")


def test_unverified_mapping_warns(tmp_path, caplog):
    mapping = tmp_path / "m.yaml"
    mapping.write_text(
        (SAMPLES / "long_mapping.yaml").read_text().replace("verified: true", "verified: false")
    )
    with caplog.at_level(logging.WARNING):
        convert(SAMPLES / "long_sample.csv", mapping, tmp_path / "data")
    assert "mapping m is unverified; check a sample before trusting results" in caplog.messages


def test_verified_mapping_does_not_warn(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        convert(SAMPLES / "long_sample.csv", SAMPLES / "long_mapping.yaml", tmp_path)
    assert not [m for m in caplog.messages if "unverified" in m]


@pytest.mark.parametrize(
    "edit",
    [
        ("layout: long", "layout: long\nbogus: 1"),
        ("  right: Type\n", "  right: Type\n  nonsense: x\n"),
        ("style: american", "colour: red"),
        ("layout: long", "layout: tall"),
    ],
)
def test_load_mapping_rejects_bad_keys(tmp_path, edit):
    mapping = tmp_path / "m.yaml"
    mapping.write_text((SAMPLES / "long_mapping.yaml").read_text().replace(*edit))
    with pytest.raises(ConfigError):
        load_mapping(mapping)


def test_wide_mapping_requires_call_and_put(tmp_path):
    mapping = tmp_path / "m.yaml"
    mapping.write_text((SAMPLES / "wide_mapping.yaml").read_text().split("call:")[0])
    with pytest.raises(ConfigError, match="call"):
        load_mapping(mapping)


@pytest.mark.parametrize("name", ["dubach", "orats"])
def test_shipped_mappings_load(name):
    assert load_mapping(f"configs/mappings/{name}.yaml") is not None


def test_cli_import_tabular(tmp_path, capsys):
    code = main(
        ["data", "import", "tabular", str(SAMPLES / "long_sample.csv")]
        + ["--mapping", str(SAMPLES / "long_mapping.yaml"), "--data-root", str(tmp_path)]
    )
    assert code == 0
    assert "wrote 4 rows" in capsys.readouterr().out


def _wide_mapping_text(**replacements):
    text = (SAMPLES / "wide_mapping.yaml").read_text()
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def test_wide_put_delta_required_unless_derived(tmp_path):
    mapping = tmp_path / "m.yaml"
    mapping.write_text(
        _wide_mapping_text(**{"put_delta_from_call: true": "put_delta_from_call: false"})
    )
    with pytest.raises(ConfigError, match="delta"):
        load_mapping(mapping)


def test_wide_requires_bid_ask_on_both_sides(tmp_path):
    mapping = tmp_path / "m.yaml"
    mapping.write_text(_wide_mapping_text(**{"  bid: pBidPx\n": ""}))
    with pytest.raises(ConfigError, match="put.*bid"):
        load_mapping(mapping)


def test_wide_integral_bid_on_one_side_is_cast(tmp_path):
    raw = tmp_path / "wide.csv"
    raw.write_text(
        "trade_date,ticker,stkPx,expirDate,strike,cBidPx,cAskPx,cMidIv,pBidPx,pAskPx,pMidIv,delta\n"
        "2024-01-02,SPY,470.5,2024-01-19,470,5,6,0.18,4.9,5.1,0.19,1\n"
    )
    convert(raw, SAMPLES / "wide_mapping.yaml", tmp_path / "data")
    c = _first_chain(tmp_path / "data")
    assert c.filter(pl.col("right") == "C")["bid"][0] == 5.0
    assert c.filter(pl.col("right") == "P")["delta"][0] == 0.0


def test_wide_non_numeric_column_names_it(tmp_path):
    raw = tmp_path / "wide.csv"
    raw.write_text(
        "trade_date,ticker,stkPx,expirDate,strike,cBidPx,cAskPx,cMidIv,pBidPx,pAskPx,pMidIv,delta\n"
        "2024-01-02,SPY,470.5,2024-01-19,470,abc,6,0.18,4.9,5.1,0.19,0.5\n"
    )
    with pytest.raises(DataError, match="cBidPx"):
        convert(raw, SAMPLES / "wide_mapping.yaml", tmp_path / "data")


@pytest.mark.parametrize("bad_column", ["Date", "Expiry"])
def test_null_date_or_expiration_is_data_error(tmp_path, bad_column):
    lines = (SAMPLES / "long_sample.csv").read_text().splitlines()
    first = lines[1].split(",")
    first[0 if bad_column == "Date" else 3] = ""
    raw = tmp_path / "long.csv"
    raw.write_text("\n".join([lines[0], ",".join(first), *lines[2:]]) + "\n")
    with pytest.raises(DataError, match=f"1 null values in column '{bad_column}'"):
        convert(raw, SAMPLES / "long_mapping.yaml", tmp_path / "data")
