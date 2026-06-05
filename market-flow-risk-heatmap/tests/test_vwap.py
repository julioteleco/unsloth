"""VWAP correctness and session reset behaviour."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.features_vwap import calculate_session_vwap


def test_vwap_exact_small_frame(tiny_vwap_frame):
    out = calculate_session_vwap(tiny_vwap_frame)
    # typical price == close since high==low==close.
    # cum(tp*vol)/cum(vol):
    #   bar0: 10
    #   bar1: (10*100 + 11*200)/300 = 10.6667
    #   bar2: (10*100 + 11*200 + 12*300)/600 = 11.3333
    expected = [10.0, 3200 / 300, 6800 / 600]
    assert np.allclose(out["vwap"].to_numpy(), expected, atol=1e-9)


def test_vwap_resets_per_session(small_intraday):
    out = calculate_session_vwap(small_intraday)
    # First bar of each session: VWAP equals that bar's typical price.
    first_idx = out.groupby("session_date").head(1).index
    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    assert np.allclose(out.loc[first_idx, "vwap"], typical.loc[first_idx], atol=1e-9)


def test_distance_columns_present(small_intraday):
    out = calculate_session_vwap(small_intraday)
    for col in ["vwap", "distance_to_vwap", "distance_to_vwap_pct", "distance_to_vwap_atr",
                "atr", "atr_pct"]:
        assert col in out.columns


def test_distance_sign_matches_price(small_intraday):
    out = calculate_session_vwap(small_intraday)
    sign_dist = np.sign(out["distance_to_vwap"])
    sign_pct = np.sign(out["distance_to_vwap_pct"])
    # Where both finite, signs agree.
    mask = out["distance_to_vwap"].notna() & out["distance_to_vwap_pct"].notna()
    assert (sign_dist[mask] == sign_pct[mask]).all()
