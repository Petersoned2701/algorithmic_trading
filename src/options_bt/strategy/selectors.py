import logging
from collections.abc import Sequence
from datetime import date, datetime

import polars as pl

from options_bt.data.chain import ContractKey
from options_bt.data.schema import NEW_YORK
from options_bt.engine.position import Leg
from options_bt.errors import NoContractFound
from options_bt.strategy.config import LegSpec

log = logging.getLogger(__name__)


def select_legs(chain: pl.DataFrame, specs: Sequence[LegSpec], ts: datetime) -> list[Leg]:
    today = ts.astimezone(NEW_YORK).date()
    legs: list[Leg] = []
    for index, spec in enumerate(specs):
        try:
            legs.append(_select_leg(chain, spec, legs, today))
        except NoContractFound as exc:
            raise NoContractFound(f"leg {index} ({_describe(spec)}): {exc}") from None
    return legs


def _select_leg(chain: pl.DataFrame, spec: LegSpec, chosen: list[Leg], today: date) -> Leg:
    ref = chosen[spec.ref] if spec.ref is not None else None
    if spec.dte is not None:
        expiration = _pick_expiration(chain, spec.dte, today)
    else:
        expiration = ref.key.expiration
    rows = chain.filter((pl.col("expiration") == expiration) & (pl.col("right") == spec.right))
    if rows.is_empty():
        raise NoContractFound(f"no {spec.right} quotes at expiration {expiration}")
    if ref is None:
        row = _pick_by_delta(rows, spec.delta, spec.right)
    else:
        row = _pick_by_offset(rows, ref.key.strike, spec.strike_offset)
    qty = spec.ratio if spec.side == "long" else -spec.ratio
    return Leg(
        key=ContractKey(row["underlying"], expiration, row["strike"], spec.right),
        qty=qty,
        style=row["style"],
        settlement=row["settlement"],
        multiplier=row["multiplier"],
    )


def _pick_expiration(chain: pl.DataFrame, dte: tuple[int, int], today: date) -> date:
    low, high = dte
    midpoint = (low + high) / 2
    candidates = [
        (abs((exp - today).days - midpoint), exp)
        for exp in chain["expiration"].unique().to_list()
        if low <= (exp - today).days <= high
    ]
    if not candidates:
        raise NoContractFound(f"no expiration with {low} <= DTE <= {high}")
    return min(candidates)[1]


def _pick_by_delta(rows: pl.DataFrame, target: float, right: str) -> dict:
    strikes = rows.sort("strike", descending=right == "C")
    deltas = strikes.select(err=(pl.col("delta").abs() - target).abs().round(9))["err"]
    # Descending for calls puts the higher (further OTM) strike first, so
    # arg_min's first-wins tie-break is always the more conservative strike.
    return strikes.row(deltas.arg_min(), named=True)


def _pick_by_offset(rows: pl.DataFrame, ref_strike: float, offset: float) -> dict:
    target = ref_strike + offset
    tolerance = max(0.01, 0.25 * abs(offset))
    candidates = rows.filter(pl.col("strike") != ref_strike).with_columns(
        dist=(pl.col("strike") - target).abs()
    )
    if candidates.is_empty():
        raise NoContractFound(f"no strike other than the reference strike {ref_strike}")
    best = candidates.sort("dist", "strike").row(0, named=True)
    if best["dist"] > tolerance:
        raise NoContractFound(
            f"nearest strike {best['strike']} is outside tolerance {tolerance:g} "
            f"of target {target:g}"
        )
    return best


def _describe(spec: LegSpec) -> str:
    if spec.ref is not None:
        rule = f"ref {spec.ref} offset {spec.strike_offset:g}"
        return rule if spec.dte is None else f"{rule}, dte {spec.dte[0]}-{spec.dte[1]}"
    return f"dte {spec.dte[0]}-{spec.dte[1]}, delta {spec.delta:g}"
