from datetime import date, datetime, time

from options_bt.data.schema import NEW_YORK


def intrinsic(right: str, strike: float, spot: float) -> float:
    if right == "C":
        return max(spot - strike, 0.0)
    return max(strike - spot, 0.0)


def is_due(expiration: date, ts: datetime, session_close: time) -> bool:
    """True once `ts` (New York time) is past `expiration`, or at/after `session_close` on it."""
    local = ts.astimezone(NEW_YORK)
    if expiration < local.date():
        return True
    return expiration == local.date() and local.time() >= session_close
