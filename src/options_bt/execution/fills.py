import logging
from collections.abc import Mapping, Sequence

from options_bt.data.chain import ContractKey
from options_bt.engine.position import Leg

log = logging.getLogger(__name__)

Quotes = Mapping[ContractKey, tuple[float, float]]
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

    def prices(self, quotes: Quotes, legs: Sequence[Leg], opening: bool) -> list[float] | None:
        found = _quotes_for(quotes, legs)
        if found is None:
            return None
        return [
            self.leg_price(bid, ask, (leg.qty > 0) == opening, len(legs))
            for leg, (bid, ask) in zip(legs, found, strict=True)
        ]


def mid_prices(quotes: Quotes, legs: Sequence[Leg]) -> list[float] | None:
    found = _quotes_for(quotes, legs)
    return None if found is None else [(bid + ask) / 2 for bid, ask in found]


def _quotes_for(quotes: Quotes, legs: Sequence[Leg]) -> list[tuple[float, float]] | None:
    found = []
    for leg in legs:
        quote = quotes.get(leg.key)
        if quote is None:
            log.debug("no quote for %s", leg.key)
            return None
        found.append(quote)
    return found
