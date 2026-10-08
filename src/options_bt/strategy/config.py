from datetime import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from options_bt.execution.fills import DEFAULT_FILL_FRACTION
from options_bt.loaders import validate_model

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
    profit_target_pct: float | None = Field(default=None, gt=0)
    stop_loss_multiple: float | None = Field(default=None, gt=0)
    dte_exit: int | None = Field(default=None, ge=0)


class SizingConfig(_Model):
    max_loss_pct_equity: float = Field(gt=0, le=100)


class PortfolioCaps(_Model):
    max_total_max_loss_pct: float = Field(default=100.0, gt=0, le=100)


class CostConfig(_Model):
    commission_per_contract: float = Field(default=0.65, ge=0)
    per_order_fee: float = Field(default=0.0, ge=0)
    fill_fraction: dict[int, float] = Field(default_factory=lambda: dict(DEFAULT_FILL_FRACTION))
    fill_fraction_override: float | None = Field(default=None, ge=0, le=1)

    @field_validator("fill_fraction")
    @classmethod
    def _fill_fractions_in_range(cls, value):
        if not value:
            raise ValueError("fill_fraction must not be empty")
        if any(legs < 1 for legs in value):
            raise ValueError("fill_fraction keys are leg counts and must be >= 1")
        if any(not 0 <= fraction <= 1 for fraction in value.values()):
            raise ValueError("fill_fraction values must be between 0 and 1")
        return value


class AccountConfig(_Model):
    initial_cash: float = Field(default=15000.0, gt=0)
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
    underlyings: list[str] = Field(min_length=1)
    entry: EntryConfig
    exits: ExitConfig = ExitConfig()
    sizing: SizingConfig
    portfolio_caps: PortfolioCaps = PortfolioCaps()
    costs: CostConfig = CostConfig()
    account: AccountConfig = AccountConfig()
    margin_model: str = "defined_risk"


def parse_config(raw: dict) -> StrategyConfig:
    return validate_model(StrategyConfig, raw)
