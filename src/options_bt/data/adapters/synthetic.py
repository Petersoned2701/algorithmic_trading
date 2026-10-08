import math
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from scipy.special import ndtr

from options_bt.data.schema import QUOTE_SCHEMA, snapshot_ts
from options_bt.data.store import ImportSummary, write_quotes
from options_bt.errors import DataError
from options_bt.loaders import read_table


def _bs(spot, strike, t_years, rate: float, vol: float, right: str):
    """Price and delta; numpy-vectorised over `strike`/`t_years`, intrinsic where t <= 0."""
    spot, strike, t = np.broadcast_arrays(*map(np.asarray, (spot, strike, t_years)))
    live = t > 0
    t_live = np.where(live, t, 1.0)
    sd = vol * np.sqrt(t_live)
    d1 = (np.log(spot / strike) + (rate + 0.5 * vol * vol) * t_live) / sd
    d2 = d1 - sd
    disc = np.exp(-rate * t)
    if right == "C":
        price = np.where(live, spot * ndtr(d1) - strike * disc * ndtr(d2), spot - strike)
        delta = np.where(live, ndtr(d1), (spot > strike) * 1.0)
    else:
        price = np.where(live, strike * disc * ndtr(-d2) - spot * ndtr(-d1), strike - spot)
        delta = np.where(live, ndtr(d1) - 1.0, -1.0 * (spot < strike))
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
    constants = {
        "underlying": underlying,
        "style": style,
        "settlement": settlement,
        "iv": vol,
        "multiplier": 100,
    }

    blocks = []
    for d, close in closes:
        dte = np.array([(exp - d).days for exp in expirations])
        live = (dte >= 0) & (dte <= max_dte)
        k_lo = math.ceil(round(strike_range[0] * close / strike_step, 9))
        k_hi = math.floor(round(strike_range[1] * close / strike_step, 9))
        strikes = np.arange(k_lo, k_hi + 1) * strike_step
        if not live.any() or not len(strikes):
            continue
        t_years = dte[live][:, None] / 365
        # Axes: expiration, right (C then P), strike.
        price, delta = (
            np.stack(pair, axis=1)
            for pair in zip(
                *(_bs(close, strikes, t_years, rate, vol, r) for r in "CP"), strict=True
            )
        )
        n_exp, n_strike = len(t_years), len(strikes)
        blocks.append(
            pl.DataFrame(
                {
                    "expiration": np.repeat(
                        np.array(expirations, dtype="datetime64[D]")[live], 2 * n_strike
                    ),
                    "strike": np.tile(strikes, 2 * n_exp),
                    "right": np.tile(np.repeat(["C", "P"], n_strike), n_exp),
                    "bid": np.maximum(0.0, price - spread / 2).ravel(),
                    "ask": (price + spread / 2).ravel(),
                    "delta": delta.ravel(),
                }
            ).with_columns(
                ts=pl.lit(snapshot_ts(d)),
                underlying_price=pl.lit(close),
                **{name: pl.lit(value) for name, value in constants.items()},
            )
        )
    if not blocks:
        return pl.DataFrame(schema=QUOTE_SCHEMA)
    return pl.concat(blocks).select(list(QUOTE_SCHEMA)).cast(QUOTE_SCHEMA)


def convert(raw_path: Path, data_root: Path, replace: bool = False, **kwargs) -> ImportSummary:
    """Read a `date,underlying,close` CSV, generate chains per underlying and write them."""
    raw = read_table(raw_path, "price path", try_parse_dates=True)
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
