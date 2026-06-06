#!/usr/bin/env python
"""Download and cache OHLCV (and optional FRED/FINRA) data for the universe.

Usage::

    python scripts/download_data.py --period 60d --interval 5m
    python scripts/download_data.py --period 60d --interval 5m --tickers SPY QQQ
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a plain script (python scripts/download_data.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config  # noqa: E402
from src.data_finra import download_short_sale_volume  # noqa: E402
from src.data_fred import download_fred_bundle, fred_available  # noqa: E402
from src.data_yfinance import download_daily, download_ohlcv  # noqa: E402
from src.utils import get_logger  # noqa: E402

log = get_logger("mfrh.download")


def main() -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Download free market data into local cache.")
    parser.add_argument("--period", default=cfg.download.period, help="yfinance period (e.g. 60d)")
    parser.add_argument("--interval", default=cfg.download.interval, help="yfinance interval (e.g. 5m)")
    parser.add_argument("--tickers", nargs="*", default=None, help="override universe tickers")
    parser.add_argument("--with-daily", action="store_true", help="also fetch daily bars")
    parser.add_argument("--with-fred", action="store_true", help="also fetch FRED macro series")
    parser.add_argument("--with-finra", action="store_true", help="also fetch FINRA short-volume proxy")
    parser.add_argument("--force", action="store_true", help="ignore cache and re-download")
    args = parser.parse_args()

    # Default to the full context universe (core + sectors + vol indices + extras).
    tickers = args.tickers or cfg.universe.context_universe()
    log.info("Downloading %d tickers (%s / %s)", len(tickers), args.period, args.interval)
    data = download_ohlcv(tickers, period=args.period, interval=args.interval, force_refresh=args.force)
    ok = sum(1 for d in data.values() if d is not None and not d.empty)
    log.info("Intraday OHLCV: %d/%d tickers returned data", ok, len(tickers))

    if args.with_daily:
        daily = download_daily(tickers, period=cfg.download.daily_period, force_refresh=args.force)
        ok_d = sum(1 for d in daily.values() if d is not None and not d.empty)
        log.info("Daily OHLCV: %d/%d tickers returned data", ok_d, len(tickers))

    if args.with_fred:
        if fred_available():
            bundle = download_fred_bundle()
            ok_f = sum(1 for d in bundle.values() if d is not None and not d.empty)
            log.info("FRED: %d/%d series returned data", ok_f, len(bundle))
        else:
            log.info("FRED_API_KEY not set; skipping FRED (yfinance-only mode).")

    if args.with_finra:
        finra = download_short_sale_volume(symbols=tickers, lookback_days=10)
        if finra.empty:
            log.info("FINRA short-volume unavailable (optional, weak proxy).")
        else:
            log.info("FINRA short-volume: %d rows across recent sessions.", len(finra))

    log.info("Done. Cache directory: %s", cfg.abs_path(cfg.paths.raw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
