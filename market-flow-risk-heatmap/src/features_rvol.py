"""Relative volume (RVOL) computed per session-minute.

Crucially this does NOT compare a bar's volume to a global average. It compares
each bar to the *median* volume seen at the SAME session-minute across the prior
``lookback_days`` sessions. That captures the U-shaped intraday volume curve, so
an open-auction bar isn't flagged "climactic" just for being the open.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import load_config
from .utils import normalize_intraday_index, session_date, session_minute


def _ensure_indexed(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "datetime" in out.columns and not isinstance(out.index, pd.DatetimeIndex):
        out["datetime"] = pd.to_datetime(out["datetime"], utc=True, errors="coerce")
        out = out.set_index("datetime")
    out = normalize_intraday_index(out)
    return out.sort_index()


def calculate_rvol_by_session_minute(
    df: pd.DataFrame, lookback_days: int | None = None
) -> pd.DataFrame:
    """Add ``session_minute``, ``median_volume_same_minute`` and ``rvol``.

    For each row, ``median_volume_same_minute`` is the trailing median volume at
    the same session-minute over the previous ``lookback_days`` *distinct*
    sessions (excluding the current session to avoid leakage). ``rvol`` is the
    bar's volume divided by that median.
    """
    cfg = load_config()
    lookback_days = lookback_days or cfg.features.rvol.lookback_days

    out = _ensure_indexed(df)
    if out.empty:
        out["session_minute"] = np.nan
        out["median_volume_same_minute"] = np.nan
        out["rvol"] = np.nan
        return out

    cfg = load_config().features.rvol
    out["session_date"] = session_date(out.index).values
    out["session_minute"] = session_minute(out.index).values
    out["volume"] = out["volume"].fillna(0)

    # Pivot to a [session x minute] volume matrix, then take a trailing median of
    # the SAME minute across the prior `lookback_days` sessions (excluding today,
    # so there is no same-bar leakage). This is fully vectorised.
    tmp = out.reset_index().rename(columns={out.index.name or "index": "datetime"})
    by_session = tmp.groupby(["session_date", "session_minute"])["volume"].last().reset_index()
    pivot = by_session.pivot(index="session_date", columns="session_minute", values="volume")
    pivot = pivot.sort_index()
    # Trailing median over previous sessions only (shift(1) drops current row).
    trailing_median = pivot.shift(1).rolling(window=lookback_days, min_periods=1).median()

    median_map = trailing_median.stack(future_stack=True).rename("median_volume_same_minute")
    median_df = median_map.reset_index()
    out = out.reset_index().rename(columns={out.index.name or "index": "datetime"})
    out = out.merge(median_df, on=["session_date", "session_minute"], how="left")
    out = out.set_index("datetime")

    out["rvol"] = out["volume"] / out["median_volume_same_minute"].replace(0, np.nan)
    if cfg.clip_max and cfg.clip_max > 0:
        out["rvol"] = out["rvol"].clip(upper=cfg.clip_max)
    # Log-RVOL z-score across the sample: a standardised "how unusual" measure.
    log_rvol = np.log(out["rvol"].replace(0, np.nan))
    out["rvol_zscore"] = (log_rvol - log_rvol.mean()) / log_rvol.std(ddof=0) if log_rvol.notna().sum() > 2 else np.nan
    return out
