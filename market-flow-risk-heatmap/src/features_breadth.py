"""Free breadth / risk-appetite proxies built from ETF ratio pairs.

We cannot access true advance/decline breadth without a paid feed, so we proxy
market internals with relative-strength ratios such as RSP/SPY (equal vs cap
weight), SMH/QQQ (semis leadership) and HYG/TLT (credit risk appetite).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import load_config


def _close_series(df: pd.DataFrame) -> pd.Series:
    """Extract a datetime-indexed close series from a canonical OHLCV frame."""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    s = df.copy()
    if "datetime" in s.columns:
        s["datetime"] = pd.to_datetime(s["datetime"], utc=True, errors="coerce")
        s = s.set_index("datetime")
    out = s["close"].astype(float)
    out.index = pd.to_datetime(out.index, utc=True)
    return out.sort_index()


def build_breadth_proxy(
    data_dict: dict[str, pd.DataFrame],
    ratios: list[list[str]] | None = None,
    return_windows: list[int] | None = None,
) -> dict[str, pd.DataFrame]:
    """Build relative-strength ratio frames from a ticker->OHLCV mapping.

    Returns ``{"NUM/DEN": DataFrame}`` where each frame has columns:
        ratio_close, ratio_return_1, ratio_return_3, ratio_return_12, ratio_trend

    ``ratio_trend`` is +1 / 0 / -1 from the sign of the medium-window return.
    Missing tickers are skipped gracefully.
    """
    cfg = load_config()
    ratios = ratios or cfg.features.breadth.ratios
    return_windows = return_windows or cfg.features.breadth.return_windows

    out: dict[str, pd.DataFrame] = {}
    for pair in ratios:
        num, den = pair[0], pair[1]
        if num not in data_dict or den not in data_dict:
            continue
        s_num = _close_series(data_dict[num])
        s_den = _close_series(data_dict[den])
        if s_num.empty or s_den.empty:
            continue
        joined = pd.concat([s_num, s_den], axis=1, keys=["num", "den"]).dropna()
        if joined.empty:
            continue
        ratio = (joined["num"] / joined["den"].replace(0, np.nan)).dropna()
        frame = pd.DataFrame({"ratio_close": ratio})
        for w in return_windows:
            frame[f"ratio_return_{w}"] = ratio.pct_change(w)
        mid = return_windows[len(return_windows) // 2] if return_windows else 3
        trend_col = f"ratio_return_{mid}"
        frame["ratio_trend"] = np.sign(frame.get(trend_col, pd.Series(0, index=frame.index)).fillna(0))
        out[f"{num}/{den}"] = frame
    return out


def breadth_snapshot(breadth: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """Latest-value summary per ratio for the dashboard and scoring layer."""
    snap: dict[str, dict] = {}
    for name, frame in breadth.items():
        if frame is None or frame.empty:
            continue
        last = frame.iloc[-1]
        snap[name] = {
            "ratio_close": float(last.get("ratio_close", np.nan)),
            "ratio_return_1": float(last.get("ratio_return_1", np.nan)),
            "ratio_return_3": float(last.get("ratio_return_3", np.nan)),
            "ratio_return_12": float(last.get("ratio_return_12", np.nan)),
            "ratio_trend": float(last.get("ratio_trend", 0.0)),
        }
    return snap


def breadth_quality_score(snapshot: dict[str, dict]) -> float:
    """Aggregate confirming breadth into a 0-1 quality score.

    1.0 means all tracked internals are trending up (risk-on / broad), 0.0 means
    all trending down. 0.5 when neutral or unavailable.
    """
    if not snapshot:
        return 0.5
    trends = [v.get("ratio_trend", 0.0) for v in snapshot.values()]
    if not trends:
        return 0.5
    # Map [-1, 1] mean to [0, 1].
    return float((np.mean(trends) + 1.0) / 2.0)
