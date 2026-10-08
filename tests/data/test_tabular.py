import logging
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from options_bt.cli import main
from options_bt.data.adapters.tabular import convert, load_mapping
from options_bt.data.schema import VALID_SETTLEMENTS, VALID_STYLES, snapshot_ts
from options_bt.errors import ConfigError, DataError
from tests.helpers import first_chain

SAMPLES = Path(__file__).parent / "samples"
LONG_CSV = SAMPLES / "long_sample.csv"
LONG_MAPPING = SAMPLES / "long_mapping.yaml"


def _mapping(tmp_path, sample, *edits: tuple[str, str]) -> Path:
    """Write a copy of a sample mapping with each (old, new) text edit applied."""
    text = (SAMPLES / f"{sample}_mapping.yaml").read_text()
    for old, new in edits:
        text = text.replace(old, new)
    path = tmp_path / "m.yaml"
    path.write_text(text)
    return path


def _wide_csv(tmp_path, row: str) -> Path:
    """Write a one-row CSV with the wide_sample header."""
    raw = tmp_path / "wide.csv"
    header = (SAMPLES / "wide_sample.csv").read_text().splitlines()[0]
    raw.write_text(f"{header}\n{row}\n")
    return raw


def test_long_layout_values(tmp_path):
    s = convert(LONG_CSV, LONG_MAPPING, tmp_path)
    assert s.rows_written == 4
    c = first_chain(tmp_path)
    assert set(c["right"]) == {"C", "P"}
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
    c = first_chain(tmp_path)
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
        "defaults: {style: european, settlement: cash, multiplier: 100}\n"
    )
    convert(raw, mapping, tmp_path / "data")
    c = first_chain(tmp_path / "data")
    assert c.filter(pl.col("right") == "P")["delta"][0] == -0.6
    assert c["iv"].null_count() == 2
    assert set(c["style"]) == {"european"}


def test_parquet_input(tmp_path):
    raw = tmp_path / "long.parquet"
    pl.read_csv(LONG_CSV).write_parquet(raw)
    mapping = _mapping(tmp_path, "long", ("csv", "parquet"))
    assert convert(raw, mapping, tmp_path / "data").rows_written == 4


def test_missing_column_names_it(tmp_path):
    with pytest.raises(DataError, match="delta"):
        convert(SAMPLES / "long_sample_no_delta.csv", LONG_MAPPING, tmp_path)


def test_canonical_column_absent_from_mapping_names_it(tmp_path):
    mapping = tmp_path / "m.yaml"
    lines = LONG_MAPPING.read_text().splitlines()
    mapping.write_text("\n".join(line for line in lines if "Bid" not in line))
    with pytest.raises(DataError, match="bid"):
        convert(LONG_CSV, mapping, tmp_path / "data")


def test_unexpected_right_values_listed(tmp_path):
    mapping = _mapping(tmp_path, "long", ("P: put", "P: PUT"))
    with pytest.raises(DataError, match="'put'"):
        convert(LONG_CSV, mapping, tmp_path / "data")


def test_unreadable_file_names_path(tmp_path):
    missing = tmp_path / "nope.csv"
    with pytest.raises(DataError, match="nope.csv"):
        convert(missing, LONG_MAPPING, tmp_path / "data")


def test_bad_date_is_data_error(tmp_path):
    mapping = _mapping(tmp_path, "long", ("%m/%d/%Y", "%Y-%m-%d"))
    with pytest.raises(DataError, match="Date"):
        convert(LONG_CSV, mapping, tmp_path / "data")


def test_unverified_mapping_warns(tmp_path, caplog):
    mapping = _mapping(tmp_path, "long", ("verified: true", "verified: false"))
    with caplog.at_level(logging.WARNING):
        convert(LONG_CSV, mapping, tmp_path / "data")
    assert "mapping m is unverified; check a sample before trusting results" in caplog.messages


