"""FINRA daily short-sale volume (OPTIONAL, weak proxy).

FINRA publishes a free daily short-sale volume file. IMPORTANT: this is *volume*,
not short *interest*. It only tells you how much of the day's reported volume was
marked short on FINRA facilities. It is a weak, noisy proxy for selling pressure
and must never be presented as short interest or positioning.

All functions degrade gracefully: on any failure they return empty frames.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from .config import cache_ttl_minutes, load_config
from .utils import get_logger, is_cache_fresh, read_parquet, write_parquet

log = get_logger("mfrh.finra")

# FINRA consolidated (combined) daily short-sale volume file.
# Format: pipe-delimited text, one file per trading day.
_FINRA_BASE = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{yyyymmdd}.txt"


def _cache_path(yyyymmdd: str) -> Path:
    cfg = load_config()
    return cfg.abs_path(cfg.paths.raw) / f"finra_shortvol__{yyyymmdd}.parquet"


def _download_one_day(d: date) -> pd.DataFrame:
    """Download one day's FINRA short-volume file. Empty frame on failure."""
    yyyymmdd = d.strftime("%Y%m%d")
    cache_path = _cache_path(yyyymmdd)
    # Historical daily files are immutable, so cache effectively never expires;
    # we still honour a long TTL for the most recent (possibly-revised) file.
    if is_cache_fresh(cache_path, max(cache_ttl_minutes(), 1440)):
        cached = read_parquet(cache_path)
        if cached is not None:
            return cached

    url = _FINRA_BASE.format(yyyymmdd=yyyymmdd)
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200 or not resp.text.strip():
            return pd.DataFrame()
        from io import StringIO

        df = pd.read_csv(StringIO(resp.text), sep="|")
        # Trailing summary line begins with a non-data token; drop incomplete rows.
        if "Symbol" not in df.columns:
            return pd.DataFrame()
        df = df.dropna(subset=["Symbol"])
        df.columns = [c.strip() for c in df.columns]
        rename = {
            "Date": "date",
            "Symbol": "symbol",
            "ShortVolume": "short_volume",
            "ShortExemptVolume": "short_exempt_volume",
            "TotalVolume": "total_volume",
            "Market": "market",
        }
        df = df.rename(columns=rename)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
        for c in ["short_volume", "short_exempt_volume", "total_volume"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        if {"short_volume", "total_volume"}.issubset(df.columns):
            df["short_volume_ratio"] = df["short_volume"] / df["total_volume"].replace(0, pd.NA)
        write_parquet(df, cache_path)
        return df
    except Exception as exc:
        log.warning("FINRA download failed for %s: %s", yyyymmdd, exc)
        return pd.DataFrame()


def download_short_sale_volume(
    symbols: Optional[list[str]] = None, lookback_days: int = 10
) -> pd.DataFrame:
    """Download recent FINRA daily short-sale volume for the given symbols.

    Returns a long-format frame ``[date, symbol, short_volume, total_volume,
    short_volume_ratio, ...]`` filtered to ``symbols`` if provided. Weekends and
    missing files are skipped silently. Empty frame if nothing downloads.
    """
    frames = []
    d = date.today()
    collected = 0
    # Walk back over calendar days, skipping weekends, until we have enough.
    for _ in range(lookback_days * 3):
        if collected >= lookback_days:
            break
        if d.weekday() < 5:  # Mon-Fri
            day_df = _download_one_day(d)
            if not day_df.empty:
                frames.append(day_df)
                collected += 1
        d -= timedelta(days=1)

    if not frames:
        log.info("No FINRA short-volume data retrieved (treated as unavailable).")
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    if symbols:
        wanted = {s.upper() for s in symbols}
        out = out[out["symbol"].str.upper().isin(wanted)].reset_index(drop=True)
    return out


def short_volume_features(df: pd.DataFrame, symbol: str) -> dict:
    """Summarise the weak short-volume proxy for a single symbol.

    Returns a dict with the latest short-volume ratio and a short trend. Always
    flags ``proxy=True`` and ``is_short_interest=False`` to avoid misuse.
    """
    base = {
        "symbol": symbol,
        "available": False,
        "proxy": True,
        "is_short_interest": False,
        "latest_short_volume_ratio": None,
        "avg_short_volume_ratio": None,
        "short_volume_ratio_trend": None,
        "note": "FINRA short-sale VOLUME proxy, NOT short interest.",
    }
    if df is None or df.empty:
        return base
    sub = df[df["symbol"].str.upper() == symbol.upper()].copy()
    if sub.empty or "short_volume_ratio" not in sub.columns:
        return base
    sub = sub.sort_values("date")
    ratios = sub["short_volume_ratio"].dropna()
    if ratios.empty:
        return base
    base["available"] = True
    base["latest_short_volume_ratio"] = float(ratios.iloc[-1])
    base["avg_short_volume_ratio"] = float(ratios.mean())
    if len(ratios) >= 2:
        base["short_volume_ratio_trend"] = float(ratios.iloc[-1] - ratios.mean())
    return base
