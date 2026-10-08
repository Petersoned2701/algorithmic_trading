import copy
from datetime import date

import pytest

from options_bt.errors import ConfigError
from options_bt.strategy.base import CloseOrder, OpenOrder
from options_bt.strategy.config import parse_config
from options_bt.strategy.rule_strategy import RuleStrategy
from tests.helpers import PCS_NO_FILTERS


def _cfg(**entry_overrides):
    cfg = copy.deepcopy(PCS_NO_FILTERS)
    cfg["entry"].update(entry_overrides)
    return cfg


def test_enters_on_scheduled_weekday_only(ctx_factory):
    s = RuleStrategy(parse_config(PCS_NO_FILTERS))  # weekdays [MON, THU]
    orders = s.on_step(ctx_factory(on=date(2024, 1, 8)))  # Monday
    assert any(isinstance(o, OpenOrder) for o in orders)
    assert s.on_step(ctx_factory(on=date(2024, 1, 9))) == []  # Tuesday


def test_open_order_carries_legs_and_strategy_tag(ctx_factory):
    orders = RuleStrategy(parse_config(PCS_NO_FILTERS)).on_step(ctx_factory(on=date(2024, 1, 8)))
    [order] = orders
    assert isinstance(order, OpenOrder)
    assert order.underlying == "SPY"
    assert order.reason == "entry"
    assert order.tags == {"strategy": "pcs_spy_45dte"}
    assert [leg.qty for leg in order.legs] == [-1, 1]


def test_profit_target_emits_close(ctx_factory):
    ctx = ctx_factory(on=date(2024, 1, 9), open_pcs_with_credit=5.0)  # rich credit, cheap now
    orders = RuleStrategy(parse_config(PCS_NO_FILTERS)).on_step(ctx)
    assert [o.reason for o in orders if isinstance(o, CloseOrder)] == ["profit_target"]


def test_no_exit_when_pnl_within_limits(ctx_factory):
    ctx = ctx_factory(on=date(2024, 1, 9), open_pcs_with_credit=0.5)
    assert RuleStrategy(parse_config(PCS_NO_FILTERS)).on_step(ctx) == []


def test_position_skipped_when_closing_quotes_missing(ctx_factory):
    ctx = ctx_factory(on=date(2024, 1, 9), open_pcs_with_credit=5.0)
    ctx.quotes = {"SPY": {}}
    assert RuleStrategy(parse_config(PCS_NO_FILTERS)).on_step(ctx) == []


def test_other_strategys_positions_are_ignored(ctx_factory):
    ctx = ctx_factory(on=date(2024, 1, 9), open_pcs_with_credit=5.0)
    for position in ctx.positions.values():
        position.tags = {"strategy": "someone_else"}
    assert RuleStrategy(parse_config(PCS_NO_FILTERS)).on_step(ctx) == []


def test_no_contract_counts_skip(ctx_factory):
    cfg = copy.deepcopy(PCS_NO_FILTERS)
    cfg["entry"]["legs"][0]["dte"] = [400, 500]
    ctx = ctx_factory(on=date(2024, 1, 8))
    assert RuleStrategy(parse_config(cfg)).on_step(ctx) == [] and ctx.stats.skipped_entries == 1


def test_max_open_positions_respected(ctx_factory):
    cfg = _cfg(max_open_positions=1)
    ctx = ctx_factory(on=date(2024, 1, 8), open_pcs_with_credit=1.0)
    assert not any(isinstance(o, OpenOrder) for o in RuleStrategy(parse_config(cfg)).on_step(ctx))


def test_every_n_steps_counts_calls_and_first_step_is_eligible(ctx_factory):
    cfg = _cfg(schedule={"every_n_steps": 2})
    s = RuleStrategy(parse_config(cfg))
    day = date(2024, 1, 8)
    entered = [bool(s.on_step(ctx_factory(on=day))) for _ in range(4)]
    assert entered == [True, False, True, False]


def test_weekday_and_every_n_steps_must_both_hold(ctx_factory):
    cfg = _cfg(schedule={"weekdays": ["MON"], "every_n_steps": 2})
    s = RuleStrategy(parse_config(cfg))
    assert s.on_step(ctx_factory(on=date(2024, 1, 9))) == []  # step 0, Tuesday
    assert s.on_step(ctx_factory(on=date(2024, 1, 8))) == []  # step 1, Monday
    assert s.on_step(ctx_factory(on=date(2024, 1, 8)))  # step 2, Monday


def test_no_schedule_enters_every_step(ctx_factory):
    s = RuleStrategy(parse_config(_cfg(schedule={})))
    assert all(s.on_step(ctx_factory(on=date(2024, 1, 9))) for _ in range(3))


def test_filter_rejection_blocks_entry_and_logs_debug(ctx_factory, caplog):
    cfg = _cfg(filters=[{"type": "vix_term_structure", "max_ratio": 1.0}])
    ctx = ctx_factory(on=date(2024, 1, 8), vix=20.0, vix3m=17.0)
    with caplog.at_level("DEBUG", logger="options_bt"):
        assert RuleStrategy(parse_config(cfg)).on_step(ctx) == []
    assert any(r.levelname == "DEBUG" for r in caplog.records)
    assert ctx.stats.skipped_entries == 0
    assert ctx.stats.rejections == {"filter:vix_term_structure": 1}


def test_filter_passing_allows_entry(ctx_factory):
    cfg = _cfg(filters=[{"type": "vix_term_structure", "max_ratio": 1.0}])
    ctx = ctx_factory(on=date(2024, 1, 8), vix=15.0, vix3m=17.0)
    assert RuleStrategy(parse_config(cfg)).on_step(ctx)


def test_underlying_without_chain_is_skipped_silently(ctx_factory):
    cfg = copy.deepcopy(PCS_NO_FILTERS)
    cfg["underlyings"] = ["QQQ", "SPY"]
    ctx = ctx_factory(on=date(2024, 1, 8))
    orders = RuleStrategy(parse_config(cfg)).on_step(ctx)
    assert [o.underlying for o in orders] == ["SPY"]
    assert ctx.stats.skipped_entries == 0


def test_constructor_validates_filters():
    cfg = _cfg(filters=[{"type": "nope"}])
    with pytest.raises(ConfigError):
        RuleStrategy(parse_config(cfg))
