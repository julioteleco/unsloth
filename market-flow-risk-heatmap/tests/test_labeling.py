"""Triple-barrier labeling: correctness and no lookahead leakage."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.labeling import label_triple_barrier


def _frame(closes, highs, lows, atr=1.0) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2024-01-02 09:30", periods=n, freq="5min", tz="America/New_York")
    return pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000.0] * n,
            "atr": [atr] * n,
        },
        index=idx,
    )


def test_label_long_hits_upper_first():
    # Entry at bar 0 (close=100, atr=1). Upper barrier = 100.8, lower = 99.5.
    # Bar 1 highs to 101 (touches upper) without touching lower -> label 1.
    df = _frame(
        closes=[100, 100.5, 100.5],
        highs=[100, 101.0, 101.0],
        lows=[100, 100.4, 100.4],
        atr=1.0,
    )
    out = label_triple_barrier(df, upper_atr=0.8, lower_atr=0.5, horizon_bars=2)
    assert out["label_long"].iloc[0] == 1


def test_label_long_hits_lower_first():
    df = _frame(
        closes=[100, 99.0, 99.0],
        highs=[100, 99.2, 99.2],
        lows=[100, 99.0, 99.0],
        atr=1.0,
    )
    out = label_triple_barrier(df, upper_atr=0.8, lower_atr=0.5, horizon_bars=2)
    assert out["label_long"].iloc[0] == 0


def test_label_nan_when_no_barrier_touched():
    df = _frame(
        closes=[100, 100.1, 100.1],
        highs=[100, 100.2, 100.2],
        lows=[100, 100.0, 100.0],
        atr=1.0,
    )
    out = label_triple_barrier(df, upper_atr=0.8, lower_atr=0.5, horizon_bars=2)
    assert np.isnan(out["label_long"].iloc[0])


def test_no_lookahead_uses_only_future_bars():
    # The CURRENT bar's own high/low must not trigger the label. Give bar 0 a huge
    # high that would touch the upper barrier; future bars are flat -> label NaN.
    df = _frame(
        closes=[100, 100, 100],
        highs=[200, 100, 100],  # bar 0 spikes, but it's the entry bar
        lows=[100, 100, 100],
        atr=1.0,
    )
    out = label_triple_barrier(df, upper_atr=0.8, lower_atr=0.5, horizon_bars=2)
    # If lookahead were broken, bar 0 would be labeled 1 from its own high.
    assert np.isnan(out["label_long"].iloc[0])


def test_mfe_mae_columns_and_signs():
    df = _frame(
        closes=[100, 101, 99],
        highs=[100, 101.5, 99.5],
        lows=[100, 100.5, 98.5],
        atr=1.0,
    )
    out = label_triple_barrier(df, upper_atr=0.8, lower_atr=0.5, horizon_bars=2)
    for col in ["mfe_atr", "mae_atr", "bars_to_mfe", "bars_to_mae"]:
        assert col in out.columns
    # MFE should be >= 0 and MAE <= 0 (excursions relative to entry).
    assert out["mfe_atr"].iloc[0] >= 0
    assert out["mae_atr"].iloc[0] <= 0


def test_last_bar_label_nan():
    df = _frame(closes=[100, 100], highs=[100, 100], lows=[100, 100], atr=1.0)
    out = label_triple_barrier(df, horizon_bars=12)
    # The final bar has no forward bars -> NaN label.
    assert np.isnan(out["label_long"].iloc[-1])


def test_short_label_uses_mirrored_barriers():
    # Entry 100, atr 1, upper=0.8 lower=0.5.
    # Short profit barrier = 99.2, short stop = 100.5.
    # Price falls to 99.0 (hits short profit) without hitting 100.5 -> label_short 1.
    df = _frame(
        closes=[100, 99.0, 99.0],
        highs=[100, 99.3, 99.3],
        lows=[100, 99.0, 99.0],
        atr=1.0,
    )
    out = label_triple_barrier(df, upper_atr=0.8, lower_atr=0.5, horizon_bars=2)
    assert out["label_short"].iloc[0] == 1
    # The same down-move is a loss for a long (hits -0.5 ATR stop first).
    assert out["label_long"].iloc[0] == 0


def test_short_label_loss_on_rally():
    # Price rallies through the short stop (100.5) first -> label_short 0.
    df = _frame(
        closes=[100, 101, 101],
        highs=[100, 101.0, 101.0],
        lows=[100, 100.6, 100.6],
        atr=1.0,
    )
    out = label_triple_barrier(df, upper_atr=0.8, lower_atr=0.5, horizon_bars=2)
    assert out["label_short"].iloc[0] == 0
    assert out["label_long"].iloc[0] == 1


def test_short_label_no_lookahead():
    # Entry bar's own low spikes far down; future bars flat -> no short label.
    df = _frame(
        closes=[100, 100, 100],
        highs=[100, 100, 100],
        lows=[1, 100, 100],
        atr=1.0,
    )
    out = label_triple_barrier(df, upper_atr=0.8, lower_atr=0.5, horizon_bars=2)
    assert np.isnan(out["label_short"].iloc[0])