def test_verified_mapping_does_not_warn(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        convert(LONG_CSV, LONG_MAPPING, tmp_path)
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
    with pytest.raises(ConfigError):
        load_mapping(_mapping(tmp_path, "long", edit))


def test_wide_mapping_requires_call_and_put(tmp_path):
    mapping = _mapping(tmp_path, "wide")
    mapping.write_text(mapping.read_text().split("call:")[0])
    with pytest.raises(ConfigError, match="call"):
        load_mapping(mapping)


def test_cli_import_tabular(tmp_path, capsys):
    code = main(
        ["data", "import", "tabular", str(LONG_CSV)]
        + ["--mapping", str(LONG_MAPPING), "--data-root", str(tmp_path)]
    )
    assert code == 0
    assert "wrote 4 rows" in capsys.readouterr().out


def test_wide_put_delta_required_unless_derived(tmp_path):
    mapping = _mapping(
        tmp_path, "wide", ("put_delta_from_call: true", "put_delta_from_call: false")
    )
    with pytest.raises(ConfigError, match="delta"):
        load_mapping(mapping)


def test_wide_requires_bid_ask_on_both_sides(tmp_path):
    with pytest.raises(ConfigError, match="put.*bid"):
        load_mapping(_mapping(tmp_path, "wide", ("  bid: pBidPx\n", "")))


def test_wide_integral_bid_on_one_side_is_cast(tmp_path):
    raw = _wide_csv(tmp_path, "2024-01-02,SPY,470.5,2024-01-19,470,5,6,0.18,4.9,5.1,0.19,1")
    convert(raw, SAMPLES / "wide_mapping.yaml", tmp_path / "data")
    c = first_chain(tmp_path / "data")
    assert c.filter(pl.col("right") == "C")["bid"][0] == 5.0
    assert c.filter(pl.col("right") == "P")["delta"][0] == 0.0


def test_wide_non_numeric_column_names_it(tmp_path):
    raw = _wide_csv(tmp_path, "2024-01-02,SPY,470.5,2024-01-19,470,abc,6,0.18,4.9,5.1,0.19,0.5")
    with pytest.raises(DataError, match="cBidPx"):
        convert(raw, SAMPLES / "wide_mapping.yaml", tmp_path / "data")


@pytest.mark.parametrize("bad_column", ["Date", "Expiry"])
def test_null_date_or_expiration_is_data_error(tmp_path, bad_column):
    lines = LONG_CSV.read_text().splitlines()
    first = lines[1].split(",")
    first[0 if bad_column == "Date" else 3] = ""
    raw = tmp_path / "long.csv"
    raw.write_text("\n".join([lines[0], ",".join(first), *lines[2:]]) + "\n")
    with pytest.raises(DataError, match=f"1 null values in column '{bad_column}'"):
        convert(raw, LONG_MAPPING, tmp_path / "data")


def test_second_tabular_import_needs_replace_and_new_values_win(tmp_path):
    convert(LONG_CSV, LONG_MAPPING, tmp_path)
    with pytest.raises(DataError, match="--replace"):
        convert(LONG_CSV, LONG_MAPPING, tmp_path)
    raw = tmp_path / "changed.csv"
    raw.write_text(LONG_CSV.read_text().replace(",5.1,5.3,", ",5.0,5.4,"))
    s = convert(raw, LONG_MAPPING, tmp_path, replace=True)
    chain = first_chain(tmp_path)
    call = chain.filter((pl.col("right") == "C") & (pl.col("strike") == 470.0)).row(0, named=True)
    assert s.rows_written == 4 and chain.height == 4
    assert (call["bid"], call["ask"]) == (5.0, 5.4)


@pytest.mark.parametrize("name", ["dubach", "orats"])
def test_shipped_mapping_loads_and_defaults_pass_validation(name):
    mapping = load_mapping(Path("configs/mappings") / f"{name}.yaml")
    assert mapping.defaults["settlement"] in VALID_SETTLEMENTS
    assert mapping.defaults["style"] in VALID_STYLES
