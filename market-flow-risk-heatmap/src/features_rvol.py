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

    out["session_date"] = session_date(out.index).values
    out["session_minute"] = session_minute(out.index).values
    out["volume"] = out["volume"].fillna(0)

    # Work on positional integers to stay robust against duplicate timestamps.
    out = out.reset_index().rename(columns={out.index.name or "index": "datetime"})
    medians = np.full(len(out), np.nan)

    sessions = sorted(out["session_date"].unique())
    session_pos = {d: i for i, d in enumerate(sessions)}

    for _minute, grp in out.groupby("session_minute", sort=False):
        # Volume at this minute per session (last wins on overlap).
        by_session = grp.groupby("session_date")["volume"].last()
        for pos, sess in zip(grp.index, grp["session_date"]):
            cur_pos = session_pos[sess]
            prior_vols = [
                by_session[s] for s in by_session.index if session_pos[s] < cur_pos
            ]
            prior_vols = prior_vols[-lookback_days:]
            if prior_vols:
                medians[pos] = float(np.median(prior_vols))

    out["median_volume_same_minute"] = medians
    out = out.set_index("datetime")
    out["rvol"] = out["volume"] / out["median_volume_same_minute"].replace(0, np.nan)
    return out
