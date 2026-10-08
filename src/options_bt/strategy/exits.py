from collections.abc import Callable
from dataclasses import dataclass

from options_bt.strategy.config import ExitConfig


@dataclass(frozen=True)
class ExitInputs:
    pnl_per_unit: float
    basis: float
    dte: int


def _profit_target(inputs: ExitInputs, pct: float) -> bool:
    if inputs.basis == 0:
        return inputs.pnl_per_unit > 0
    return inputs.pnl_per_unit >= pct / 100 * inputs.basis


def _stop_loss(inputs: ExitInputs, multiple: float) -> bool:
    if inputs.basis == 0:
        return inputs.pnl_per_unit < 0
    return -inputs.pnl_per_unit >= multiple * inputs.basis


def _dte_exit(inputs: ExitInputs, dte: float) -> bool:
    return inputs.dte <= dte


_EXITS: tuple[tuple[str, str, Callable[[ExitInputs, float], bool]], ...] = (
    ("profit_target_pct", "profit_target", _profit_target),
    ("stop_loss_multiple", "stop_loss", _stop_loss),
    ("dte_exit", "dte_exit", _dte_exit),
)


def exit_reason(inputs: ExitInputs, cfg: ExitConfig) -> str | None:
    for field, reason, rule in _EXITS:
        value = getattr(cfg, field)
        if value is not None and rule(inputs, value):
            return reason
    return None
