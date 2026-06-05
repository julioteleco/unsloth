"""Shared utilities: logging, caching helpers, timezone handling, parquet IO."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

US_EASTERN = "America/New_York"

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Return a module logger configured once with a sane default handler."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


log = get_logger("mfrh.utils")


# --------------------------------------------------------------------------- #
# Timezone helpers
# --------------------------------------------------------------------------- #
def normalize_intraday_index(df: pd.DataFrame, tz: str = US_EASTERN) -> pd.DataFrame:
    """Return ``df`` with a tz-aware DatetimeIndex localized to US/Eastern.

    yfinance intraday data is usually already tz-aware. We coerce to US/Eastern
    so that "session minute" logic lines up with the US cash session. Naive
    indices are assumed to already be in US/Eastern.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, utc=True)
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC").tz_convert(tz)
    else:
        out.index = out.index.tz_convert(tz)
    return out


def session_date(index: pd.DatetimeIndex) -> pd.Series:
    """Return the calendar (session) date for each timestamp."""
    return pd.Series(index.date, index=index, name="session_date")


def session_minute(index: pd.DatetimeIndex) -> pd.Series:
    """Minutes elapsed since 09:30 US/Eastern for each timestamp.

    Values are clipped at 0 for pre-market bars. This is the key used to compare
    a bar's volume against the same point in prior sessions.
    """
    minutes = index.hour * 60 + index.minute - (9 * 60 + 30)
    return pd.Series(np.maximum(minutes, 0), index=index, name="session_minute")


# --------------------------------------------------------------------------- #
# Caching
# --------------------------------------------------------------------------- #
def is_cache_fresh(path: Path, ttl_minutes: int) -> bool:
    """True if ``path`` exists and is younger than ``ttl_minutes``."""
    if ttl_minutes <= 0 or not path.exists():
        return False
    age_min = (time.time() - path.stat().st_mtime) / 60.0
    return age_min < ttl_minutes


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Persist a DataFrame to parquet, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def read_parquet(path: Path) -> Optional[pd.DataFrame]:
    """Read a parquet file, returning ``None`` if missing/unreadable."""
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as exc:  # pragma: no cover - corruption is rare
        log.warning("Failed reading parquet %s: %s", path, exc)
        return None


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# --------------------------------------------------------------------------- #
# Numeric helpers
# --------------------------------------------------------------------------- #
def safe_div(numerator: float, denominator: float, default: float = np.nan) -> float:
    """Divide guarding against zero / NaN denominators."""
    try:
        if denominator is None or denominator == 0 or pd.isna(denominator):
            return default
        return numerator / denominator
    except Exception:
        return default


def clip_score(value: float) -> float:
    """Clamp a score into the inclusive 0-100 range; NaN -> 50 (neutral)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return 50.0
    return float(min(100.0, max(0.0, value)))


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """Rolling z-score with a minimum-periods guard."""
    mean = series.rolling(window, min_periods=max(2, window // 2)).mean()
    std = series.rolling(window, min_periods=max(2, window // 2)).std()
    return (series - mean) / std.replace(0, np.nan)
