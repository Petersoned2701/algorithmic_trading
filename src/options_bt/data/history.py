from bisect import bisect_right
from datetime import datetime

import polars as pl

from options_bt.data.store import QuoteStore


class History:
    """Point-in-time view of the store: every read is limited to `ts <= now`."""

    def __init__(self, store: QuoteStore, now: datetime):
        self._store = store
        self._now = now

    def underlying_prices(self, underlying: str, lookback: int) -> pl.Series:
        df = self._store.underlying_series(underlying)
        ts = self._store.series_ts("underlying", underlying)
        return self._tail(df, ts, "underlying_price", lookback)

    def atm_iv(self, underlying: str, lookback: int, target_dte: int = 30) -> pl.Series:
        df = self._store.atm_iv_series(underlying, target_dte)
        ts = self._store.series_ts("atm_iv", underlying, target_dte)
        return self._tail(df, ts, "atm_iv", lookback)

    def _tail(self, df: pl.DataFrame, ts: list[datetime], column: str, lookback: int) -> pl.Series:
        end = bisect_right(ts, self._now)
        return df[column].slice(max(0, end - lookback), min(end, lookback))
