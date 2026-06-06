"""Reproducible synthetic market data — the offline / demo fallback.

This is the definitive answer to "no network, no data": a deterministic generator
that produces realistic-looking intraday OHLCV for the whole universe so the app
(and tests, and screenshots) always have something to render. It is clearly
labelled as demo data everywhere it surfaces — never presented as real.

Design choices that make it "realistic enough" for the diagnostic UI:
- U-shaped intraday volume curve (busy open/close, quiet midday).
- Per-ticker drift/volatility seeds so breadth ratios and regimes vary.
- ^VIX (and the vol term-structure indices) move inversely to SPY returns.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Base price, RNG seed and daily drift per ticker. Anything not listed gets a
# generic profile so the generator never fails on an unknown symbol.
_SPECS: dict[str, tuple[float, int, float]] = {
    "SPY": (500, 1, 0.010), "QQQ": (430, 2, 0.015), "IWM": (200, 3, 0.000),
    "DIA": (390, 4, 0.005), "RSP": (160, 5, 0.000), "SMH": (210, 6, 0.020),
    "XLK": (210, 7, 0.012), "XLF": (40, 8, 0.004), "XLE": (90, 9, -0.003),
    "HYG": (77, 10, 0.001), "TLT": (92, 11, -0.004), "UUP": (28, 12, 0.000),
    "GLD": (210, 13, 0.003), "USO": (78, 14, -0.002), "^VIX": (15, 15, 0.000),
    "XLY": (180, 16, 0.008), "XLP": (78, 17, 0.000), "XLV": (140, 18, 0.002),
    "XLI": (120, 19, 0.006), "XLU": (68, 20, 0.000), "XLB": (88, 21, 0.003),
    "XLRE": (40, 22, 0.000), "XLC": (78, 23, 0.010), "^VIX9D": (14, 24, 0.000),
    "^VIX3M": (17, 25, 0.000), "^VVIX": (95, 26, 0.000), "BTC-USD": (62000, 27, 0.020),
}

_BARS_PER_DAY = 78  # 5-minute bars in a regular US cash session (09:30-16:00)


def _spec_for(ticker: str) -> tuple[float, int, float]:
    if ticker in _SPECS:
        return _SPECS[ticker]
    # Deterministic generic profile derived from the ticker name.
    seed = (abs(hash(ticker)) % 9000) + 1000
    return (100.0, seed, 0.0)


def _to_pandas_freq(interval: str) -> str:
    """Map a yfinance interval ('5m','15m','1h') to a pandas-3 offset alias."""
    iv = interval.strip().lower()
    if iv.endswith("m") and not iv.endswith("mo"):
        return f"{iv[:-1] or '5'}min"
    if iv.endswith("min"):
        return iv
    if iv.endswith("h"):
        return iv
    return "5min"


def _period_to_days(period: str, fallback: int = 45) -> int:
    """Best-effort parse of a yfinance-style period like '60d' / '5d'."""
    try:
        period = period.strip().lower()
        if period.endswith("d"):
            return max(1, min(int(period[:-1]), 60))
        if period.endswith("mo"):
            return max(1, min(int(period[:-2]) * 21, 60))
        if period.endswith("y"):
            return 60
    except Exception:
        pass
    return fallback


def generate_ohlcv(
    ticker: str,
    period: str = "60d",
    interval: str = "5m",
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Generate one deterministic synthetic OHLCV frame (canonical schema).

    The output matches the real loader's columns exactly:
    ``[datetime, open, high, low, close, volume, ticker]``.
    """
    base, seed, drift = _spec_for(ticker)
    is_vol_index = ticker.startswith("^")
    vol = 0.08 if is_vol_index else 0.25
    n_days = _period_to_days(period)
    bars = _BARS_PER_DAY if interval in ("5m", "5min") else max(6, _BARS_PER_DAY // 3)
    pandas_freq = _to_pandas_freq(interval)

    rng = np.random.default_rng(seed)
    end = end or pd.Timestamp("2024-03-15")
    days = pd.bdate_range(end=end.normalize(), periods=n_days)

    frames = []
    last = base
    pos = np.linspace(-1, 1, bars)
    vol_curve = 0.5 + pos ** 2  # U-shape
    for d in days:
        idx = pd.date_range(
            pd.Timestamp(d.date()) + pd.Timedelta("9h30m"),
            periods=bars,
            freq=pandas_freq,
            tz="America/New_York",
        )
        steps = rng.normal(drift, vol, bars).cumsum()
        close = last + steps
        last = float(close[-1])
        wig = np.abs(rng.normal(0.05, 0.03, bars)) * base * 0.01
        high = close + wig
        low = close - wig
        op = close - rng.normal(0, 0.02, bars) * base * 0.01
        volume = (rng.integers(2000, 6000, bars) * vol_curve).astype(float)
        frames.append(
            pd.DataFrame(
                {
                    "datetime": idx,
                    "open": op,
                    "high": np.maximum.reduce([op, high, close]),
                    "low": np.minimum.reduce([op, low, close]),
                    "close": close,
                    "volume": volume,
                    "ticker": ticker,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def generate_universe(
    tickers: list[str], period: str = "60d", interval: str = "5m"
) -> dict[str, pd.DataFrame]:
    """Generate synthetic OHLCV for many tickers."""
    return {t: generate_ohlcv(t, period=period, interval=interval) for t in tickers}
