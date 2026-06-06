"""Calendar / seasonality features — derived locally, NO external data needed.

Intraday US-equity behaviour has well-documented calendar structure: monthly
options expiration (OPEX, third Friday), quarterly quad-witching, month-end
rebalancing, day-of-week effects, and the closing-auction window. These are all
computable from the timestamp alone, so they are 100% free and always available.

Event days (FOMC/CPI/NFP) are optional and read from config — empty by default so
we never assert a stale or guessed date.
"""
from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd

from .config import load_config
from .utils import US_EASTERN, normalize_intraday_index


def third_friday(year: int, month: int) -> _dt.date:
    """Return the third Friday of a month (monthly equity options expiration)."""
    d = _dt.date(year, month, 1)
    # weekday(): Mon=0 ... Fri=4
    first_friday = d + _dt.timedelta(days=(4 - d.weekday()) % 7)
    return first_friday + _dt.timedelta(days=14)


def is_opex(day: _dt.date) -> bool:
    """True if ``day`` is the monthly options-expiration Friday."""
    return day == third_friday(day.year, day.month)


def is_quad_witching(day: _dt.date) -> bool:
    """True on quarterly quad-witching (third Friday of Mar/Jun/Sep/Dec)."""
    return day.month in (3, 6, 9, 12) and is_opex(day)


def _is_month_end_week(day: _dt.date) -> bool:
    """True if ``day`` falls in the last 3 business days of the month."""
    last = _dt.date(day.year, day.month, 28)
    # advance to actual last day of month
    one = _dt.timedelta(days=1)
    nxt = last + one
    while nxt.month == day.month:
        last = nxt
        nxt = last + one
    # count business days remaining (inclusive)
    bdays = pd.bdate_range(day, last)
    return len(bdays) <= 3


def _parse_dates(values: list[str]) -> set[_dt.date]:
    out: set[_dt.date] = set()
    for v in values:
        try:
            out.add(pd.Timestamp(v).date())
        except Exception:
            continue
    return out


def compute_seasonality_features(index: pd.DatetimeIndex | None = None,
                                 now: pd.Timestamp | None = None) -> dict:
    """Compute calendar features for the latest bar (or ``now``).

    Returns a flat dict of booleans/ints describing the current calendar context.
    Pass either an ``index`` (uses its last timestamp) or an explicit ``now``.
    """
    cfg = load_config().features.seasonality
    if now is None:
        if index is not None and len(index) > 0:
            ts = pd.Timestamp(index[-1])
        else:
            ts = pd.Timestamp.now(tz=US_EASTERN)
    else:
        ts = pd.Timestamp(now)
    if ts.tzinfo is None:
        ts = ts.tz_localize(US_EASTERN)
    else:
        ts = ts.tz_convert(US_EASTERN)

    day = ts.date()
    minutes_since_open = max(int(ts.hour * 60 + ts.minute - (9 * 60 + 30)), 0)
    minutes_to_close = int((16 * 60) - (ts.hour * 60 + ts.minute))

    fomc = _parse_dates(cfg.fomc_dates)
    cpi = _parse_dates(cfg.cpi_dates)

    return {
        "day_of_week": int(ts.weekday()),  # Mon=0
        "is_monday": ts.weekday() == 0,
        "is_friday": ts.weekday() == 4,
        "is_opex": is_opex(day),
        "is_quad_witching": is_quad_witching(day),
        "is_month_end_week": _is_month_end_week(day),
        "is_first_trading_minutes": minutes_since_open <= 30,
        "is_closing_window": 0 <= minutes_to_close <= cfg.closing_window_min,
        "minutes_since_open": minutes_since_open,
        "minutes_to_close": minutes_to_close,
        "is_fomc_day": day in fomc,
        "is_cpi_day": day in cpi,
        "is_event_day": (day in fomc) or (day in cpi),
    }


def add_seasonality_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Annotate every bar of an intraday frame with per-bar calendar features.

    Vectorised; safe on empty frames. Index is normalised to US/Eastern.
    """
    out = df.copy()
    if "datetime" in out.columns and not isinstance(out.index, pd.DatetimeIndex):
        out["datetime"] = pd.to_datetime(out["datetime"], utc=True, errors="coerce")
        out = out.set_index("datetime")
    out = normalize_intraday_index(out)
    if out.empty:
        for c in ["day_of_week", "is_opex", "is_quad_witching", "is_month_end_week",
                  "is_closing_window", "minutes_since_open", "minutes_to_close"]:
            out[c] = np.nan
        return out

    idx = out.index
    days = pd.Series(idx.date, index=idx)
    out["day_of_week"] = idx.weekday
    out["minutes_since_open"] = np.maximum(idx.hour * 60 + idx.minute - (9 * 60 + 30), 0)
    out["minutes_to_close"] = (16 * 60) - (idx.hour * 60 + idx.minute)
    cfg = load_config().features.seasonality
    out["is_closing_window"] = (out["minutes_to_close"] >= 0) & (
        out["minutes_to_close"] <= cfg.closing_window_min
    )
    out["is_opex"] = days.map(is_opex).to_numpy()
    out["is_quad_witching"] = days.map(is_quad_witching).to_numpy()
    out["is_month_end_week"] = days.map(_is_month_end_week).to_numpy()
    return out
