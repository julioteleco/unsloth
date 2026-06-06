#!/usr/bin/env python
"""Seed the local cache with reproducible synthetic data (offline demo).

Lets you run the dashboard with ZERO network access:

    python scripts/seed_demo_data.py --period 60d --interval 5m
    streamlit run app/streamlit_app.py        # renders on demo data

The data is deterministic and clearly labelled as demo throughout the UI. It is
NOT real market data and must not be used for analysis.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config  # noqa: E402
from src.data_yfinance import _raw_cache_path  # noqa: E402
from src.demo_data import generate_ohlcv  # noqa: E402
from src.utils import get_logger, write_parquet  # noqa: E402

log = get_logger("mfrh.seed_demo")


def main() -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Seed local cache with synthetic demo data.")
    parser.add_argument("--period", default=cfg.download.period)
    parser.add_argument("--interval", default=cfg.download.interval)
    parser.add_argument("--tickers", nargs="*", default=None)
    args = parser.parse_args()

    tickers = args.tickers or cfg.universe.context_universe()
    for t in tickers:
        df = generate_ohlcv(t, period=args.period, interval=args.interval)
        write_parquet(df, _raw_cache_path(t, args.period, args.interval))
        log.info("seeded demo %s: %d rows", t, len(df))

    log.info("Seeded %d tickers into %s", len(tickers), cfg.abs_path(cfg.paths.raw))
    print("\nDemo data ready. Run:  streamlit run app/streamlit_app.py")
    print("NOTE: synthetic data — for demo/offline only, NOT real market data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
