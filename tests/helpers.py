import copy
from datetime import date, timedelta

import polars as pl

from options_bt.data.chain import ContractKey
from options_bt.data.schema import snapshot_ts
from options_bt.data.store import QuoteStore
from options_bt.engine.position import Leg

E1 = date(2024, 2, 16)
E2 = date(2024, 3, 15)

D0 = date(2024, 1, 2)
T0 = snapshot_ts(D0)
T1 = snapshot_ts(date(2024, 1, 3))
EXPIRY_TS = snapshot_ts(E1)

PCS = {
    "name": "pcs_spy_45dte",
    "underlyings": ["SPY"],
    "entry": {
        "schedule": {"weekdays": ["MON", "THU"]},
        "filters": [
            {"type": "vix_term_structure", "max_ratio": 1.0},
            {"type": "iv_rank", "min": 20, "lookback_days": 252},
        ],
        "legs": [
            {"right": "put", "side": "short", "dte": [30, 45], "delta": 0.25},
            {"right": "put", "side": "long", "ref": 0, "strike_offset": -5},
        ],
    },
    "exits": {"profit_target_pct": 50, "stop_loss_multiple": 2.0, "dte_exit": 21},
    "sizing": {"max_loss_pct_equity": 2.0},
    "portfolio_caps": {"max_total_max_loss_pct": 15},
    "costs": {
        "commission_per_contract": 0.65,
        "fill_fraction": {1: 0.75, 2: 0.66, 3: 0.56, 4: 0.53},
    },
}

PCS_NO_FILTERS = copy.deepcopy(PCS)
PCS_NO_FILTERS["entry"]["filters"] = []


def L(
    qty: int,
    right: str,
    strike: float,
    exp: date = E1,
    *,
    price: float = 0.0,
    underlying: str = "SPY",
    style: str = "american",
    settlement: str = "physical",
) -> Leg:
    return Leg(
        key=ContractKey(underlying, exp, float(strike), right),
        qty=qty,
        style=style,
        settlement=settlement,
        entry_price=price,
    )


EMPTY_TRADES = pl.DataFrame(
    {"closed_ts": [], "pnl": [], "commissions": []},
    schema={
        "closed_ts": pl.Datetime("us", "UTC"),
        "pnl": pl.Float64,
        "commissions": pl.Float64,
    },
)


def daily_pcs(**overrides) -> dict:
    """PCS without filters: enters every day, one position at a time, 100k cash."""
    raw = copy.deepcopy(PCS_NO_FILTERS)
    raw["entry"]["schedule"] = {}
    raw["entry"]["max_open_positions"] = 1
    raw["account"] = {"initial_cash": 100_000}
    return {**raw, **overrides}


def weekdays(start: date, n: int) -> list[date]:
    """The first `n` Mon-Fri dates on or after `start`."""
    days: list[date] = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def first_chain(root, underlying: str = "SPY") -> pl.DataFrame:
    store = QuoteStore(root)
    return store.chain(underlying, store.timestamps([underlying])[0])


def eq(values, start: date = date(2024, 1, 2), tbill: float | None = None) -> pl.DataFrame:
    """Equity frame on consecutive Mon-Fri dates from `start` (ts, equity, tbill only)."""
    days = weekdays(start, len(values))
    return pl.DataFrame(
        {
            "ts": [snapshot_ts(x) for x in days],
            "equity": pl.Series(list(values), dtype=pl.Float64),
            "tbill": pl.Series([tbill] * len(days), dtype=pl.Float64),
        }
    )
