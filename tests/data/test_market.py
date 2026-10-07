from datetime import date

import pytest

from options_bt.data.market import MarketData
from options_bt.data.schema import snapshot_ts
from options_bt.errors import DataError


def test_asof_uses_last_value_at_or_before(tmp_path):
    (tmp_path / "market").mkdir()
    (tmp_path / "market/vix.csv").write_text("date,value\n2024-01-02,15\n2024-01-04,20\n")
    m = MarketData.load(tmp_path)
    assert m.asof("vix", snapshot_ts(date(2024, 1, 3))) == 15.0
    assert m.asof("vix", snapshot_ts(date(2024, 1, 4))) == 20.0
    assert m.asof("vix", snapshot_ts(date(2023, 12, 29))) is None


def test_unknown_series_raises(tmp_path):
    with pytest.raises(DataError, match="vix3m"):
        MarketData.load(tmp_path).asof("vix3m", snapshot_ts(date(2024, 1, 2)))


def test_unsorted_csv_is_sorted_on_load(tmp_path):
    (tmp_path / "market").mkdir()
    (tmp_path / "market/vix.csv").write_text("date,value\n2024-01-04,20\n2024-01-02,15\n")
    m = MarketData.load(tmp_path)
    assert m.asof("vix", snapshot_ts(date(2024, 1, 3))) == 15.0


@pytest.mark.parametrize(
    "content",
    ["when,value\n2024-01-02,15\n", "date,value\nnot-a-date,15\n", "date,value\n2024-01-02,abc\n"],
)
def test_malformed_csv_raises_naming_file(tmp_path, content):
    (tmp_path / "market").mkdir()
    (tmp_path / "market/vix.csv").write_text(content)
    with pytest.raises(DataError, match="vix.csv"):
        MarketData.load(tmp_path)


def test_example_csvs_cover_2024():
    from pathlib import Path

    m = MarketData.load(Path(__file__).parents[2] / "examples")
    assert m.asof("tbill", snapshot_ts(date(2024, 6, 3))) == 5.0
    assert m.asof("vix", snapshot_ts(date(2024, 8, 5))) == 30.0
    assert m.asof("vix3m", snapshot_ts(date(2024, 8, 5))) == 25.0
    assert m.asof("vix", snapshot_ts(date(2024, 8, 6))) == 15.0
    assert m.asof("vix", snapshot_ts(date(2024, 1, 1))) is None
