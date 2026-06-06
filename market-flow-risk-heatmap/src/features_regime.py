"""Simple market regime classification from free inputs.

Combines VIX behaviour, price-vs-VWAP for SPY/QQQ, and the breadth proxies into a
single coarse regime label. This is intentionally rule-based and transparent so
the dashboard can explain *why* it picked a regime.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import load_config
from .features_breadth import breadth_quality_score


def _last(series: pd.Series, default: float = np.nan) -> float:
    if series is None or series.empty:
        return default
    val = series.dropna()
    return float(val.iloc[-1]) if not val.empty else default


def compute_vix_features(vix_df: pd.DataFrame) -> dict:
    """VIX change and MA relationships from a canonical OHLCV frame."""
    cfg = load_config().features.regime
    out = {
        "vix_level": np.nan,
        "vix_change": np.nan,
        "vix_above_ma5": False,
        "vix_above_ma20": False,
        "vix_rising": False,
    }
    if vix_df is None or vix_df.empty:
        return out
    close = vix_df["close"].astype(float).reset_index(drop=True)
    if close.empty:
        return out
    out["vix_level"] = float(close.iloc[-1])
    if len(close) >= 2:
        out["vix_change"] = float(close.iloc[-1] - close.iloc[-2])
        out["vix_rising"] = out["vix_change"] > 0
    ma5 = close.rolling(cfg.vix_ma_short, min_periods=1).mean().iloc[-1]
    ma20 = close.rolling(cfg.vix_ma_long, min_periods=1).mean().iloc[-1]
    out["vix_above_ma5"] = bool(close.iloc[-1] > ma5)
    out["vix_above_ma20"] = bool(close.iloc[-1] > ma20)
    return out


def compute_regime_features(
    primary_vwap_df: pd.DataFrame | None,
    qqq_vwap_df: pd.DataFrame | None,
    vix_df: pd.DataFrame | None,
    breadth_snapshot: dict | None,
    macro_snapshot: dict | None = None,
) -> dict:
    """Assemble the regime feature dict (one snapshot for the latest bar).

    ``macro_snapshot`` is an optional FRED dict (see ``data_fred``) carrying e.g.
    ``TERM_SPREAD_10Y_2Y``. It is purely additive context and may be empty.
    """
    feats: dict = {}
    feats.update(compute_vix_features(vix_df))

    def _above_vwap(df: pd.DataFrame | None) -> bool:
        if df is None or df.empty or "distance_to_vwap" not in df.columns:
            return False
        return bool(_last(df["distance_to_vwap"], 0.0) > 0)

    feats["spy_above_vwap"] = _above_vwap(primary_vwap_df)
    feats["qqq_above_vwap"] = _above_vwap(qqq_vwap_df)

    snap = breadth_snapshot or {}
    feats["risk_on_proxy"] = float(snap.get("HYG/TLT", {}).get("ratio_trend", 0.0))
    feats["tech_leadership"] = float(snap.get("SMH/QQQ", {}).get("ratio_trend", 0.0))
    feats["breadth_quality"] = breadth_quality_score(snap)

    macro = macro_snapshot or {}
    feats["term_spread_10y_2y"] = macro.get("TERM_SPREAD_10Y_2Y", np.nan)
    feats["term_spread_10y_3m"] = macro.get("TERM_SPREAD_10Y_3M", np.nan)
    feats["yield_curve_inverted"] = bool(
        feats["term_spread_10y_2y"] < 0 if not np.isnan(feats["term_spread_10y_2y"]) else False
    )
    feats["hy_oas"] = macro.get("HY_OAS", np.nan)
    feats["nfci"] = macro.get("NFCI", np.nan)
    # Financial conditions tighter than neutral (>0) is a risk-off tailwind.
    feats["financial_conditions_tight"] = bool(
        feats["nfci"] > 0 if not np.isnan(feats["nfci"]) else False
    )
    feats["macro_available"] = bool(macro)
    return feats


def classify_regime(feats: dict) -> dict:
    """Map regime features to a label with a short rationale.

    Possible labels: bullish_trend, bearish_trend, mean_reversion,
    high_volatility, low_quality_rally, risk_off, neutral.
    """
    reasons: list[str] = []
    vix_rising = feats.get("vix_rising", False)
    vix_above_ma20 = feats.get("vix_above_ma20", False)
    spy_up = feats.get("spy_above_vwap", False)
    qqq_up = feats.get("qqq_above_vwap", False)
    breadth_q = feats.get("breadth_quality", 0.5)
    risk_on = feats.get("risk_on_proxy", 0.0)
    vix_level = feats.get("vix_level", np.nan)

    vix_backwardation = feats.get("volterm_vix_backwardation", False)
    fin_tight = feats.get("financial_conditions_tight", False)

    # High volatility dominates if VIX is elevated/rising OR the term structure is
    # in backwardation (front-month fear above 3-month).
    if ((not np.isnan(vix_level) and vix_level >= 25) and vix_rising and vix_above_ma20) \
            or vix_backwardation:
        if vix_backwardation:
            reasons.append("estructura VIX en backwardation (VIX > VIX3M): estrés")
        else:
            reasons.append("VIX elevado y subiendo (>=25, sobre MA20)")
        return {"regime": "high_volatility", "reasons": reasons}

    if vix_rising and risk_on < 0 and not spy_up:
        reasons.append("VIX subiendo, crédito (HYG/TLT) débil y SPY bajo VWAP")
        if feats.get("yield_curve_inverted"):
            reasons.append("curva 10y-2y invertida (contexto macro de riesgo)")
        if fin_tight:
            reasons.append("condiciones financieras tensas (NFCI > 0)")
        return {"regime": "risk_off", "reasons": reasons}

    if spy_up and qqq_up and breadth_q >= 0.6 and not vix_above_ma20:
        reasons.append("SPY y QQQ sobre VWAP con breadth sano y VIX contenido")
        return {"regime": "bullish_trend", "reasons": reasons}

    if (not spy_up) and (not qqq_up) and breadth_q <= 0.4:
        reasons.append("SPY y QQQ bajo VWAP con breadth débil")
        return {"regime": "bearish_trend", "reasons": reasons}

    if spy_up and breadth_q < 0.5:
        reasons.append("Precio sobre VWAP pero breadth no confirma (rally de baja calidad)")
        return {"regime": "low_quality_rally", "reasons": reasons}

    if not vix_rising and abs(risk_on) < 0.5 and 0.4 <= breadth_q <= 0.6:
        reasons.append("VIX estable y breadth mixto: condiciones de reversión a la media")
        return {"regime": "mean_reversion", "reasons": reasons}

    reasons.append("Sin sesgo dominante claro")
    return {"regime": "neutral", "reasons": reasons}
