from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import polars as pl

from options_bt.data.chain import Quotes
from options_bt.data.history import History
from options_bt.data.market import MarketData
from options_bt.engine.position import Leg, Position
from options_bt.execution.fills import FillModel


@dataclass
class OpenOrder:
    underlying: str
    legs: list[Leg]
    reason: str
    tags: dict = field(default_factory=dict)


@dataclass
class CloseOrder:
    position_id: int
    reason: str


Order = OpenOrder | CloseOrder


@dataclass
class RunStats:
    stale_marks: int = 0
    deferred_closes: int = 0
    skipped_entries: int = 0
    spread_cost: float = 0.0
    rejections: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.rejections[reason] = self.rejections.get(reason, 0) + 1


@dataclass
class StepContext:
    ts: datetime
    chains: Mapping[str, pl.DataFrame]
    quotes: Mapping[str, Quotes]
    positions: Mapping[int, Position]
    equity: float
    market: MarketData
    history: History
    fill_model: FillModel
    stats: RunStats


class Strategy(Protocol):
    def on_step(self, ctx: StepContext) -> list[Order]: ...
