from collections.abc import Sequence

from options_bt.engine.position import Leg


def commission(
    legs: Sequence[Leg], quantity: int, per_contract: float, per_order: float = 0.0
) -> float:
    return sum(abs(leg.qty) for leg in legs) * quantity * per_contract + per_order
