"""High-level orchestration: build features, context and scores for a ticker.

This glues the individual feature modules together so the CLI scripts and the
Streamlit app share one code path. Everything degrades gracefully: a failing data
source yields empty/neutral outputs instead of an exception.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import load_config
from .data_yfinance import (
    download_ohlcv,
    download_options_snapshot,
    get_data_status,
    latest_close,
)
from .features_breadth import breadth_quality_score, breadth_snapshot, build_breadth_proxy
from .features_options import compute_options_features
from .features_regime import classify_regime, compute_regime_features
from .features_rvol import calculate_rvol_by_session_minute
from .features_seasonality import compute_seasonality_features
from .features_vol_term import compute_vol_term_features
from .features_volume_profile import (
    VolumeProfile,
    assign_profile_features,
    calculate_volume_profile,
)
from .features_vwap import calculate_session_vwap
from .scoring import compute_all_scores, compute_scores_timeseries
from .utils import get_logger, write_parquet

log = get_logger("mfrh.pipeline")


@dataclass
class TickerBundle:
    ticker: str
    features: pd.DataFrame
    profile: VolumeProfile
    context: dict
    breadth: dict
    breadth_snap: dict
    options_features: dict
    regime: dict
    raw: dict = field(default_factory=dict)
    data_status: dict = field(default_factory=dict)

    def data_summary(self) -> dict:
        """Aggregate provenance: counts by source + overall flags."""
        counts: dict[str, int] = {}
        for src in self.data_status.values():
            counts[src] = counts.get(src, 0) + 1
        is_demo = any(s in ("demo", "demo_fallback") for s in self.data_status.values())
        primary_src = self.data_status.get(self.ticker, "unknown")
        return {
            "counts": counts,
            "is_demo": is_demo,
            "primary_source": primary_src,
            "n_tickers": len(self.data_status),
        }


def build_intraday_features(df: pd.DataFrame) -> tuple[pd.DataFrame, VolumeProfile]:
    """Run VWAP/ATR, RVOL and volume-profile features on one OHLCV frame."""
    if df is None or df.empty:
        return pd.DataFrame(), calculate_volume_profile(pd.DataFrame())

    feats = calculate_session_vwap(df)
    rvol = calculate_rvol_by_session_minute(df)
    # Merge RVOL columns (share the same index after both reindex to datetime).
    for col in ["session_minute", "median_volume_same_minute", "rvol", "rvol_zscore"]:
        if col in rvol.columns:
            feats[col] = rvol[col].reindex(feats.index)

    profile = calculate_volume_profile(feats)
    feats = assign_profile_features(feats, profile)

    # Simple range-breakout helper used by Breakout_Quality: close beyond the
    # trailing 20-bar high/low.
    roll_high = feats["high"].rolling(20, min_periods=5).max().shift(1)
    roll_low = feats["low"].rolling(20, min_periods=5).min().shift(1)
    atr = feats.get("atr")
    if atr is not None:
        up_break = (feats["close"] - roll_high) / atr.replace(0, pd.NA)
        dn_break = (roll_low - feats["close"]) / atr.replace(0, pd.NA)
        feats["range_breakout"] = up_break.clip(lower=0).fillna(0) + dn_break.clip(lower=0).fillna(0)
    else:
        feats["range_breakout"] = 0.0
    return feats, profile


def build_context(
    data_dict: dict[str, pd.DataFrame],
    primary_feats: pd.DataFrame,
    qqq_feats: pd.DataFrame | None,
    options_features: dict | None,
    macro_snapshot: dict | None = None,
) -> tuple[dict, dict, dict, dict]:
    """Assemble cross-asset context, breadth, snapshot and regime dicts."""
    breadth = build_breadth_proxy(data_dict)
    snap = breadth_snapshot(breadth)

    vol_term = compute_vol_term_features(data_dict)
    seasonality = compute_seasonality_features(
        primary_feats.index if primary_feats is not None and not primary_feats.empty else None
    )

    vix_df = data_dict.get("^VIX", pd.DataFrame())
    regime_feats = compute_regime_features(primary_feats, qqq_feats, vix_df, snap, macro_snapshot)
    regime_feats.update({f"volterm_{k}": v for k, v in vol_term.items()})
    regime = classify_regime(regime_feats)
    regime["features"] = regime_feats

    context = {
        "breadth_quality": breadth_quality_score(snap),
        "risk_on_proxy": regime_feats.get("risk_on_proxy", 0.0),
        "tech_leadership": regime_feats.get("tech_leadership", 0.0),
        "vix_rising": regime_feats.get("vix_rising", False),
        "vix_level": regime_feats.get("vix_level", float("nan")),
        "term_spread_10y_2y": regime_feats.get("term_spread_10y_2y", float("nan")),
        "vix_backwardation": vol_term.get("vix_backwardation", False),
        "vix_term_ratio": vol_term.get("vix_term_ratio", float("nan")),
        "regime": regime.get("regime", "neutral"),
        "options": options_features or {"available": False},
        "macro": macro_snapshot or {},
        "vol_term": vol_term,
        "seasonality": seasonality,
    }
    return context, breadth, snap, regime


def build_ticker_bundle(
    ticker: str,
    period: str = "60d",
    interval: str = "5m",
    use_options: bool = True,
    force_refresh: bool = False,
) -> TickerBundle:
    """End-to-end: download data, build features, context and store a bundle.

    Downloads the primary ticker plus the full universe (for breadth/regime),
    builds features, computes the cross-asset context and returns a bundle the
    dashboard can render directly.
    """
    cfg = load_config()
    # Full context universe: core + sectors + vol-structure indices + extras.
    universe = list(dict.fromkeys([ticker, "QQQ", "SPY", *cfg.universe.context_universe()]))
    data_dict = download_ohlcv(universe, period=period, interval=interval, force_refresh=force_refresh)

    primary_df = data_dict.get(ticker, pd.DataFrame())
    feats, profile = build_intraday_features(primary_df)

    qqq_feats = None
    if "QQQ" in data_dict and not data_dict["QQQ"].empty:
        qqq_feats, _ = build_intraday_features(data_dict["QQQ"])

    options_features = {"available": False}
    if use_options and ticker in cfg.universe.options_tickers:
        snap = download_options_snapshot(ticker)
        options_features = compute_options_features(snap, spot=latest_close(primary_df))

    # Optional FRED macro context (no-op without FRED_API_KEY).
    macro_snapshot: dict = {}
    try:
        from .data_fred import fred_available, latest_macro_snapshot

        if fred_available():
            macro_snapshot = latest_macro_snapshot()
    except Exception:  # macro is purely additive; never block the pipeline
        macro_snapshot = {}

    context, breadth, breadth_snap, regime = build_context(
        data_dict, feats, qqq_feats, options_features, macro_snapshot
    )

    return TickerBundle(
        ticker=ticker,
        features=feats,
        profile=profile,
        context=context,
        breadth=breadth,
        breadth_snap=breadth_snap,
        options_features=options_features,
        regime=regime,
        raw=data_dict,
        data_status=get_data_status(),
    )


def latest_scores(bundle: TickerBundle):
    """Compute scores for the most recent bar of a bundle."""
    if bundle.features is None or bundle.features.empty:
        return {}, None
    row = bundle.features.iloc[-1]
    scores = compute_all_scores(row, bundle.context)
    return scores, row


def persist_features(bundle: TickerBundle) -> None:
    """Write the feature frame to ``data/features`` as parquet."""
    if bundle.features is None or bundle.features.empty:
        return
    cfg = load_config()
    from .data_yfinance import _safe_ticker_filename  # local import to avoid cycle

    path = cfg.abs_path(cfg.paths.features) / f"{_safe_ticker_filename(bundle.ticker)}_features.parquet"
    out = bundle.features.copy()
    out.index.name = "datetime"
    write_parquet(out.reset_index(), path)
    log.info("persisted features for %s -> %s", bundle.ticker, path)


def scores_timeseries_for_bundle(bundle: TickerBundle) -> pd.DataFrame:
    """Compute the per-bar score time series for heatmaps/backtests."""
    if bundle.features is None or bundle.features.empty:
        return pd.DataFrame()
    return compute_scores_timeseries(bundle.features, bundle.context)
