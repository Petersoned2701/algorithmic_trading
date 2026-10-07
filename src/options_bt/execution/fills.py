import logging
from collections.abc import Mapping, Sequence

import polars as pl

from options_bt.data.chain import find_quote
from options_bt.engine.position import Leg

log = logging.getLogger(__name__)

DEFAULT_FILL_FRACTION = {1: 0.75, 2: 0.66, 3: 0.56, 4: 0.53}


class FillModel:
    """Prices each leg at a fraction of the bid-ask spread away from the favourable side."""

    def __init__(
        self,
        fill_fraction: Mapping[int, float] = DEFAULT_FILL_FRACTION,
        override: float | None = None,
    ):
        self.fill_fraction = fill_fraction
        self.override = override

    def fraction(self, n_legs: int) -> float:
        if self.override is not None:
            return self.override
        return self.fill_fraction[min(n_legs, max(self.fill_fraction))]

    def leg_price(self, bid: float, ask: float, buying: bool, n_legs: int) -> float:
        f = self.fraction(n_legs)
        return bid + f * (ask - bid) if buying else ask - f * (ask - bid)

    def prices(self, chain: pl.DataFrame, legs: Sequence[Leg], opening: bool) -> list[float] | None:
        result = []
        for leg in legs:
            quote = find_quote(chain, leg.key)
            if quote is None:
                log.debug("no quote for %s", leg.key)
                return None
            buying = (leg.qty > 0) == opening
            result.append(self.leg_price(quote["bid"], quote["ask"], buying, len(legs)))
        return result


def mid_prices(chain: pl.DataFrame, legs: Sequence[Leg]) -> list[float] | None:
    result = []
    for leg in legs:
        quote = find_quote(chain, leg.key)
        if quote is None:
            return None
        result.append((quote["bid"] + quote["ask"]) / 2)
    return result
