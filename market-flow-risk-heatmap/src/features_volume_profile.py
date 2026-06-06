"""Approximate volume profile from OHLCV bars (no tick data available).

Each bar's volume is spread *uniformly* across price bins between its high and
low (a standard free approximation). From the resulting price->volume histogram
we derive POC, Value Area High/Low (70% by default), and approximate HVN/LVN
levels. ``assign_profile_features`` then maps the latest price relative to those
levels for use in scoring.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import load_config


@dataclass
class VolumeProfile:
    bin_edges: np.ndarray  # length bins+1
    bin_centers: np.ndarray  # length bins
    bin_volume: np.ndarray  # length bins
    poc: float
    vah: float
    val: float
    hvn: list[float] = field(default_factory=list)
    lvn: list[float] = field(default_factory=list)
    value_area_pct: float = 0.70

    def as_dict(self) -> dict:
        return {
            "poc": self.poc,
            "vah": self.vah,
            "val": self.val,
            "hvn": self.hvn,
            "lvn": self.lvn,
            "value_area_pct": self.value_area_pct,
        }


def calculate_volume_profile(
    df: pd.DataFrame,
    bins: int | None = None,
    value_area_pct: float | None = None,
) -> VolumeProfile:
    """Build an approximate volume profile from OHLCV bars.

    Volume from each bar is distributed uniformly across the price bins that the
    bar's [low, high] range overlaps. If ``high == low`` the whole volume goes to
    the bin containing ``close``.
    """
    cfg = load_config()
    bins = bins or cfg.features.volume_profile.bins
    value_area_pct = value_area_pct or cfg.features.volume_profile.value_area_pct

    if df is None or df.empty:
        edges = np.linspace(0, 1, bins + 1)
        centers = (edges[:-1] + edges[1:]) / 2
        return VolumeProfile(edges, centers, np.zeros(bins), np.nan, np.nan, np.nan,
                             value_area_pct=value_area_pct)

    lo = float(df["low"].min())
    hi = float(df["high"].max())
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        hi = lo + max(abs(lo) * 1e-4, 1e-6)

    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    bin_volume = np.zeros(bins)
    bin_width = (hi - lo) / bins

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    vols = np.nan_to_num(df["volume"].to_numpy(dtype=float), nan=0.0)

    for h, l, c, v in zip(highs, lows, closes, vols):
        if v <= 0:
            continue
        if h <= l:  # degenerate bar -> assign to close's bin
            idx = int(np.clip((c - lo) / bin_width, 0, bins - 1))
            bin_volume[idx] += v
            continue
        # Distribute v uniformly over [l, h] across overlapping bins.
        lo_idx = int(np.clip((l - lo) / bin_width, 0, bins - 1))
        hi_idx = int(np.clip((h - lo) / bin_width, 0, bins - 1))
        if lo_idx == hi_idx:
            bin_volume[lo_idx] += v
            continue
        span = h - l
        for b in range(lo_idx, hi_idx + 1):
            b_low = edges[b]
            b_high = edges[b + 1]
            overlap = min(h, b_high) - max(l, b_low)
            if overlap > 0:
                bin_volume[b] += v * (overlap / span)

    poc_idx = int(np.argmax(bin_volume))
    poc = float(centers[poc_idx])

    vah, val = _value_area(centers, bin_volume, poc_idx, value_area_pct)
    hvn, lvn = _hvn_lvn(centers, bin_volume)

    return VolumeProfile(
        bin_edges=edges,
        bin_centers=centers,
        bin_volume=bin_volume,
        poc=poc,
        vah=vah,
        val=val,
        hvn=hvn,
        lvn=lvn,
        value_area_pct=value_area_pct,
    )


def _value_area(
    centers: np.ndarray, vol: np.ndarray, poc_idx: int, pct: float
) -> tuple[float, float]:
    """Grow outward from the POC until ``pct`` of total volume is captured."""
    total = vol.sum()
    if total <= 0:
        return float(centers[poc_idx]), float(centers[poc_idx])
    target = total * pct
    included = {poc_idx}
    captured = vol[poc_idx]
    lo_i = hi_i = poc_idx
    n = len(vol)
    while captured < target and (lo_i > 0 or hi_i < n - 1):
        below = vol[lo_i - 1] if lo_i > 0 else -1.0
        above = vol[hi_i + 1] if hi_i < n - 1 else -1.0
        if above >= below:
            hi_i += 1
            captured += max(above, 0.0)
            included.add(hi_i)
        else:
            lo_i -= 1
            captured += max(below, 0.0)
            included.add(lo_i)
    vah = float(centers[max(included)])
    val = float(centers[min(included)])
    return vah, val


def _hvn_lvn(centers: np.ndarray, vol: np.ndarray) -> tuple[list[float], list[float]]:
    """Approximate high/low volume nodes via local extrema + thresholds."""
    cfg = load_config().features.volume_profile
    if vol.max() <= 0:
        return [], []
    norm = vol / vol.max()
    hvn_thr = cfg.hvn_quantile
    lvn_thr = cfg.lvn_quantile
    hvn, lvn = [], []
    for i in range(1, len(vol) - 1):
        is_local_max = norm[i] >= norm[i - 1] and norm[i] >= norm[i + 1]
        is_local_min = norm[i] <= norm[i - 1] and norm[i] <= norm[i + 1]
        if is_local_max and norm[i] >= hvn_thr:
            hvn.append(float(centers[i]))
        if is_local_min and norm[i] <= lvn_thr:
            lvn.append(float(centers[i]))
    return hvn, lvn


def _nearest(levels: list[float], price: float) -> float:
    if not levels:
        return np.nan
    return float(min(levels, key=lambda x: abs(x - price)))


def assign_profile_features(
    df: pd.DataFrame, profile: VolumeProfile, near_atr_mult: float = 0.5
) -> pd.DataFrame:
    """Annotate each row with its location relative to the volume profile.

    Adds:
        distance_to_poc, distance_to_vah, distance_to_val,
        near_hvn, near_lvn, inside_value_area.

    "Near" is defined as within ``near_atr_mult`` * ATR (falling back to a small
    fraction of price when ATR is unavailable).
    """
    out = df.copy()
    price = out["close"]
    out["distance_to_poc"] = price - profile.poc
    out["distance_to_vah"] = price - profile.vah
    out["distance_to_val"] = price - profile.val

    if "atr" in out.columns:
        tol = out["atr"].fillna(price * 0.001) * near_atr_mult
    else:
        tol = price * 0.001

    nearest_hvn = price.apply(lambda p: _nearest(profile.hvn, p))
    nearest_lvn = price.apply(lambda p: _nearest(profile.lvn, p))
    out["near_hvn"] = (nearest_hvn - price).abs() <= tol
    out["near_lvn"] = (nearest_lvn - price).abs() <= tol
    out["near_hvn"] = out["near_hvn"].fillna(False)
    out["near_lvn"] = out["near_lvn"].fillna(False)

    lo = min(profile.val, profile.vah)
    hi = max(profile.val, profile.vah)
    out["inside_value_area"] = (price >= lo) & (price <= hi)
    return out
