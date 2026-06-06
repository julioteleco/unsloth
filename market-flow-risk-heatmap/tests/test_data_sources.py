"""Tests for the additional free data-source features (seasonality, VIX term,
FRED-derived macro). These run fully offline on synthetic inputs."""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd

from src.data_fred import latest_macro_snapshot
from src.features_seasonality import (
    add_seasonality_columns,
    compute_seasonality_features,
    is_opex,
    is_quad_witching,
    third_friday,
)
from src.features_vol_term import compute_vol_term_features


# --------------------------- seasonality ---------------------------------- #
def test_third_friday_and_opex():
    # June 2024: third Friday is the 21st (and quad-witching month).
    assert third_friday(2024, 6) == datetime.date(2024, 6, 21)
    assert is_opex(datetime.date(2024, 6, 21))
    assert not is_opex(datetime.date(2024, 6, 14))
    assert is_quad_witching(datetime.date(2024, 6, 21))
    # July is not a quad-witching month.
    assert not is_quad_witching(third_friday(2024, 7))


def test_closing_window_flag():
    f = compute_seasonality_features(now=pd.Timestamp("2024-06-03 15:45", tz="America/New_York"))
    assert f["is_closing_window"] is True
    assert f["minutes_to_close"] == 15
    f2 = compute_seasonality_features(now=pd.Timestamp("2024-06-03 10:00", tz="America/New_York"))
    assert f2["is_closing_window"] is False


def test_add_seasonality_columns_vectorised():
    idx = pd.date_range("2024-06-21 09:30", periods=10, freq="5min", tz="America/New_York")
    df = pd.DataFrame({"datetime": idx, "open": 1.0, "high": 1.0, "low": 1.0,
                       "close": 1.0, "volume": 1.0})
    out = add_seasonality_columns(df)
    assert out["is_opex"].all()  # all bars fall on OPEX day
    assert out["is_quad_witching"].all()
    assert (out["minutes_since_open"] >= 0).all()


def test_seasonality_empty_frame():
    out = add_seasonality_columns(pd.DataFrame(columns=["datetime", "close", "high", "low", "volume"]))
    assert out.empty


# --------------------------- VIX term structure --------------------------- #
def _c(v):
    return pd.DataFrame({"close": [v]})


def test_vix_backwardation_detected():
    vt = compute_vol_term_features({"^VIX": _c(25), "^VIX3M": _c(20)})
    assert vt["vix_term_ratio"] > 1.0
    assert vt["vix_backwardation"] is True
    assert vt["vix_contango"] is False


def test_vix_contango_detected():
    vt = compute_vol_term_features({"^VIX": _c(14), "^VIX3M": _c(18)})
    assert vt["vix_term_ratio"] < 1.0
    assert vt["vix_contango"] is True
    assert vt["vix_backwardation"] is False


def test_vol_term_missing_series_degrades():
    vt = compute_vol_term_features({})  # nothing available
    assert vt["vol_term_available"] is False
    assert np.isnan(vt["vix_term_ratio"])
    assert vt["vix_backwardation"] is False


# --------------------------- FRED derived --------------------------------- #
def test_macro_derived_spreads():
    bundle = {
        "DGS10": pd.DataFrame({"value": [4.2]}),
        "DGS2": pd.DataFrame({"value": [4.6]}),
        "DGS3MO": pd.DataFrame({"value": [5.3]}),
        "T10YIE": pd.DataFrame({"value": [2.3]}),
        "BAMLH0A0HYM2": pd.DataFrame({"value": [3.5]}),
    }
    snap = latest_macro_snapshot(bundle)
    assert snap["TERM_SPREAD_10Y_2Y"] == pytest_approx(-0.4)
    assert snap["TERM_SPREAD_10Y_3M"] == pytest_approx(-1.1)
    assert snap["REAL_RATE_10Y"] == pytest_approx(1.9)
    assert snap["HY_OAS"] == 3.5


def test_macro_empty_bundle():
    assert latest_macro_snapshot({}) == {}


def pytest_approx(x, tol=1e-9):
    class _A:
        def __eq__(self, other):
            return abs(other - x) < tol
    return _A()
