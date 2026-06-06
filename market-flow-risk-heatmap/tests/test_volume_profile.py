"""Volume profile sanity: POC/VAH/VAL coherence and feature assignment."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.features_volume_profile import (
    assign_profile_features,
    calculate_volume_profile,
)


def _bars(prices_volumes: list[tuple[float, float]]) -> pd.DataFrame:
    rows = []
    for i, (price, vol) in enumerate(prices_volumes):
        rows.append(
            {
                "datetime": pd.Timestamp("2024-01-02 09:30", tz="America/New_York")
                + pd.Timedelta(minutes=5 * i),
                "open": price,
                "high": price + 0.05,
                "low": price - 0.05,
                "close": price,
                "volume": vol,
                "ticker": "T",
            }
        )
    return pd.DataFrame(rows)


def test_poc_at_highest_volume_price():
    # Concentrate volume at price 100.
    df = _bars([(98, 10), (99, 20), (100, 200), (101, 20), (102, 10)])
    prof = calculate_volume_profile(df, bins=80)
    assert abs(prof.poc - 100.0) < 0.5


def test_value_area_ordering():
    df = _bars([(98, 10), (99, 40), (100, 200), (101, 40), (102, 10)])
    prof = calculate_volume_profile(df, bins=80)
    assert prof.val <= prof.poc <= prof.vah
    assert np.isfinite(prof.val) and np.isfinite(prof.vah)


def test_value_area_within_price_range():
    df = _bars([(98, 10), (99, 40), (100, 200), (101, 40), (102, 10)])
    prof = calculate_volume_profile(df, bins=80)
    assert df["low"].min() - 0.1 <= prof.val
    assert prof.vah <= df["high"].max() + 0.1


def test_assign_profile_features_inside_value_area():
    df = _bars([(98, 10), (99, 40), (100, 200), (101, 40), (102, 10)])
    df["atr"] = 0.5
    prof = calculate_volume_profile(df, bins=80)
    out = assign_profile_features(df, prof)
    for col in ["distance_to_poc", "distance_to_vah", "distance_to_val",
                "near_hvn", "near_lvn", "inside_value_area"]:
        assert col in out.columns
    # The POC-priced bar must sit inside the value area.
    poc_bar = out.iloc[2]
    assert bool(poc_bar["inside_value_area"]) is True


def test_degenerate_bar_assigned_to_close():
    # high == low for every bar -> all volume at the close bin, profile still valid.
    df = _bars([(100, 100)])
    df["high"] = df["close"]
    df["low"] = df["close"]
    prof = calculate_volume_profile(df, bins=80)
    assert np.isfinite(prof.poc)
