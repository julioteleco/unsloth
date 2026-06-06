"""FRED macro series access. The API key is OPTIONAL.

If ``FRED_API_KEY`` is absent, every function returns empty frames and logs an
informational message; the rest of the system continues on yfinance data only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from .config import cache_ttl_minutes, get_fred_api_key, load_config
from .utils import get_logger, is_cache_fresh, read_parquet, write_parquet

log = get_logger("mfrh.fred")

_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


def fred_available() -> bool:
    """True if a FRED API key is configured."""
    return get_fred_api_key() is not None


def _cache_path(series_id: str) -> Path:
    cfg = load_config()
    return cfg.abs_path(cfg.paths.raw) / f"fred__{series_id}.parquet"


def download_fred_series(series_id: str, force_refresh: bool = False) -> pd.DataFrame:
    """Download a single FRED series as a tidy DataFrame.

    Returns columns ``[date, value]`` (value as float, NaNs dropped). Returns an
    empty frame when no API key is set or on any network/parse error.
    """
    empty = pd.DataFrame(columns=["date", "value"])
    key = get_fred_api_key()
    if key is None:
        log.info("FRED_API_KEY not set; skipping series %s (yfinance-only mode)", series_id)
        return empty

    cache_path = _cache_path(series_id)
    if not force_refresh and is_cache_fresh(cache_path, cache_ttl_minutes()):
        cached = read_parquet(cache_path)
        if cached is not None:
            return cached

    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
    }
    try:
        resp = requests.get(_FRED_URL, params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        obs = payload.get("observations", [])
        if not obs:
            log.warning("FRED returned no observations for %s", series_id)
            return empty
        df = pd.DataFrame(obs)[["date", "value"]]
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"]).reset_index(drop=True)
        write_parquet(df, cache_path)
        log.info("FRED %s: %d observations", series_id, len(df))
        return df
    except Exception as exc:
        log.warning("FRED download failed for %s: %s", series_id, exc)
        stale = read_parquet(cache_path)
        return stale if stale is not None else empty


def download_fred_bundle(series_ids: Optional[list[str]] = None) -> dict[str, pd.DataFrame]:
    """Download the configured FRED series bundle. Empty dict-friendly."""
    cfg = load_config()
    ids = series_ids if series_ids is not None else cfg.fred.series
    return {sid: download_fred_series(sid) for sid in ids}


def latest_macro_snapshot(bundle: Optional[dict[str, pd.DataFrame]] = None) -> dict[str, float]:
    """Return the latest value of each FRED series plus derived risk gauges.

    Derived fields (only when their inputs are present):
        TERM_SPREAD_10Y_2Y   = DGS10 - DGS2     (curve slope; <0 = inverted)
        TERM_SPREAD_10Y_3M   = DGS10 - DGS3MO   (Fed's preferred recession slope)
        REAL_RATE_10Y        = DGS10 - T10YIE   (10y real yield proxy)
        HY_OAS               = BAMLH0A0HYM2     (high-yield credit stress)
        IG_OAS               = BAMLC0A0CM       (investment-grade credit stress)
        NFCI / ANFCI         financial-conditions indices (>0 = tighter)
    """
    if bundle is None:
        bundle = download_fred_bundle()
    snap: dict[str, float] = {}
    for sid, df in bundle.items():
        if df is not None and not df.empty:
            snap[sid] = float(df["value"].iloc[-1])

    if "DGS10" in snap and "DGS2" in snap:
        snap["TERM_SPREAD_10Y_2Y"] = snap["DGS10"] - snap["DGS2"]
    if "DGS10" in snap and "DGS3MO" in snap:
        snap["TERM_SPREAD_10Y_3M"] = snap["DGS10"] - snap["DGS3MO"]
    if "DGS10" in snap and "T10YIE" in snap:
        snap["REAL_RATE_10Y"] = snap["DGS10"] - snap["T10YIE"]
    if "BAMLH0A0HYM2" in snap:
        snap["HY_OAS"] = snap["BAMLH0A0HYM2"]
    if "BAMLC0A0CM" in snap:
        snap["IG_OAS"] = snap["BAMLC0A0CM"]
    return snap
