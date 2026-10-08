import logging
import math

log = logging.getLogger(__name__)


def _units(budget: float, requirement: float) -> int:
    # The tolerance keeps an exact fit (0.3 / 0.1 is 2.9999999999999996) from losing a unit.
    return math.floor(budget / requirement + 1e-9)


def size(
    requirement_per_unit: float | None,
    *,
    equity: float,
    cash: float,
    current_requirement: float,
    max_loss_pct_equity: float,
    max_total_max_loss_pct: float,
) -> tuple[int, str | None]:
    """Units to open and the rejection reason (None when quantity > 0)."""
    if requirement_per_unit is None:
        return 0, "undefined_risk"
    if requirement_per_unit <= 0:
        log.debug("non-positive requirement %s; refusing to size", requirement_per_unit)
        return 0, "size_zero"

    qty = _units(max_loss_pct_equity / 100 * equity, requirement_per_unit)
    if qty <= 0:
        return 0, "size_zero"

    room = max_total_max_loss_pct / 100 * equity - current_requirement
    qty = min(qty, _units(room, requirement_per_unit))
    if qty <= 0:
        return 0, "portfolio_cap"

    qty = min(qty, _units(cash, requirement_per_unit))
    if qty <= 0:
        return 0, "insufficient_cash"
    return qty, None
