"""Session VWAP and intraday ATR features.

VWAP resets every session (calendar day in US/Eastern). Distances to VWAP are
expressed in absolute terms, percent, and ATR multiples so downstream scoring can
reason about "extension" in a volatility-aware way.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import load_config
from .utils import normalize_intraday_index, session_date


def _ensure_indexed(df: pd.DataFrame) -> pd.DataFrame:
    """Return a tz-aware, datetime-indexed copy of a canonical OHLCV frame."""
    out = df.copy()
    if "datetime" in out.columns:
        out["datetime"] = pd.to_datetime(out["datetime"], utc=True, errors="coerce")
        out = out.set_index("datetime")
    out = normalize_intraday_index(out)
    return out.sort_index()


def calculate_atr(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """Add a simple (rolling-mean) ATR and ATR percent to the frame.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|).
    ``atr`` is the rolling mean of TR over ``window`` bars; ``atr_pct`` expresses
    it as a fraction of close.
    """
    out = df.copy()
    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(window, min_periods=max(2, window // 2)).mean()
    out["atr_pct"] = out["atr"] / out["close"].replace(0, np.nan)
    return out


def calculate_session_vwap(df: pd.DataFrame, atr_window: int | None = None) -> pd.DataFrame:
    """Compute session-anchored VWAP plus distance metrics.

    Adds columns:
        vwap, distance_to_vwap, distance_to_vwap_pct, distance_to_vwap_atr,
        atr, atr_pct, session_date, session_minute (best-effort).

    VWAP is reset for each session/day using::

        typical_price = (high + low + close) / 3
        vwap = cumsum(typical_price * volume) / cumsum(volume)
    """
    cfg = load_config()
    atr_window = atr_window or cfg.features.vwap.atr_window

    out = _ensure_indexed(df)
    if out.empty:
        for c in [
            "vwap",
            "distance_to_vwap",
            "distance_to_vwap_pct",
            "distance_to_vwap_atr",
            "atr",
            "atr_pct",
        ]:
            out[c] = np.nan
        return out

    out["session_date"] = session_date(out.index).values
    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    out["_tp_vol"] = typical * out["volume"].fillna(0)
    grp = out.groupby("session_date", sort=False)
    cum_tpvol = grp["_tp_vol"].cumsum()
    cum_vol = grp["volume"].apply(lambda s: s.fillna(0).cumsum()).reset_index(level=0, drop=True)
    out["vwap"] = cum_tpvol / cum_vol.replace(0, np.nan)
    # First bar of a session with zero volume falls back to typical price.
    out["vwap"] = out["vwap"].fillna(typical)
    out = out.drop(columns=["_tp_vol"])

    out = calculate_atr(out, window=atr_window)

    out["distance_to_vwap"] = out["close"] - out["vwap"]
    out["distance_to_vwap_pct"] = out["distance_to_vwap"] / out["vwap"].replace(0, np.nan)
    out["distance_to_vwap_atr"] = out["distance_to_vwap"] / out["atr"].replace(0, np.nan)
    return out
