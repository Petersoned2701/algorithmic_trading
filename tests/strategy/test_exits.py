from options_bt.strategy.config import ExitConfig
from options_bt.strategy.exits import ExitInputs, exit_reason

CFG = ExitConfig(profit_target_pct=50, stop_loss_multiple=2.0, dte_exit=21)


def test_profit_target():
    assert exit_reason(ExitInputs(50.0, 100.0, 30), CFG) == "profit_target"


def test_stop_loss():
    assert exit_reason(ExitInputs(-200.0, 100.0, 30), CFG) == "stop_loss"


def test_dte_exit():
    assert exit_reason(ExitInputs(0.0, 100.0, 21), CFG) == "dte_exit"


def test_no_exit():
    assert exit_reason(ExitInputs(10.0, 100.0, 30), CFG) is None


def test_unset_rules_ignored():
    assert exit_reason(ExitInputs(-1e6, 100.0, 0), ExitConfig()) is None


def test_first_matching_rule_wins():
    assert exit_reason(ExitInputs(50.0, 100.0, 5), CFG) == "profit_target"


def test_zero_basis_flat_pnl_triggers_neither_pnl_rule():
    assert exit_reason(ExitInputs(0.0, 0.0, 30), CFG) is None


def test_zero_basis_profit_target_requires_positive_pnl():
    cfg = ExitConfig(profit_target_pct=50)
    assert exit_reason(ExitInputs(0.0, 0.0, 30), cfg) is None
    assert exit_reason(ExitInputs(0.01, 0.0, 30), cfg) == "profit_target"


def test_zero_basis_stop_loss_requires_negative_pnl():
    cfg = ExitConfig(stop_loss_multiple=2.0)
    assert exit_reason(ExitInputs(0.0, 0.0, 30), cfg) is None
    assert exit_reason(ExitInputs(-0.01, 0.0, 30), cfg) == "stop_loss"
