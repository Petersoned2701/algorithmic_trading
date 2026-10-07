import logging
from collections.abc import Callable
from dataclasses import dataclass

from options_bt.strategy.config import ExitConfig

log = logging.getLogger(__name__)


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


EXITS: dict[str, Callable[[ExitInputs, float], bool]] = {
    "profit_target_pct": _profit_target,
    "stop_loss_multiple": _stop_loss,
    "dte_exit": _dte_exit,
}


def exit_reason(inputs: ExitInputs, cfg: ExitConfig) -> str | None:
    for name, rule in EXITS.items():
        value = getattr(cfg, name)
        if value is not None and rule(inputs, value):
            return name.removesuffix("_pct").removesuffix("_multiple")
    return None
