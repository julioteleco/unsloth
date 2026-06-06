"""Triple-barrier labeling and MFE/MAE computation (no lookahead leakage).

For each bar we look FORWARD only over the next ``horizon_bars`` and check whether
an ATR-scaled upper barrier is touched before a lower barrier. The label for bar
``i`` is computed strictly from bars ``i+1 ... i+horizon`` — never from bar ``i``
itself — to avoid lookahead bias.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import load_config


def label_triple_barrier(
    df: pd.DataFrame,
    upper_atr: float | None = None,
    lower_atr: float | None = None,
    horizon_bars: int | None = None,
) -> pd.DataFrame:
    """Compute triple-barrier long labels plus MFE/MAE in ATR units.

    For each bar ``i`` (entry at ``close[i]``, ATR from bar ``i``):
        label_long = 1  if +upper_atr*ATR is touched before -lower_atr*ATR
        label_long = 0  if -lower_atr*ATR is touched first
        label_long = NaN if neither barrier is touched within the horizon

    Also adds: mfe_atr, mae_atr, bars_to_mfe, bars_to_mae.
    Forward windows use only future bars (i+1 .. i+horizon): no lookahead.
    """
    cfg = load_config().labeling.triple_barrier
    upper_atr = cfg.upper_atr if upper_atr is None else upper_atr
    lower_atr = cfg.lower_atr if lower_atr is None else lower_atr
    horizon_bars = cfg.horizon_bars if horizon_bars is None else horizon_bars

    out = df.copy()
    n = len(out)
    label = np.full(n, np.nan)
    label_short = np.full(n, np.nan)
    mfe = np.full(n, np.nan)
    mae = np.full(n, np.nan)
    bars_to_mfe = np.full(n, np.nan)
    bars_to_mae = np.full(n, np.nan)

    if n == 0 or "close" not in out.columns or "atr" not in out.columns:
        for c, v in [
            ("label_long", label), ("label_short", label_short),
            ("mfe_atr", mfe), ("mae_atr", mae),
            ("bars_to_mfe", bars_to_mfe), ("bars_to_mae", bars_to_mae),
        ]:
            out[c] = v
        return out

    close = out["close"].to_numpy(dtype=float)
    high = out["high"].to_numpy(dtype=float)
    low = out["low"].to_numpy(dtype=float)
    atr = out["atr"].to_numpy(dtype=float)

    for i in range(n):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        entry = close[i]
        # Long barriers: profit above (+upper), stop below (-lower).
        long_up = entry + upper_atr * a
        long_dn = entry - lower_atr * a
        # Short barriers are mirrored: profit below (-upper), stop above (+lower).
        short_dn = entry - upper_atr * a
        short_up = entry + lower_atr * a
        end = min(i + horizon_bars, n - 1)
        if end <= i:
            continue

        best_up = -np.inf
        best_dn = np.inf
        touched = None        # long outcome
        touched_short = None  # short outcome (own barriers)
        for j in range(i + 1, end + 1):  # FORWARD only
            hi_excursion = (high[j] - entry) / a
            lo_excursion = (low[j] - entry) / a
            if hi_excursion > best_up:
                best_up = hi_excursion
                bars_to_mfe[i] = j - i
            if lo_excursion < best_dn:
                best_dn = lo_excursion
                bars_to_mae[i] = j - i
            if touched is None:
                hit_up = high[j] >= long_up
                hit_dn = low[j] <= long_dn
                if hit_up and hit_dn:
                    touched = 0  # ambiguous within one bar -> conservative loss
                elif hit_up:
                    touched = 1
                elif hit_dn:
                    touched = 0
            if touched_short is None:
                s_hit_dn = low[j] <= short_dn   # short profit target
                s_hit_up = high[j] >= short_up  # short stop
                if s_hit_dn and s_hit_up:
                    touched_short = 0  # conservative loss for the short
                elif s_hit_dn:
                    touched_short = 1
                elif s_hit_up:
                    touched_short = 0

        mfe[i] = best_up if np.isfinite(best_up) else np.nan
        mae[i] = best_dn if np.isfinite(best_dn) else np.nan
        if touched is not None:
            label[i] = touched
        if touched_short is not None:
            label_short[i] = touched_short

    out["label_long"] = label
    out["label_short"] = label_short
    out["mfe_atr"] = mfe
    out["mae_atr"] = mae
    out["bars_to_mfe"] = bars_to_mfe
    out["bars_to_mae"] = bars_to_mae
    return out
