"""Scoring invariants: always in [0, 100], valid labels, robust to NaNs."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.scoring import (
    SCORE_FUNCS,
    compute_all_scores,
    compute_scores_timeseries,
    label_for_score,
)


def _row(**kwargs) -> pd.Series:
    base = {
        "open": 100.0,
        "high": 100.5,
        "low": 99.5,
        "close": 100.0,
        "volume": 1000.0,
        "vwap": 99.8,
        "atr": 0.5,
        "distance_to_vwap": 0.2,
        "distance_to_vwap_atr": 0.4,
        "distance_to_poc": 0.1,
        "distance_to_vah": -0.2,
        "distance_to_val": 0.5,
        "near_hvn": False,
        "near_lvn": False,
        "inside_value_area": True,
        "rvol": 1.2,
        "range_breakout": 0.0,
    }
    base.update(kwargs)
    return pd.Series(base)


def _context(**kwargs) -> dict:
    base = {
        "breadth_quality": 0.5,
        "risk_on_proxy": 0.0,
        "tech_leadership": 0.0,
        "vix_rising": False,
        "options": {"available": False},
    }
    base.update(kwargs)
    return base


def test_all_scores_in_range_normal():
    scores = compute_all_scores(_row(), _context())
    assert set(scores.keys()) == set(SCORE_FUNCS.keys())
    for res in scores.values():
        assert 0.0 <= res.score <= 100.0
        assert res.label in {"bajo", "medio", "alto", "extremo"}


def test_scores_in_range_extreme_inputs():
    extreme = _row(distance_to_vwap_atr=8.0, rvol=12.0, near_hvn=True,
                   inside_value_area=False, distance_to_vah=2.0)
    ctx = _context(breadth_quality=0.0, vix_rising=True, risk_on_proxy=-1.0,
                   tech_leadership=-1.0)
    for res in compute_all_scores(extreme, ctx).values():
        assert 0.0 <= res.score <= 100.0


def test_scores_in_range_with_nans():
    nan_row = _row(distance_to_vwap_atr=np.nan, rvol=np.nan, atr=np.nan)
    for res in compute_all_scores(nan_row, _context()).values():
        assert 0.0 <= res.score <= 100.0


def test_label_thresholds():
    assert label_for_score(0) == "bajo"
    assert label_for_score(30) == "medio"
    assert label_for_score(60) == "alto"
    assert label_for_score(90) == "extremo"


def test_long_risk_increases_with_extension():
    low_ext = compute_all_scores(_row(distance_to_vwap_atr=0.1), _context())["Long_Risk"].score
    high_ext = compute_all_scores(
        _row(distance_to_vwap_atr=2.5, rvol=2.5, near_hvn=True, inside_value_area=False),
        _context(breadth_quality=0.2, vix_rising=True),
    )["Long_Risk"].score
    assert high_ext > low_ext


def test_timeseries_scores_in_range(small_intraday):
    from src.features_vwap import calculate_session_vwap

    feats = calculate_session_vwap(small_intraday)
    feats["rvol"] = 1.0
    feats["inside_value_area"] = True
    feats["near_hvn"] = False
    feats["near_lvn"] = False
    feats["distance_to_vah"] = 0.0
    feats["distance_to_val"] = 0.0
    feats["range_breakout"] = 0.0
    ts = compute_scores_timeseries(feats, _context())
    valid = ts.to_numpy()
    valid = valid[~np.isnan(valid)]
    assert (valid >= 0).all() and (valid <= 100).all()
