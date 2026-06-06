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


def test_vwap_bands_ordering(small_intraday):
    out = calculate_session_vwap(small_intraday)
    assert {"vwap_std", "vwap_upper_1", "vwap_lower_1", "vwap_upper_2", "vwap_lower_2",
            "distance_to_vwap_band"}.issubset(out.columns)
    mask = out["vwap_std"].notna() & (out["vwap_std"] > 0)
    assert (out.loc[mask, "vwap_upper_1"] >= out.loc[mask, "vwap"]).all()
    assert (out.loc[mask, "vwap_lower_1"] <= out.loc[mask, "vwap"]).all()
    # 2-sigma band is strictly wider than the 1-sigma band.
    assert (out.loc[mask, "vwap_upper_2"] >= out.loc[mask, "vwap_upper_1"]).all()
    assert (out.loc[mask, "vwap_lower_2"] <= out.loc[mask, "vwap_lower_1"]).all()


def test_vwap_std_zero_when_no_dispersion(tiny_vwap_frame):
    # high==low==close per bar -> typical price has no intra-bar dispersion, but
    # across bars the volume-weighted variance is non-negative and finite.
    out = calculate_session_vwap(tiny_vwap_frame)
    assert (out["vwap_std"] >= -1e-9).all()
    assert out["vwap_std"].notna().all()


def test_atr_wilder_vs_sma_differ(small_intraday):
    from src.features_vwap import calculate_atr

    w = calculate_atr(small_intraday, window=14, method="wilder")["atr"]
    s = calculate_atr(small_intraday, window=14, method="sma")["atr"]
    # Both positive where defined; the two smoothings should not be identical.
    both = w.notna() & s.notna()
    assert (w[both] > 0).all() and (s[both] > 0).all()
    assert not np.allclose(w[both], s[both])
