from datetime import date
from typing import NamedTuple

import polars as pl


class ContractKey(NamedTuple):
    underlying: str
    expiration: date
    strike: float
    right: str


Quotes = dict[ContractKey, tuple[float, float]]


def index_quotes(chain: pl.DataFrame) -> Quotes:
    """Map each contract in one snapshot to its (bid, ask)."""
    key_columns = (chain[c].to_list() for c in ContractKey._fields)
    keys = zip(*key_columns, strict=True)  # plain tuples: equal to ContractKey, much cheaper
    return dict(
        zip(keys, zip(chain["bid"].to_list(), chain["ask"].to_list(), strict=True), strict=True)
    )
