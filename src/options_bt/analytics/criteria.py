"""Go/no-go criteria that decide whether a strategy is worth paper trading."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from options_bt.errors import ConfigError
from options_bt.strategy.config import load_raw


class Criteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_net_return: float = 0.0
    min_excess_return: float = 0.0
    max_drawdown: float = 0.25
    max_stress_loss: float = 0.15
    min_oos_net_return: float = 0.0
    min_robustness: float = 0.60


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Literal["PASS", "FAIL", "N/A"]
    actual: float | None
    threshold: float


def load_criteria(path: Path | str) -> Criteria:
    try:
        return Criteria.model_validate(load_raw(Path(path)))
    except ValidationError as exc:
        lines = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise ConfigError(f"invalid criteria in {path}: " + "; ".join(lines)) from exc


def _check(name: str, actual: float | None, threshold: float, passes) -> CheckResult:
    if actual is None:
        return CheckResult(name, "N/A", None, threshold)
    return CheckResult(name, "PASS" if passes(actual, threshold) else "FAIL", actual, threshold)


def evaluate(
    criteria: Criteria,
    metrics: dict,
    stress: list[dict],
    split: dict | None,
    robustness: float | None = None,
) -> list[CheckResult]:
    losses = [
        max(-row["return"], row.get("max_drawdown") or 0.0)
        for row in stress
        if row.get("return") is not None
    ]
    worst_stress = 0.0 - max(losses) if losses else None
    traded = metrics.get("trades") != 0
    oos_return = None if split is None or not traded else split["out_of_sample"]["net_return"]
    return [
        _check(
            "net_return",
            metrics.get("net_return") if traded else None,
            criteria.min_net_return,
            lambda a, t: a > t,
        ),
        _check(
            "excess_return",
            metrics.get("excess_annualized_return") if traded else None,
            criteria.min_excess_return,
            lambda a, t: a > t,
        ),
        _check(
            "max_drawdown", metrics.get("max_drawdown"), criteria.max_drawdown, lambda a, t: a <= t
        ),
        _check(
            "worst_stress_loss",
            worst_stress,
            -criteria.max_stress_loss,
            lambda a, t: a >= t,
        ),
        _check("oos_net_return", oos_return, criteria.min_oos_net_return, lambda a, t: a > t),
        _check("robustness", robustness, criteria.min_robustness, lambda a, t: a >= t),
    ]
