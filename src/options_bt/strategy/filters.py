import inspect
import logging
from collections.abc import Callable
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from options_bt.data.schema import ny_date
from options_bt.errors import ConfigError
from options_bt.loaders import read_dated_csv
from options_bt.strategy.base import StepContext

log = logging.getLogger(__name__)

FILTERS: dict[str, Callable[..., bool]] = {}


def register(name: str) -> Callable[[Callable[..., bool]], Callable[..., bool]]:
    def decorator(fn: Callable[..., bool]) -> Callable[..., bool]:
        FILTERS[name] = fn
        return fn

    return decorator


def check(filter_cfg: dict, ctx: StepContext, underlying: str) -> bool:
    params = {k: v for k, v in filter_cfg.items() if k != "type"}
    return FILTERS[filter_cfg["type"]](ctx, underlying, **params)


def validate_filters(filter_cfgs: list[dict]) -> None:
    for cfg in filter_cfgs:
        name = cfg.get("type")
        if name not in FILTERS:
            raise ConfigError(f"unknown filter type '{name}'; known: {', '.join(sorted(FILTERS))}")
        accepted = list(inspect.signature(FILTERS[name]).parameters)[2:]
        bad = sorted(set(cfg) - {"type"} - set(accepted))
        if bad:
            raise ConfigError(
                f"filter '{name}': unknown parameter(s) {', '.join(bad)}; "
                f"accepted: {', '.join(accepted) or 'none'}"
            )


@register("vix_term_structure")
def vix_term_structure(ctx: StepContext, underlying: str, max_ratio: float = 1.0) -> bool:
    vix = ctx.market.asof("vix", ctx.ts)
    vix3m = ctx.market.asof("vix3m", ctx.ts)
    if vix is None or vix3m is None:
        log.debug("vix_term_structure: missing vix/vix3m at %s", ctx.ts)
        return False
    return vix / vix3m < max_ratio


@register("iv_rank")
def iv_rank(
    ctx: StepContext,
    underlying: str,
    min: float = 0,
    max: float = 100,
    lookback_days: int = 252,
) -> bool:
    iv = ctx.history.atm_iv(underlying, lookback_days).drop_nulls()
    if len(iv) < lookback_days // 2:
        log.debug(
            "iv_rank: only %d of %d needed values for %s", len(iv), lookback_days // 2, underlying
        )
        return False
    low, high = iv.min(), iv.max()
    if high == low:
        log.debug("iv_rank: flat IV history for %s", underlying)
        return False
    rank = (iv[-1] - low) / (high - low) * 100
    return min <= rank <= max


@lru_cache
def _event_dates(path: Path) -> tuple[date, ...]:
    return tuple(read_dated_csv(path, "events file")["date"])


@register("event_blackout")
def event_blackout(
    ctx: StepContext,
    underlying: str,
    file: str = "configs/events.csv",
    days_before: int = 1,
    days_after: int = 0,
) -> bool:
    today = ny_date(ctx.ts)
    for d in _event_dates(Path(file).resolve()):
        if d - timedelta(days=days_before) <= today <= d + timedelta(days=days_after):
            log.debug("event_blackout: %s within window of event on %s", today, d)
            return False
    return True
