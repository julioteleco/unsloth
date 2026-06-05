"""Analytical backtest: bucket scores and measure forward MFE/MAE statistics.

There is NO order execution, NO broker, NO position sizing here. We simply group
historical bars by a chosen score into fixed buckets (0-20, 20-40, ...) and report
hit rate and excursion statistics from the triple-barrier labels. This validates
whether a score has any discriminative power, without pretending to be a strategy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import load_config


def bucket_score_analysis(
    scores: pd.Series,
    labels: pd.DataFrame,
    buckets: list[int] | None = None,
) -> pd.DataFrame:
    """Aggregate forward outcomes by score bucket.

    Parameters
    ----------
    scores:
        Series of a single score (0-100), aligned with ``labels``.
    labels:
        DataFrame from :func:`label_triple_barrier` containing ``label_long``,
        ``mfe_atr``, ``mae_atr``.
    buckets:
        Bucket edges, default ``[0, 20, 40, 60, 80, 100]``.

    Returns one row per bucket with: n_events, hit_rate, mean_mfe, mean_mae,
    mfe_mae_ratio, expectancy.
    """
    cfg = load_config().labeling
    buckets = buckets or cfg.backtest_buckets

    df = pd.DataFrame(
        {
            "score": scores.to_numpy(dtype=float),
            "label_long": labels.get("label_long", pd.Series(np.nan, index=labels.index)).to_numpy(),
            "mfe_atr": labels.get("mfe_atr", pd.Series(np.nan, index=labels.index)).to_numpy(),
            "mae_atr": labels.get("mae_atr", pd.Series(np.nan, index=labels.index)).to_numpy(),
        }
    )
    df = df.dropna(subset=["score"])

    edges = buckets
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        # Last bucket is inclusive of the upper edge.
        if hi == edges[-1]:
            mask = (df["score"] >= lo) & (df["score"] <= hi)
        else:
            mask = (df["score"] >= lo) & (df["score"] < hi)
        sub = df[mask]
        n = len(sub)
        labeled = sub["label_long"].dropna()
        hit_rate = float(labeled.mean()) if len(labeled) else np.nan
        mean_mfe = float(sub["mfe_atr"].mean()) if n else np.nan
        mean_mae = float(sub["mae_atr"].mean()) if n else np.nan
        mfe_mae = (
            float(abs(mean_mfe) / abs(mean_mae))
            if mean_mae not in (0, np.nan) and np.isfinite(mean_mae) and mean_mae != 0
            else np.nan
        )
        # Expectancy proxy: hit_rate * mean_mfe - (1 - hit_rate) * |mean_mae|.
        if np.isfinite(hit_rate) and np.isfinite(mean_mfe) and np.isfinite(mean_mae):
            expectancy = hit_rate * mean_mfe - (1 - hit_rate) * abs(mean_mae)
        else:
            expectancy = np.nan
        rows.append(
            {
                "bucket": f"{lo}-{hi}",
                "n_events": n,
                "hit_rate": hit_rate,
                "mean_mfe_atr": mean_mfe,
                "mean_mae_atr": mean_mae,
                "mfe_mae_ratio": mfe_mae,
                "expectancy_atr": expectancy,
            }
        )
    return pd.DataFrame(rows)


def run_score_backtest(
    features: pd.DataFrame,
    scores_ts: pd.DataFrame,
    labels: pd.DataFrame,
    score_name: str = "Long_Opportunity",
    buckets: list[int] | None = None,
) -> pd.DataFrame:
    """Convenience wrapper: align a named score with labels and bucket it."""
    if score_name not in scores_ts.columns:
        raise KeyError(f"score '{score_name}' not in scores_ts columns: {list(scores_ts.columns)}")
    common = scores_ts.index.intersection(labels.index)
    return bucket_score_analysis(
        scores_ts.loc[common, score_name], labels.loc[common], buckets=buckets
    )
