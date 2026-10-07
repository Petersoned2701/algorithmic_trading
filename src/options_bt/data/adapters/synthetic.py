import logging
import math
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from scipy.stats import norm

from options_bt.data.schema import QUOTE_SCHEMA, snapshot_ts
from options_bt.data.store import ImportSummary, write_quotes
from options_bt.errors import DataError

log = logging.getLogger(__name__)


def _bs(spot, strike, t_years, rate: float, vol: float, right: str):
    """Price and delta; numpy-vectorised over `strike`/`t_years`, intrinsic where t <= 0."""
    spot, strike, t = np.broadcast_arrays(*map(np.asarray, (spot, strike, t_years)))
    live = t > 0
    sd = vol * np.sqrt(np.where(live, t, 1.0))
    d1 = (np.log(spot / strike) + (rate + 0.5 * vol * vol) * np.where(live, t, 1.0)) / sd
    d2 = d1 - sd
    disc = np.exp(-rate * t)
    if right == "C":
        price = np.where(live, spot * norm.cdf(d1) - strike * disc * norm.cdf(d2), spot - strike)
        delta = np.where(live, norm.cdf(d1), (spot > strike) * 1.0)
    else:
        price = np.where(live, strike * disc * norm.cdf(-d2) - spot * norm.cdf(-d1), strike - spot)
        delta = np.where(live, norm.cdf(d1) - 1.0, -1.0 * (spot < strike))
    return np.where(live, price, np.maximum(price, 0.0)), delta


def bs_price(
    spot: float, strike: float, t_years: float, rate: float, vol: float, right: str
) -> float:
    return float(_bs(spot, strike, t_years, rate, vol, right)[0])


def bs_delta(
    spot: float, strike: float, t_years: float, rate: float, vol: float, right: str
) -> float:
    return float(_bs(spot, strike, t_years, rate, vol, right)[1])


def _fridays(first: date, last: date) -> list[date]:
    d = first + timedelta(days=(4 - first.weekday()) % 7)
    out = []
    while d <= last:
        out.append(d)
        d += timedelta(days=7)
    return out


def generate_chains(
    underlying: str,
    closes: Sequence[tuple[date, float]],
    *,
    vol: float = 0.20,
    rate: float = 0.0,
    strike_step: float = 1.0,
    strike_range: tuple[float, float] = (0.8, 1.2),
    max_dte: int = 70,
    spread: float = 0.10,
    style: str = "american",
    settlement: str = "physical",
) -> pl.DataFrame:
    """Black-Scholes quotes for weekly Friday expirations, one snapshot per (date, close)."""
    if not closes:
        return pl.DataFrame(schema=QUOTE_SCHEMA)
    dates = [d for d, _ in closes]
    expirations = _fridays(min(dates), max(dates) + timedelta(days=max_dte))

    cols: dict[str, list] = {name: [] for name in QUOTE_SCHEMA}
    for d, close in closes:
        k_lo = math.ceil(round(strike_range[0] * close / strike_step, 9))
        k_hi = math.floor(round(strike_range[1] * close / strike_step, 9))
        strikes = np.arange(k_lo, k_hi + 1) * strike_step
        for exp in expirations:
            dte = (exp - d).days
            if not 0 <= dte <= max_dte:
                continue
            for right in ("C", "P"):
                theo, delta = _bs(close, strikes, dte / 365, rate, vol, right)
                n = len(strikes)
                block = {
                    "ts": [snapshot_ts(d)] * n,
                    "underlying": [underlying] * n,
                    "underlying_price": [close] * n,
                    "expiration": [exp] * n,
                    "strike": strikes,
                    "right": [right] * n,
                    "style": [style] * n,
                    "settlement": [settlement] * n,
                    "bid": np.maximum(0.0, theo - spread / 2),
                    "ask": theo + spread / 2,
                    "delta": delta,
                    "iv": [vol] * n,
                    "multiplier": [100] * n,
                }
                for name, values in block.items():
                    cols[name].extend(values)
    return pl.DataFrame(cols, schema=QUOTE_SCHEMA)


def convert(raw_path: Path, data_root: Path, replace: bool = False, **kwargs) -> ImportSummary:
    """Read a `date,underlying,close` CSV, generate chains per underlying and write them."""
    try:
        raw = pl.read_csv(raw_path, try_parse_dates=True)
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise DataError(f"cannot read {raw_path}: {exc}") from exc
    missing = [c for c in ("date", "underlying", "close") if c not in raw.columns]
    if missing:
        raise DataError(f"{raw_path} is missing columns: {', '.join(missing)}")
    if raw.schema["date"] != pl.Date:
        raise DataError(f"{raw_path}: column 'date' must hold ISO dates (YYYY-MM-DD)")
    if raw.is_empty():
        raise DataError(f"{raw_path} has no rows")

    frames = []
    for (underlying,), group in raw.sort("date").group_by(["underlying"], maintain_order=True):
        closes = list(zip(group["date"], group["close"].cast(pl.Float64), strict=True))
        frames.append(generate_chains(str(underlying), closes, **kwargs))
    return write_quotes(pl.concat(frames), data_root, replace=replace)
