"""yfinance data access with local parquet cache and robust error handling.

Provides OHLCV downloads (intraday and daily) plus options snapshots. Every
public function degrades gracefully: on failure it logs and returns an empty
container rather than raising, so the dashboard never crashes on a bad feed.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import cache_ttl_minutes, load_config
from .utils import (
    get_logger,
    is_cache_fresh,
    normalize_intraday_index,
    read_parquet,
    write_parquet,
)

log = get_logger("mfrh.yfinance")

_OHLCV_COLUMNS = ["datetime", "open", "high", "low", "close", "volume", "ticker"]


def _safe_ticker_filename(ticker: str) -> str:
    """Make a filesystem-safe stem from a ticker (e.g. ``^VIX`` -> ``_VIX``)."""
    return re.sub(r"[^A-Za-z0-9=_-]", "_", ticker)


def _raw_cache_path(ticker: str, period: str, interval: str) -> Path:
    cfg = load_config()
    stem = f"{_safe_ticker_filename(ticker)}__{period}__{interval}.parquet"
    return cfg.abs_path(cfg.paths.raw) / stem


def _flatten_yf_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalize a yfinance frame to the canonical OHLCV schema."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=_OHLCV_COLUMNS)

    df = raw.copy()
    # yfinance can return a MultiIndex column frame for single tickers.
    if isinstance(df.columns, pd.MultiIndex):
        # Prefer the level that holds OHLCV field names.
        lvl0 = set(df.columns.get_level_values(0))
        if {"Open", "Close"}.issubset(lvl0):
            df.columns = df.columns.get_level_values(0)
        else:
            df.columns = df.columns.get_level_values(-1)

    df = normalize_intraday_index(df)
    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].copy()
    df = df.dropna(subset=[c for c in ["open", "high", "low", "close"] if c in df.columns])
    df["volume"] = df.get("volume", 0).fillna(0)
    df["ticker"] = ticker
    df = df.reset_index().rename(columns={df.reset_index().columns[0]: "datetime"})
    # Ensure the index column is named datetime regardless of original name.
    if "datetime" not in df.columns:
        df = df.rename(columns={df.columns[0]: "datetime"})
    for col in _OHLCV_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[_OHLCV_COLUMNS]


def _download_single(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """Download one ticker via yfinance, returning the canonical schema."""
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover - import guard
        log.error("yfinance not importable: %s", exc)
        return pd.DataFrame(columns=_OHLCV_COLUMNS)

    try:
        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            prepost=False,
            progress=False,
            threads=False,
        )
        return _flatten_yf_frame(raw, ticker)
    except Exception as exc:
        log.warning("yfinance download failed for %s (%s/%s): %s", ticker, period, interval, exc)
        return pd.DataFrame(columns=_OHLCV_COLUMNS)


def download_ohlcv(
    tickers: list[str],
    period: str = "60d",
    interval: str = "5m",
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """Download OHLCV for a list of tickers with local caching.

    Returns a mapping ``ticker -> DataFrame`` with columns:
    ``[datetime, open, high, low, close, volume, ticker]``.

    Each frame is cached to ``data/raw`` as parquet. Failures yield an empty
    frame for that ticker rather than raising.
    """
    ttl = cache_ttl_minutes() if use_cache else 0
    out: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        cache_path = _raw_cache_path(ticker, period, interval)
        if not force_refresh and is_cache_fresh(cache_path, ttl):
            cached = read_parquet(cache_path)
            if cached is not None and not cached.empty:
                out[ticker] = cached
                log.info("cache hit: %s (%s/%s, %d rows)", ticker, period, interval, len(cached))
                continue

        df = _download_single(ticker, period, interval)
        if df.empty:
            # Fall back to stale cache if available.
            stale = read_parquet(cache_path)
            if stale is not None and not stale.empty:
                log.info("using stale cache for %s after download failure", ticker)
                out[ticker] = stale
                continue
        else:
            write_parquet(df, cache_path)
        out[ticker] = df
        log.info("downloaded %s: %d rows (%s/%s)", ticker, len(df), period, interval)
    return out


def download_daily(
    tickers: list[str],
    period: str = "2y",
    interval: str = "1d",
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """Convenience wrapper for daily bars (used by breadth/regime context)."""
    return download_ohlcv(
        tickers, period=period, interval=interval, use_cache=use_cache, force_refresh=force_refresh
    )


# --------------------------------------------------------------------------- #
# Options
# --------------------------------------------------------------------------- #
def download_options_snapshot(ticker: str, max_expirations: int = 4) -> dict:
    """Return a lite options snapshot for ``ticker``.

    Structure::

        {
            "ticker": str,
            "available": bool,
            "expirations": [str, ...],
            "calls": pd.DataFrame,
            "puts": pd.DataFrame,
            "error": str | None,
        }

    Never raises. If the chain is unavailable, ``available`` is False and the
    caller should display "options data unavailable".
    """
    result = {
        "ticker": ticker,
        "available": False,
        "expirations": [],
        "calls": pd.DataFrame(),
        "puts": pd.DataFrame(),
        "error": None,
    }
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover
        result["error"] = f"yfinance unavailable: {exc}"
        return result

    cols = [
        "strike",
        "lastPrice",
        "bid",
        "ask",
        "volume",
        "openInterest",
        "impliedVolatility",
    ]
    try:
        tk = yf.Ticker(ticker)
        expirations = list(tk.options or [])
        if not expirations:
            result["error"] = "no expirations returned"
            return result
        chosen = expirations[:max_expirations]
        calls_frames, puts_frames = [], []
        for exp in chosen:
            try:
                chain = tk.option_chain(exp)
            except Exception as exc:
                log.warning("option_chain failed for %s %s: %s", ticker, exp, exc)
                continue
            calls = chain.calls.copy()
            puts = chain.puts.copy()
            calls["expiration"] = exp
            puts["expiration"] = exp
            calls_frames.append(calls)
            puts_frames.append(puts)

        if not calls_frames and not puts_frames:
            result["error"] = "all option_chain calls failed"
            return result

        def _tidy(frames: list[pd.DataFrame]) -> pd.DataFrame:
            if not frames:
                return pd.DataFrame(columns=cols + ["expiration"])
            df = pd.concat(frames, ignore_index=True)
            for c in cols:
                if c not in df.columns:
                    df[c] = pd.NA
            return df[cols + ["expiration"]]

        result["calls"] = _tidy(calls_frames)
        result["puts"] = _tidy(puts_frames)
        result["expirations"] = chosen
        result["available"] = True
        return result
    except Exception as exc:
        log.warning("options snapshot failed for %s: %s", ticker, exc)
        result["error"] = str(exc)
        return result


def latest_close(df: pd.DataFrame) -> Optional[float]:
    """Return the most recent close from a canonical OHLCV frame, or None."""
    if df is None or df.empty or "close" not in df.columns:
        return None
    try:
        return float(df["close"].iloc[-1])
    except Exception:
        return None
