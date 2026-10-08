from datetime import date
from typing import NamedTuple

import polars as pl


class ContractKey(NamedTuple):
    underlying: str
    expiration: date
    strike: float
    right: str


def index_quotes(chain: pl.DataFrame) -> dict[ContractKey, tuple[float, float]]:
    """Map each contract in one snapshot to its (bid, ask)."""
    key_columns = (chain[c].to_list() for c in ContractKey._fields)
    keys = map(ContractKey._make, zip(*key_columns, strict=True))
    return dict(
        zip(keys, zip(chain["bid"].to_list(), chain["ask"].to_list(), strict=True), strict=True)
    )
