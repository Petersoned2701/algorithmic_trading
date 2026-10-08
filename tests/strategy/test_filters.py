import dataclasses
from datetime import date

import polars as pl
import pytest

from options_bt.data.market import MarketData
from options_bt.errors import ConfigError, DataError
from options_bt.strategy.filters import check, validate_filters
from tests.helpers import flat_market


@pytest.fixture
def events_file(tmp_path):
    path = tmp_path / "ev.csv"
    path.write_text("date,event\n2024-01-10,CPI\n")
    return str(path)


def test_vix_term_structure(ctx_factory):
    assert check(
        {"type": "vix_term_structure", "max_ratio": 1.0}, ctx_factory(vix=15, vix3m=17), "SPY"
    )
    assert not check(
        {"type": "vix_term_structure", "max_ratio": 1.0}, ctx_factory(vix=30, vix3m=25), "SPY"
    )


def test_iv_rank_needs_history(ctx_factory):
    assert not check(
        {"type": "iv_rank", "min": 0, "lookback_days": 252}, ctx_factory(days=10), "SPY"
    )


def test_event_blackout(events_file, ctx_factory):
    cfg = {"type": "event_blackout", "file": events_file, "days_before": 1}
    assert not check(cfg, ctx_factory(on=date(2024, 1, 9)), "SPY")
    assert check(cfg, ctx_factory(on=date(2024, 1, 11)), "SPY")


def test_unknown_filter_and_bad_param():
    with pytest.raises(ConfigError, match="nope"):
        validate_filters([{"type": "nope"}])
    with pytest.raises(ConfigError, match="max_ration"):
        validate_filters([{"type": "vix_term_structure", "max_ration": 1}])


def test_vix_term_structure_missing_value_blocks_entry(ctx_factory):
    no_vix = pl.DataFrame(schema={"date": pl.Date, "value": pl.Float64})
    market = MarketData({**flat_market(vix3m=17.0).series, "vix": no_vix})
    ctx = dataclasses.replace(ctx_factory(), market=market)
    assert not check({"type": "vix_term_structure"}, ctx, "SPY")


def test_event_blackout_days_after_and_default_file(events_file, ctx_factory):
    cfg = {"type": "event_blackout", "file": events_file, "days_before": 0, "days_after": 1}
    assert check(cfg, ctx_factory(on=date(2024, 1, 9)), "SPY")
    assert not check(cfg, ctx_factory(on=date(2024, 1, 10)), "SPY")
    assert not check(cfg, ctx_factory(on=date(2024, 1, 11)), "SPY")
    assert check(cfg, ctx_factory(on=date(2024, 1, 12)), "SPY")
    assert check({"type": "event_blackout"}, ctx_factory(on=date(2024, 1, 9)), "SPY")


def test_event_blackout_missing_file_is_data_error(tmp_path, ctx_factory):
    cfg = {"type": "event_blackout", "file": str(tmp_path / "missing.csv")}
    with pytest.raises(DataError, match="missing.csv"):
        check(cfg, ctx_factory(), "SPY")


@pytest.mark.parametrize(("last", "expected"), [(0.30, True), (0.15, False), (0.10, False)])
def test_iv_rank_window(ctx_factory, monkeypatch, last, expected):
    ctx = ctx_factory()
    ivs = pl.Series([0.10 + 0.002 * i for i in range(100)] + [last])
    monkeypatch.setattr(ctx.history, "atm_iv", lambda *a, **k: ivs)
    cfg = {"type": "iv_rank", "min": 50, "lookback_days": 100}
    assert check(cfg, ctx, "SPY") is expected


def test_iv_rank_flat_history_blocks_entry(ctx_factory, monkeypatch):
    ctx = ctx_factory()
    monkeypatch.setattr(ctx.history, "atm_iv", lambda *a, **k: pl.Series([0.2] * 100))
    assert not check({"type": "iv_rank", "lookback_days": 100}, ctx, "SPY")
