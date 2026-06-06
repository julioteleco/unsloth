"""VIX term-structure features (free via yfinance: ^VIX, ^VIX9D, ^VIX3M, ^VVIX).

The slope of the VIX term structure is one of the most informative free regime
signals available. In calm markets the curve is in *contango* (VIX < VIX3M);
under stress it flips into *backwardation* (VIX > VIX3M). The VIX/VIX3M ratio and
the short-end VIX9D/VIX spread are robust, no-cost risk-on/off gauges.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import load_config
from .utils import safe_div


def _last_close(df: pd.DataFrame | None) -> float:
    if df is None or df.empty or "close" not in df.columns:
        return np.nan
    s = df["close"].dropna()
    return float(s.iloc[-1]) if not s.empty else np.nan


def compute_vol_term_features(data_dict: dict[str, pd.DataFrame]) -> dict:
    """Compute VIX term-structure features from a ticker->OHLCV mapping.

    Returns a dict with the available vol levels plus:
        vix_term_ratio       = VIX / VIX3M   (>1 => backwardation/stress)
        vix_contango         = bool(ratio < 1)
        vix_backwardation    = bool(ratio >= threshold)
        vix_short_spread      = VIX9D - VIX   (short-end stress)
        vvix_level           = VVIX (vol-of-vol)
    Missing series degrade to NaN/False without error.
    """
    cfg = load_config().features.regime
    vix = _last_close(data_dict.get("^VIX"))
    vix9d = _last_close(data_dict.get("^VIX9D"))
    vix3m = _last_close(data_dict.get("^VIX3M"))
    vvix = _last_close(data_dict.get("^VVIX"))

    ratio = safe_div(vix, vix3m)
    out = {
        "vix_level": vix,
        "vix9d_level": vix9d,
        "vix3m_level": vix3m,
        "vvix_level": vvix,
        "vix_term_ratio": ratio,
        "vix_contango": bool(ratio < 1.0) if not np.isnan(ratio) else False,
        "vix_backwardation": bool(ratio >= cfg.vix_backwardation_threshold)
        if not np.isnan(ratio) else False,
        "vix_short_spread": (vix9d - vix) if (not np.isnan(vix9d) and not np.isnan(vix)) else np.nan,
        "vol_term_available": not np.isnan(ratio),
    }
    return out
