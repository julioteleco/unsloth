"""RVOL by session-minute: comparison against same minute of prior sessions."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.features_rvol import calculate_rvol_by_session_minute


def _session(date: str, volumes: list[float], base: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range(f"{date} 09:30", periods=len(volumes), freq="5min",
                        tz="America/New_York")
    n = len(volumes)
    return pd.DataFrame(
        {
            "datetime": idx,
            "open": [base] * n,
            "high": [base + 0.5] * n,
            "low": [base - 0.5] * n,
            "close": [base] * n,
            "volume": volumes,
            "ticker": "T",
        }
    )


def test_rvol_uses_same_minute_history():
    # Three sessions; the 2nd bar (session_minute=5) has volumes 100, 100, 200.
    s1 = _session("2024-01-02", [10, 100, 10])
    s2 = _session("2024-01-03", [10, 100, 10])
    s3 = _session("2024-01-04", [10, 200, 10])
    df = pd.concat([s1, s2, s3], ignore_index=True)

    out = calculate_rvol_by_session_minute(df, lookback_days=20)
    # Last session, session_minute == 5: median of prior same-minute volumes
    # (100, 100) == 100, so rvol = 200 / 100 = 2.0.
    last = out[(out["session_date"] == out["session_date"].max()) & (out["session_minute"] == 5)]
    assert len(last) == 1
    assert np.isclose(last["median_volume_same_minute"].iloc[0], 100.0)
    assert np.isclose(last["rvol"].iloc[0], 2.0)


def test_rvol_first_session_is_nan():
    s1 = _session("2024-01-02", [10, 100, 10])
    out = calculate_rvol_by_session_minute(s1, lookback_days=20)
    # No prior sessions -> median undefined -> rvol NaN.
    assert out["rvol"].isna().all()


def test_rvol_not_global_mean():
    # A bar at the volatile open should NOT be flagged climactic just because the
    # open is always high; comparing same-minute history neutralises the U-shape.
    opens_high = [1000, 50, 50]
    s1 = _session("2024-01-02", opens_high)
    s2 = _session("2024-01-03", opens_high)
    s3 = _session("2024-01-04", opens_high)
    df = pd.concat([s1, s2, s3], ignore_index=True)
    out = calculate_rvol_by_session_minute(df)
    # Open bar of last session: rvol ~ 1.0 (1000 vs median 1000), not huge.
    open_bar = out[(out["session_date"] == out["session_date"].max()) & (out["session_minute"] == 0)]
    assert np.isclose(open_bar["rvol"].iloc[0], 1.0)
