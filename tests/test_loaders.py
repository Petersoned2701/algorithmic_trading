import polars as pl
import pytest
import yaml
from pydantic import BaseModel, ConfigDict

from options_bt.errors import ConfigError, DataError
from options_bt.loaders import load_yaml, read_dated_csv, read_table, validate_model
from tests.helpers import PCS


def test_load_yaml_reads_mapping(tmp_path):
    path = tmp_path / "pcs.yaml"
    path.write_text(yaml.safe_dump(PCS))
    assert load_yaml(path)["name"] == "pcs_spy_45dte"


def test_load_yaml_missing_file_names_path(tmp_path):
    with pytest.raises(ConfigError, match="missing.yaml"):
        load_yaml(tmp_path / "missing.yaml")


def test_load_yaml_invalid_yaml(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("a: [unclosed")
    with pytest.raises(ConfigError, match="bad.yaml"):
        load_yaml(path)


@pytest.mark.parametrize(
    "text, kind, shape", [("- 1\n- 2\n", dict, "mapping"), ("a: 1\n", list, "list")]
)
def test_load_yaml_wrong_top_level_type(tmp_path, text, kind, shape):
    path = tmp_path / "shape.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=rf"shape.yaml must be a YAML {shape}"):
        load_yaml(path, kind)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: int
    nested: dict[str, int] = {}


def test_validate_model_lists_dotted_locations_under_a_source_header():
    with pytest.raises(ConfigError) as exc:
        validate_model(_Model, {"a": "x", "nested": {"k": "y"}, "z": 1}, "thing in t.yaml")
    lines = str(exc.value).splitlines()
    assert lines[0] == "invalid thing in t.yaml:"
    assert any(line.startswith("a: ") for line in lines)
    assert any(line.startswith("nested.k: ") for line in lines)
    assert any(line.startswith("z: ") for line in lines)


def test_validate_model_without_source_has_no_header():
    with pytest.raises(ConfigError) as exc:
        validate_model(_Model, {})
    assert str(exc.value).startswith("a: ")


def test_validate_model_returns_the_model():
    assert validate_model(_Model, {"a": 1}).a == 1


@pytest.mark.parametrize("fmt", ["csv", "parquet"])
def test_read_table_names_what_and_path(tmp_path, fmt):
    path = tmp_path / f"nope.{fmt}"
    with pytest.raises(DataError, match=f"cannot read price path .*nope.{fmt}"):
        read_table(path, "price path", fmt)
    df = pl.DataFrame({"a": [1], "b": [2]})
    (df.write_csv if fmt == "csv" else df.write_parquet)(path)
    assert read_table(path, "price path", fmt).columns == ["a", "b"]


def test_read_dated_csv_parses_sorts_and_casts(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text("date,value\n2024-01-04,20\n2024-01-02,15.5\n")
    df = read_dated_csv(path, "series", ["value"])
    assert df["date"].to_list()[0].isoformat() == "2024-01-02"
    assert df["value"].to_list() == [15.5, 20.0]


@pytest.mark.parametrize("text", ["date,value\nnot-a-date,1\n", "date,value\n2024-01-02,abc\n"])
def test_read_dated_csv_bad_content_names_file(tmp_path, text):
    path = tmp_path / "s.csv"
    path.write_text(text)
    with pytest.raises(DataError, match="s.csv"):
        read_dated_csv(path, "series", ["value"])
