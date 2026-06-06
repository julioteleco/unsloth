"""Demo-data generator + offline fallback / provenance behaviour."""
from __future__ import annotations

import os

import pandas as pd

from src.data_yfinance import _OHLCV_COLUMNS, download_ohlcv, get_data_status
from src.demo_data import generate_ohlcv, generate_universe


def test_demo_frame_schema_and_nonempty():
    df = generate_ohlcv("SPY", period="10d", interval="5m")
    assert list(df.columns) == _OHLCV_COLUMNS
    assert not df.empty
    assert (df["high"] >= df["low"]).all()
    assert (df["volume"] >= 0).all()
    assert df["ticker"].eq("SPY").all()


def test_demo_is_deterministic():
    a = generate_ohlcv("QQQ", period="10d")
    b = generate_ohlcv("QQQ", period="10d")
    pd.testing.assert_frame_equal(a, b)


def test_demo_unknown_ticker_still_generates():
    df = generate_ohlcv("ZZZZ", period="5d")
    assert not df.empty


def test_generate_universe_keys():
    out = generate_universe(["SPY", "^VIX"], period="5d")
    assert set(out.keys()) == {"SPY", "^VIX"}
    assert not out["^VIX"].empty


def test_demo_mode_env_forces_synthetic(monkeypatch, tmp_path):
    # In demo mode the loader must not need the network and must report 'demo'.
    monkeypatch.setenv("MFRH_DEMO_MODE", "1")
    monkeypatch.setenv("MFRH_DATA_DIR", str(tmp_path))
    out = download_ohlcv(["SPY"], period="5d", interval="5m", force_refresh=True)
    assert not out["SPY"].empty
    assert get_data_status().get("SPY") == "demo"


def test_demo_fallback_when_offline(monkeypatch, tmp_path):
    # No demo mode, but force a failed download into an empty cache dir ->
    # fallback should kick in and label the source as demo_fallback.
    monkeypatch.delenv("MFRH_DEMO_MODE", raising=False)
    monkeypatch.setenv("MFRH_DEMO_FALLBACK", "1")
    monkeypatch.setenv("MFRH_DATA_DIR", str(tmp_path))

    import src.data_yfinance as dy

    monkeypatch.setattr(dy, "_download_single", lambda *a, **k: pd.DataFrame(columns=_OHLCV_COLUMNS))
    out = dy.download_ohlcv(["NOPE"], period="5d", interval="5m", force_refresh=True)
    assert not out["NOPE"].empty
    assert dy.get_data_status().get("NOPE") == "demo_fallback"


def test_demo_fallback_disabled_yields_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("MFRH_DEMO_MODE", raising=False)
    monkeypatch.setenv("MFRH_DEMO_FALLBACK", "0")
    monkeypatch.setenv("MFRH_DATA_DIR", str(tmp_path))

    import src.data_yfinance as dy

    monkeypatch.setattr(dy, "_download_single", lambda *a, **k: pd.DataFrame(columns=_OHLCV_COLUMNS))
    out = dy.download_ohlcv(["NOPE2"], period="5d", interval="5m", force_refresh=True)
    assert out["NOPE2"].empty
    assert dy.get_data_status().get("NOPE2") == "empty"
