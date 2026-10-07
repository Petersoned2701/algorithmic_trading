from collections.abc import Sequence
from typing import Protocol

from options_bt.engine.position import Leg, max_loss
from options_bt.errors import ConfigError


class MarginModel(Protocol):
    def requirement(self, legs: Sequence[Leg], net_premium: float) -> float | None: ...


class DefinedRiskMargin:
    def requirement(self, legs: Sequence[Leg], net_premium: float) -> float | None:
        return max_loss(legs, net_premium)


def margin_model(name: str) -> MarginModel:
    if name == "defined_risk":
        return DefinedRiskMargin()
    raise ConfigError(f"unknown margin model {name!r}; expected 'defined_risk'")
