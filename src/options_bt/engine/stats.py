from dataclasses import dataclass, field


@dataclass
class RunStats:
    stale_marks: int = 0
    deferred_closes: int = 0
    skipped_entries: int = 0
    spread_cost: float = 0.0
    rejections: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.rejections[reason] = self.rejections.get(reason, 0) + 1
