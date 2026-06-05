#!/usr/bin/env python
"""Run the analytical (no-execution) bucket backtest for a ticker/score.

Usage::

    python scripts/run_backtest.py --ticker SPY --score Long_Opportunity
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest import run_score_backtest  # noqa: E402
from src.config import load_config  # noqa: E402
from src.labeling import label_triple_barrier  # noqa: E402
from src.pipeline import build_ticker_bundle, scores_timeseries_for_bundle  # noqa: E402
from src.scoring import SCORE_FUNCS  # noqa: E402
from src.utils import get_logger  # noqa: E402

log = get_logger("mfrh.backtest")


def main() -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Analytical score-bucket backtest (MFE/MAE).")
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--period", default=cfg.download.period)
    parser.add_argument("--interval", default=cfg.download.interval)
    parser.add_argument("--score", default="Long_Opportunity", choices=list(SCORE_FUNCS.keys()))
    parser.add_argument("--upper-atr", type=float, default=cfg.labeling.triple_barrier.upper_atr)
    parser.add_argument("--lower-atr", type=float, default=cfg.labeling.triple_barrier.lower_atr)
    parser.add_argument("--horizon", type=int, default=cfg.labeling.triple_barrier.horizon_bars)
    args = parser.parse_args()

    bundle = build_ticker_bundle(args.ticker, period=args.period, interval=args.interval)
    if bundle.features is None or bundle.features.empty:
        log.error("No features for %s.", args.ticker)
        return 1

    labels = label_triple_barrier(
        bundle.features,
        upper_atr=args.upper_atr,
        lower_atr=args.lower_atr,
        horizon_bars=args.horizon,
    )
    scores_ts = scores_timeseries_for_bundle(bundle)
    table = run_score_backtest(bundle.features, scores_ts, labels, score_name=args.score)

    print(f"\n=== Bucket analysis: {args.score} on {args.ticker} "
          f"(upper={args.upper_atr} ATR, lower={args.lower_atr} ATR, horizon={args.horizon}) ===")
    with_pd_options(table)
    print("\nNOTA: análisis estadístico, sin ejecución ni broker. No es asesoramiento financiero.")
    return 0


def with_pd_options(table) -> None:
    import pandas as pd

    with pd.option_context("display.float_format", lambda x: f"{x:6.3f}", "display.width", 120):
        print(table.to_string(index=False))


if __name__ == "__main__":
    raise SystemExit(main())
