from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from options_bt.errors import ConfigError
from options_bt.execution.fills import DEFAULT_FILL_FRACTION

_RIGHTS = {"put": "P", "p": "P", "call": "C", "c": "C"}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LegSpec(_Model):
    right: Literal["P", "C"]
    side: Literal["long", "short"]
    ratio: int = Field(default=1, ge=1)
    dte: tuple[int, int] | None = None
    delta: float | None = Field(default=None, gt=0, lt=1)
    ref: int | None = None
    strike_offset: float | None = None

    @field_validator("right", mode="before")
    @classmethod
    def _normalise_right(cls, value):
        if isinstance(value, str):
            return _RIGHTS.get(value.lower(), value)
        return value

    @field_validator("dte")
    @classmethod
    def _dte_range(cls, value):
        if value is not None and not 0 <= value[0] <= value[1]:
            raise ValueError("dte must satisfy 0 <= min <= max")
        return value

    @model_validator(mode="after")
    def _one_selector(self):
        by_delta = self.dte is not None and self.delta is not None
        by_ref = self.ref is not None and self.strike_offset is not None
        if self.ref is None and self.strike_offset is not None:
            raise ValueError("strike_offset requires ref")
        if self.ref is not None and self.delta is not None:
            raise ValueError("a leg uses either dte+delta or ref+strike_offset, not both")
        if by_delta == by_ref:
            raise ValueError("a leg needs exactly one of dte+delta or ref+strike_offset")
        return self


class Schedule(_Model):
    weekdays: list[Literal["MON", "TUE", "WED", "THU", "FRI"]] | None = None
    every_n_steps: int | None = Field(default=None, ge=1)


class EntryConfig(_Model):
    schedule: Schedule = Schedule()
    max_open_positions: int | None = Field(default=None, ge=1)
    filters: list[dict] = []
    legs: list[LegSpec] = Field(min_length=1)

    @field_validator("filters")
    @classmethod
    def _filters_have_type(cls, value):
        for i, item in enumerate(value):
            if "type" not in item:
                raise ValueError(f"filter {i} needs a 'type' key")
        return value

    @model_validator(mode="after")
    def _refs_point_backwards(self):
        for i, leg in enumerate(self.legs):
            if leg.ref is not None and not 0 <= leg.ref < i:
                raise ValueError(f"leg {i}: ref {leg.ref} must point to an earlier leg")
        return self


class ExitConfig(_Model):
    profit_target_pct: float | None = None
    stop_loss_multiple: float | None = None
    dte_exit: int | None = None


class SizingConfig(_Model):
    max_loss_pct_equity: float


class PortfolioCaps(_Model):
    max_total_max_loss_pct: float = 100.0


class CostConfig(_Model):
    commission_per_contract: float = 0.65
    per_order_fee: float = 0.0
    fill_fraction: dict[int, float] = Field(default_factory=lambda: dict(DEFAULT_FILL_FRACTION))
    fill_fraction_override: float | None = None


class AccountConfig(_Model):
    initial_cash: float = 15000.0
    cash_interest: bool = False
    session_close: time = time(15, 45)

    @field_validator("session_close", mode="before")
    @classmethod
    def _quote_clock_time(cls, value):
        if isinstance(value, int):
            raise ValueError(
                f'session_close {value} was read as a number; quote the time, e.g. "15:45"'
            )
        return value

    @field_validator("session_close")
    @classmethod
    def _naive_clock_time(cls, value):
        if value.tzinfo is not None:
            raise ValueError("session_close is a New York wall-clock time; omit the UTC offset")
        return value


class StrategyConfig(_Model):
    name: str
    underlyings: list[str]
    entry: EntryConfig
    exits: ExitConfig = ExitConfig()
    sizing: SizingConfig
    portfolio_caps: PortfolioCaps = PortfolioCaps()
    costs: CostConfig = CostConfig()
    account: AccountConfig = AccountConfig()
    margin_model: str = "defined_risk"


def load_raw(path: Path) -> dict:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config {path} must be a YAML mapping at the top level")
    return raw


def parse_config(raw: dict) -> StrategyConfig:
    try:
        return StrategyConfig.model_validate(raw)
    except ValidationError as exc:
        lines = [
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()
        ]
        raise ConfigError("\n".join(lines)) from exc
