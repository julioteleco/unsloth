"""Shared pytest fixtures and path setup for the test suite."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Make ``src`` importable when running pytest from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_session(date: str, n: int = 12, base: float = 100.0, seed: int = 0) -> pd.DataFrame:
    """Build a small intraday session of 5m bars in US/Eastern."""
    rng = np.random.default_rng(seed)
    start = pd.Timestamp(f"{date} 09:30", tz="America/New_York")
    idx = pd.date_range(start, periods=n, freq="5min")
    steps = rng.normal(0, 0.2, n).cumsum()
    close = base + steps
    high = close + np.abs(rng.normal(0.1, 0.05, n))
    low = close - np.abs(rng.normal(0.1, 0.05, n))
    open_ = close - rng.normal(0, 0.05, n)
    volume = rng.integers(1000, 5000, n).astype(float)
    return pd.DataFrame(
        {
            "datetime": idx,
            "open": open_,
            "high": np.maximum.reduce([open_, high, close]),
            "low": np.minimum.reduce([open_, low, close]),
            "close": close,
            "volume": volume,
            "ticker": "TEST",
        }
    )


@pytest.fixture
def small_intraday() -> pd.DataFrame:
    """Two sessions of 12 bars each, deterministic."""
    a = _make_session("2024-01-02", n=12, base=100.0, seed=1)
    b = _make_session("2024-01-03", n=12, base=101.0, seed=2)
    return pd.concat([a, b], ignore_index=True)


@pytest.fixture
def tiny_vwap_frame() -> pd.DataFrame:
    """Hand-built frame with known VWAP for exact assertions."""
    idx = pd.date_range("2024-01-02 09:30", periods=3, freq="5min", tz="America/New_York")
    return pd.DataFrame(
        {
            "datetime": idx,
            "open": [10.0, 11.0, 12.0],
            "high": [10.0, 11.0, 12.0],
            "low": [10.0, 11.0, 12.0],
            "close": [10.0, 11.0, 12.0],
            "volume": [100.0, 200.0, 300.0],
            "ticker": "TEST",
        }
    )
