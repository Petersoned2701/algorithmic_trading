import logging
import math

log = logging.getLogger(__name__)


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

    qty = math.floor(max_loss_pct_equity / 100 * equity / requirement_per_unit)
    if qty <= 0:
        return 0, "size_zero"

    room = max_total_max_loss_pct / 100 * equity - current_requirement
    qty = min(qty, math.floor(room / requirement_per_unit))
    if qty <= 0:
        return 0, "portfolio_cap"

    qty = min(qty, math.floor(cash / requirement_per_unit))
    if qty <= 0:
        return 0, "insufficient_cash"
    return qty, None
