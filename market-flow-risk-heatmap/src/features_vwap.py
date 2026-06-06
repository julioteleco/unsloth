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


def true_range(df: pd.DataFrame) -> pd.Series:
    """True Range = max(high-low, |high-prev_close|, |low-prev_close|)."""
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def calculate_atr(df: pd.DataFrame, window: int = 14, method: str | None = None) -> pd.DataFrame:
    """Add ATR and ATR percent to the frame.

    ``method='wilder'`` uses Wilder's RMA smoothing (the canonical ATR, an EWMA
    with ``alpha = 1/window``), which is what most charting/quant stacks report.
    ``method='sma'`` uses a simple rolling mean. ``atr_pct`` is ATR / close.
    """
    cfg = load_config().features.atr
    method = (method or cfg.method).lower()
    out = df.copy()
    tr = true_range(out)
    min_p = max(2, window // 2)
    if method == "sma":
        out["atr"] = tr.rolling(window, min_periods=min_p).mean()
    else:  # wilder (RMA)
        out["atr"] = tr.ewm(alpha=1.0 / window, min_periods=min_p, adjust=False).mean()
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
            "vwap_std",
            "distance_to_vwap",
            "distance_to_vwap_pct",
            "distance_to_vwap_atr",
            "distance_to_vwap_band",
            "atr",
            "atr_pct",
        ]:
            out[c] = np.nan
        return out

    out["session_date"] = session_date(out.index).values
    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    vol = out["volume"].fillna(0)
    out["_tp_vol"] = typical * vol
    out["_tp2_vol"] = (typical ** 2) * vol
    grp = out.groupby("session_date", sort=False)
    cum_tpvol = grp["_tp_vol"].cumsum()
    cum_tp2vol = grp["_tp2_vol"].cumsum()
    cum_vol = grp["volume"].transform(lambda s: s.fillna(0).cumsum())
    out["vwap"] = cum_tpvol / cum_vol.replace(0, np.nan)
    # First bar of a session with zero volume falls back to typical price.
    out["vwap"] = out["vwap"].fillna(typical)

    # Volume-weighted standard deviation around the session VWAP:
    #   var = E[tp^2] - E[tp]^2  (both volume-weighted, cumulative within session)
    mean_tp2 = cum_tp2vol / cum_vol.replace(0, np.nan)
    vw_var = (mean_tp2 - out["vwap"] ** 2).clip(lower=0)
    out["vwap_std"] = np.sqrt(vw_var)
    out = out.drop(columns=["_tp_vol", "_tp2_vol"])

    for sigma in cfg.features.vwap.band_sigmas:
        tag = str(sigma).rstrip("0").rstrip(".") if "." in str(sigma) else str(sigma)
        out[f"vwap_upper_{tag}"] = out["vwap"] + sigma * out["vwap_std"]
        out[f"vwap_lower_{tag}"] = out["vwap"] - sigma * out["vwap_std"]

    out = calculate_atr(out, window=atr_window)

    out["distance_to_vwap"] = out["close"] - out["vwap"]
    out["distance_to_vwap_pct"] = out["distance_to_vwap"] / out["vwap"].replace(0, np.nan)
    out["distance_to_vwap_atr"] = out["distance_to_vwap"] / out["atr"].replace(0, np.nan)
    # Distance expressed in volume-weighted-σ band units (mean-reversion signal).
    out["distance_to_vwap_band"] = out["distance_to_vwap"] / out["vwap_std"].replace(0, np.nan)
    return out
