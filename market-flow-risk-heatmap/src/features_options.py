"""Lite options features from a yfinance snapshot.

These are coarse, free-data approximations. We do NOT use OPRA, real Greeks, or a
live order book. The "gamma wall" is a naive proxy: the strike with the largest
total open interest, where dealer hedging *may* cluster. Treat as context only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import get_logger, safe_div

log = get_logger("mfrh.options")


def compute_options_features(snapshot: dict, spot: float | None = None) -> dict:
    """Compute lite options features from a ``download_options_snapshot`` dict.

    Returns a dict that always includes ``available`` (bool). When unavailable,
    callers should show "options data unavailable" and skip option-based scoring.
    """
    base = {
        "available": False,
        "ticker": snapshot.get("ticker") if snapshot else None,
        "put_call_volume_ratio": np.nan,
        "put_call_oi_ratio": np.nan,
        "max_call_oi_strike": np.nan,
        "max_put_oi_strike": np.nan,
        "max_total_oi_strike": np.nan,
        "distance_to_max_oi_strike": np.nan,
        "approximate_gamma_wall": np.nan,
        "note": "Free yfinance snapshot; coarse proxy, not OPRA / real Greeks.",
    }
    if not snapshot or not snapshot.get("available"):
        if snapshot and snapshot.get("error"):
            base["note"] = f"options data unavailable: {snapshot['error']}"
        return base

    calls = snapshot.get("calls", pd.DataFrame())
    puts = snapshot.get("puts", pd.DataFrame())
    if calls.empty and puts.empty:
        return base

    def _sum(df: pd.DataFrame, col: str) -> float:
        if df.empty or col not in df.columns:
            return 0.0
        return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())

    call_vol = _sum(calls, "volume")
    put_vol = _sum(puts, "volume")
    call_oi = _sum(calls, "openInterest")
    put_oi = _sum(puts, "openInterest")

    base["put_call_volume_ratio"] = safe_div(put_vol, call_vol)
    base["put_call_oi_ratio"] = safe_div(put_oi, call_oi)

    def _max_oi_strike(df: pd.DataFrame) -> float:
        if df.empty or "openInterest" not in df.columns or "strike" not in df.columns:
            return np.nan
        oi = pd.to_numeric(df["openInterest"], errors="coerce").fillna(0)
        if oi.sum() <= 0:
            return np.nan
        return float(df.loc[oi.idxmax(), "strike"])

    base["max_call_oi_strike"] = _max_oi_strike(calls)
    base["max_put_oi_strike"] = _max_oi_strike(puts)

    # Combined OI by strike -> largest cluster is the proxy "gamma wall".
    combined = []
    for df in (calls, puts):
        if not df.empty and {"strike", "openInterest"}.issubset(df.columns):
            tmp = df[["strike", "openInterest"]].copy()
            tmp["openInterest"] = pd.to_numeric(tmp["openInterest"], errors="coerce").fillna(0)
            combined.append(tmp)
    if combined:
        all_oi = pd.concat(combined, ignore_index=True)
        by_strike = all_oi.groupby("strike")["openInterest"].sum()
        if by_strike.sum() > 0:
            wall = float(by_strike.idxmax())
            base["max_total_oi_strike"] = wall
            base["approximate_gamma_wall"] = wall
            if spot is not None and np.isfinite(spot):
                base["distance_to_max_oi_strike"] = float(spot - wall)

    base["available"] = True
    return base
