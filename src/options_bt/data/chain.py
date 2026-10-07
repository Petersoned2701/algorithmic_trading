from dataclasses import dataclass
from datetime import date

import polars as pl


@dataclass(frozen=True)
class ContractKey:
    underlying: str
    expiration: date
    strike: float
    right: str


def find_quote(chain: pl.DataFrame, key: ContractKey) -> dict | None:
    rows = chain.filter(
        (pl.col("underlying") == key.underlying)
        & (pl.col("expiration") == key.expiration)
        & (pl.col("strike") == key.strike)
        & (pl.col("right") == key.right)
    )
    return rows.row(0, named=True) if rows.height else None
