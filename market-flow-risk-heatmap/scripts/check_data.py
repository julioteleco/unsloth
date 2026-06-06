#!/usr/bin/env python
"""Data health check: probe every free source and report what works.

Run this to diagnose the "data problem" on any machine:

    python scripts/check_data.py
    python scripts/check_data.py --ticker SPY --period 5d

It reports, per source, whether data was retrieved and from where (live / cache /
stale / demo), so you can immediately see if (e.g.) yfinance is blocked or FRED
needs a key — without digging through logs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import demo_mode, load_config  # noqa: E402
from src.data_finra import download_short_sale_volume  # noqa: E402
from src.data_fred import download_fred_series, fred_available  # noqa: E402
from src.data_yfinance import download_ohlcv, get_data_status  # noqa: E402
from src.utils import get_logger  # noqa: E402

log = get_logger("mfrh.check_data")


def main() -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Probe free data sources and report health.")
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--period", default="5d")
    parser.add_argument("--interval", default=cfg.download.interval)
    args = parser.parse_args()

    print("=" * 60)
    print(" market-flow-risk-heatmap — data health check")
    print("=" * 60)
    print(f" demo_mode env: {demo_mode()}")
    print(f" FRED_API_KEY set: {fred_available()}")
    print("-" * 60)

    # yfinance
    data = download_ohlcv([args.ticker, "^VIX", "^VIX3M"], period=args.period,
                          interval=args.interval, force_refresh=True)
    status = get_data_status()
    print(" yfinance (OHLCV / VIX term structure):")
    for tk, df in data.items():
        rows = 0 if df is None else len(df)
        print(f"   {tk:10s} rows={rows:6d}  source={status.get(tk, '?')}")

    # FRED
    print(" FRED (macro):")
    if fred_available():
        sample = download_fred_series("DGS10", force_refresh=True)
        print(f"   DGS10 rows={len(sample)}  {'OK' if not sample.empty else 'FAILED'}")
    else:
        print("   skipped (no FRED_API_KEY) — system runs yfinance-only")

    # FINRA
    print(" FINRA (short-sale volume proxy):")
    finra = download_short_sale_volume(symbols=[args.ticker], lookback_days=3)
    print(f"   rows={len(finra)}  {'OK' if not finra.empty else 'unavailable (optional)'}")

    print("-" * 60)
    primary = status.get(args.ticker, "?")
    if primary in ("live", "cache"):
        print(f" RESULT: real data OK for {args.ticker} (source={primary}).")
    elif primary in ("stale_cache",):
        print(f" RESULT: only stale cache for {args.ticker}; network may be down.")
    elif primary in ("demo", "demo_fallback"):
        print(f" RESULT: using DEMO data for {args.ticker} — no live feed reachable.")
        print("         (set up network access, or this is offline/sandbox mode.)")
    else:
        print(f" RESULT: NO data for {args.ticker}.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
