#!/usr/bin/env python
"""Build and persist intraday features + scores for a single ticker.

Usage::

    python scripts/build_features.py --ticker SPY
    python scripts/build_features.py --ticker QQQ --period 30d --no-options
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config  # noqa: E402
from src.explain import explain_current_state  # noqa: E402
from src.pipeline import build_ticker_bundle, latest_scores, persist_features  # noqa: E402
from src.utils import get_logger  # noqa: E402

log = get_logger("mfrh.build_features")


def main() -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Build features and scores for a ticker.")
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--period", default=cfg.download.period)
    parser.add_argument("--interval", default=cfg.download.interval)
    parser.add_argument("--no-options", action="store_true", help="skip options snapshot")
    parser.add_argument("--force", action="store_true", help="ignore cache")
    args = parser.parse_args()

    bundle = build_ticker_bundle(
        args.ticker,
        period=args.period,
        interval=args.interval,
        use_options=not args.no_options,
        force_refresh=args.force,
    )
    if bundle.features is None or bundle.features.empty:
        log.error("No data/features for %s. Check connectivity or ticker.", args.ticker)
        return 1

    persist_features(bundle)
    scores, row = latest_scores(bundle)
    diag = explain_current_state(row, scores)

    log.info("Regime: %s", bundle.regime.get("regime"))
    print("\n=== Scores (latest bar) ===")
    for name, res in scores.items():
        print(f"  {name:28s} {res.score:6.1f}  [{res.label}]")
    print("\n=== Diagnosis ===")
    print(diag["summary"])
    print("\n" + diag["disclaimer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
