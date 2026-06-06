"""Risk / opportunity scoring (0-100) with transparent factor explanations.

Each score is a weighted blend of bounded factors in [0, 1]. Every factor records
a human-readable reason when it is materially "on", so the explanation layer can
surface the 3-6 dominant drivers. Scores never silently exceed [0, 100].

These are DIAGNOSTIC scores, not trade signals and not financial advice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from .config import load_config
from .utils import clip_score


@dataclass
class Factor:
    name: str
    value: float  # bounded [0, 1] contribution intensity
    weight: float
    reason: str  # filled when the factor is materially active


@dataclass
class ScoreResult:
    name: str
    score: float
    label: str
    factors: list[Factor] = field(default_factory=list)
    explanation: str = ""

    def top_reasons(self, k: int = 6) -> list[str]:
        active = [f for f in self.factors if f.reason and f.value > 0.15]
        active.sort(key=lambda f: f.value * f.weight, reverse=True)
        return [f.reason for f in active[:k]]

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "label": self.label,
            "explanation": self.explanation,
            "factors": [
                {"name": f.name, "value": f.value, "weight": f.weight, "reason": f.reason}
                for f in self.factors
            ],
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def label_for_score(score: float) -> str:
    """Map a 0-100 score to bajo / medio / alto / extremo."""
    cfg = load_config().scoring.labels
    if score < cfg.bajo:
        return "bajo"
    if score < cfg.medio:
        return "medio"
    if score < cfg.alto:
        return "alto"
    return "extremo"


def _saturate(x: float, scale: float) -> float:
    """Map |x|/scale into [0, 1] with soft saturation (1 - exp)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 0.0
    return float(1.0 - np.exp(-abs(x) / max(scale, 1e-9)))


def _combine(factors: list[Factor]) -> float:
    total_w = sum(f.weight for f in factors)
    if total_w <= 0:
        return 50.0
    weighted = sum(f.value * f.weight for f in factors)
    return clip_score(100.0 * weighted / total_w)


def _row_get(row: pd.Series, key: str, default: float = np.nan) -> float:
    try:
        v = row.get(key, default)
        return float(v) if v is not None else default
    except Exception:
        return default


def _ctx(context: dict, *keys, default=0.0):
    cur = context
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur if cur is not None else default


def _finalize(name: str, factors: list[Factor]) -> ScoreResult:
    score = _combine(factors)
    res = ScoreResult(name=name, score=score, label=label_for_score(score), factors=factors)
    return res


# --------------------------------------------------------------------------- #
# Individual scores
# --------------------------------------------------------------------------- #
def score_long_risk(row: pd.Series, context: dict) -> ScoreResult:
    """Risk of *entering* a long here (chasing). Higher = more dangerous."""
    dist_atr = _row_get(row, "distance_to_vwap_atr")
    near_vah = bool(row.get("distance_to_vah", -1) is not None and _row_get(row, "distance_to_vah") >= -0.0) \
        and not bool(row.get("inside_value_area", True))
    rvol = _row_get(row, "rvol")
    near_hvn = bool(row.get("near_hvn", False))
    breadth_q = _ctx(context, "breadth_quality", default=0.5)
    vix_rising = bool(_ctx(context, "vix_rising", default=False))
    risk_on = _ctx(context, "risk_on_proxy", default=0.0)
    tech_lead = _ctx(context, "tech_leadership", default=0.0)
    dist_oi = _ctx(context, "options", "distance_to_max_oi_strike", default=np.nan)

    factors = [
        Factor("extension_above_vwap",
               _saturate(max(dist_atr, 0), 1.5) if dist_atr > 0 else 0.0, 0.22,
               f"precio +{dist_atr:.1f} ATR sobre VWAP (extendido)" if dist_atr > 0.8 else ""),
        Factor("near_resistance_vah_hvn", 0.8 if (near_vah or near_hvn) else 0.0, 0.15,
               "llega a zona VAH/HVN (resistencia de perfil)" if (near_vah or near_hvn) else ""),
        Factor("climactic_rvol", _saturate(max(rvol - 1.0, 0), 1.5) if dist_atr > 0 else 0.0, 0.15,
               f"RVOL climático {rvol:.1f} tras subida" if rvol > 1.8 and dist_atr > 0 else ""),
        Factor("weak_breadth", 1.0 - breadth_q, 0.14,
               "breadth débil (RSP/SPY no acompaña)" if breadth_q < 0.45 else ""),
        Factor("vix_rising", 1.0 if vix_rising else 0.0, 0.12,
               "VIX subiendo mientras el precio sube" if vix_rising else ""),
        Factor("credit_weak", 1.0 if risk_on < 0 else 0.0, 0.10,
               "HYG/TLT débil (apetito de riesgo flojo)" if risk_on < 0 else ""),
        Factor("tech_weak", 1.0 if tech_lead < 0 else 0.0, 0.07,
               "SMH/QQQ no confirma el liderazgo tech" if tech_lead < 0 else ""),
        Factor("near_oi_strike",
               _saturate(1.0, 1.0) if (not np.isnan(dist_oi) and abs(dist_oi) < 1.0) else 0.0, 0.05,
               "muy cerca de strike de OI máxima" if (not np.isnan(dist_oi) and abs(dist_oi) < 1.0) else ""),
    ]
    return _finalize("Long_Risk", factors)


def score_long_opportunity(row: pd.Series, context: dict) -> ScoreResult:
    """Attractiveness of entering a long (constructive pullback)."""
    dist_atr = _row_get(row, "distance_to_vwap_atr")
    near_val = bool(_row_get(row, "distance_to_val") <= 0.0) or bool(row.get("near_hvn", False))
    rvol = _row_get(row, "rvol")
    breadth_q = _ctx(context, "breadth_quality", default=0.5)
    tech_lead = _ctx(context, "tech_leadership", default=0.0)
    vix_rising = bool(_ctx(context, "vix_rising", default=False))

    # Constructive: small negative-to-flat distance to VWAP (reclaim), healthy RVOL.
    reclaim = 1.0 - _saturate(dist_atr, 1.0) if -1.0 <= dist_atr <= 0.3 else 0.0
    factors = [
        Factor("vwap_reclaim_or_pullback", reclaim, 0.22,
               "pullback/recuperación de VWAP (zona de entrada)" if reclaim > 0.4 else ""),
        Factor("near_support_val_hvn", 0.8 if near_val else 0.0, 0.18,
               "cerca de VAL/HVN como soporte" if near_val else ""),
        Factor("healthy_rvol", 1.0 - abs(_saturate(rvol - 1.0, 1.0) - 0.3) if not np.isnan(rvol) else 0.0,
               0.15, f"RVOL sano {rvol:.1f} (participación sin clímax)" if 0.8 <= rvol <= 2.0 else ""),
        Factor("breadth_confirms", breadth_q, 0.16,
               "RSP/SPY acompaña (breadth sano)" if breadth_q > 0.55 else ""),
        Factor("tech_confirms", 1.0 if tech_lead > 0 else 0.0, 0.14,
               "SMH/QQQ acompaña" if tech_lead > 0 else ""),
        Factor("vix_calm", 1.0 if not vix_rising else 0.0, 0.15,
               "VIX estable o bajando" if not vix_rising else ""),
    ]
    return _finalize("Long_Opportunity", factors)


def score_short_risk(row: pd.Series, context: dict) -> ScoreResult:
    """Risk of *entering* a short here (selling into support)."""
    dist_atr = _row_get(row, "distance_to_vwap_atr")
    near_val = bool(_row_get(row, "distance_to_val") <= 0.0) or bool(row.get("near_hvn", False))
    rvol = _row_get(row, "rvol")
    vix_rising = bool(_ctx(context, "vix_rising", default=False))
    risk_on = _ctx(context, "risk_on_proxy", default=0.0)

    factors = [
        Factor("near_support", 0.8 if near_val else 0.0, 0.24,
               "cerca de soporte VAL/HVN (peligroso para cortos)" if near_val else ""),
        Factor("over_extended_below_vwap",
               _saturate(max(-dist_atr, 0), 1.5) if dist_atr < 0 else 0.0, 0.22,
               f"precio {dist_atr:.1f} ATR bajo VWAP (sobre-extendido a la baja)" if dist_atr < -1.2 else ""),
        Factor("climactic_selling", _saturate(max(rvol - 1.0, 0), 1.5) if dist_atr < 0 else 0.0, 0.18,
               f"volumen vendedor climático RVOL {rvol:.1f}" if rvol > 1.8 and dist_atr < 0 else ""),
        Factor("vix_stalling", 1.0 if not vix_rising else 0.0, 0.18,
               "VIX deja de subir (posible suelo)" if not vix_rising else ""),
        Factor("credit_stabilizing", 1.0 if risk_on >= 0 else 0.0, 0.18,
               "HYG/TLT estabilizándose" if risk_on >= 0 else ""),
    ]
    return _finalize("Short_Risk", factors)


def score_short_opportunity(row: pd.Series, context: dict) -> ScoreResult:
    """Attractiveness of entering a short (rejection / breakdown)."""
    dist_to_vah = _row_get(row, "distance_to_vah")
    near_hvn = bool(row.get("near_hvn", False))
    dist_atr = _row_get(row, "distance_to_vwap_atr")
    rvol = _row_get(row, "rvol")
    near_lvn = bool(row.get("near_lvn", False))
    breadth_q = _ctx(context, "breadth_quality", default=0.5)
    vix_rising = bool(_ctx(context, "vix_rising", default=False))
    tech_lead = _ctx(context, "tech_leadership", default=0.0)

    rejection = 0.8 if (abs(dist_to_vah) < (_row_get(row, "atr") or 1) and near_hvn) else 0.0
    lost_vwap = _saturate(max(-dist_atr, 0), 1.0) if dist_atr < 0 else 0.0
    factors = [
        Factor("rejection_at_vah_hvn", rejection, 0.20,
               "rechazo en VAH/HVN/resistencia" if rejection > 0 else ""),
        Factor("lost_vwap", lost_vwap, 0.18,
               "pérdida de VWAP" if dist_atr < -0.2 else ""),
        Factor("rising_rvol_in_decline", _saturate(max(rvol - 1.0, 0), 1.2) if dist_atr < 0 else 0.0,
               0.16, f"RVOL creciente en la caída ({rvol:.1f})" if rvol > 1.3 and dist_atr < 0 else ""),
        Factor("breadth_deteriorating", 1.0 - breadth_q, 0.16,
               "breadth deteriorándose" if breadth_q < 0.45 else ""),
        Factor("vix_rising", 1.0 if vix_rising else 0.0, 0.14,
               "VIX subiendo" if vix_rising else ""),
        Factor("tech_weak", 1.0 if tech_lead < 0 else 0.0, 0.08,
               "SMH/QQQ débil" if tech_lead < 0 else ""),
        Factor("break_toward_lvn", 0.7 if near_lvn else 0.0, 0.08,
               "ruptura hacia zona LVN (vacío de volumen)" if near_lvn else ""),
    ]
    return _finalize("Short_Opportunity", factors)


def score_exit_long_risk(row: pd.Series, context: dict) -> ScoreResult:
    """Risk that an existing long should be trimmed/exited."""
    dist_atr = _row_get(row, "distance_to_vwap_atr")
    near_vah = bool(row.get("near_hvn", False)) or (_row_get(row, "distance_to_vah") >= 0)
    rvol = _row_get(row, "rvol")
    rejection = _detect_rejection_candle(row, bullish=False)
    breadth_q = _ctx(context, "breadth_quality", default=0.5)
    vix_rising = bool(_ctx(context, "vix_rising", default=False))

    factors = [
        Factor("extreme_distance_above_vwap",
               _saturate(max(dist_atr, 0), 1.2) if dist_atr > 0 else 0.0, 0.26,
               f"distancia extrema +{dist_atr:.1f} ATR sobre VWAP" if dist_atr > 1.5 else ""),
        Factor("arrived_at_vah_hvn", 0.8 if near_vah else 0.0, 0.18,
               "llegada a VAH/HVN/resistencia" if near_vah else ""),
        Factor("climactic_rvol", _saturate(max(rvol - 1.0, 0), 1.5), 0.16,
               f"RVOL climático {rvol:.1f}" if rvol > 1.8 else ""),
        Factor("rejection_candle", rejection, 0.18,
               "vela de rechazo bajista" if rejection > 0.4 else ""),
        Factor("breadth_divergence", 1.0 - breadth_q, 0.12,
               "breadth divergente (no confirma la subida)" if breadth_q < 0.45 else ""),
        Factor("vix_not_confirming", 1.0 if vix_rising else 0.0, 0.10,
               "VIX no confirma (sube con el precio)" if vix_rising else ""),
    ]
    return _finalize("Exit_Long_Risk", factors)


def score_exit_short_risk(row: pd.Series, context: dict) -> ScoreResult:
    """Risk that an existing short should be covered."""
    dist_atr = _row_get(row, "distance_to_vwap_atr")
    near_val = bool(row.get("near_hvn", False)) or (_row_get(row, "distance_to_val") <= 0)
    rvol = _row_get(row, "rvol")
    rejection = _detect_rejection_candle(row, bullish=True)
    vix_rising = bool(_ctx(context, "vix_rising", default=False))

    factors = [
        Factor("extreme_distance_below_vwap",
               _saturate(max(-dist_atr, 0), 1.2) if dist_atr < 0 else 0.0, 0.28,
               f"distancia extrema {dist_atr:.1f} ATR bajo VWAP" if dist_atr < -1.5 else ""),
        Factor("arrived_at_val_hvn", 0.8 if near_val else 0.0, 0.20,
               "llegada a VAL/HVN como soporte" if near_val else ""),
        Factor("climactic_selling", _saturate(max(rvol - 1.0, 0), 1.5), 0.18,
               f"RVOL vendedor climático {rvol:.1f}" if rvol > 1.8 else ""),
        Factor("bullish_rejection_candle", rejection, 0.18,
               "vela de rechazo alcista" if rejection > 0.4 else ""),
        Factor("vix_stalling", 1.0 if not vix_rising else 0.0, 0.16,
               "VIX deja de subir" if not vix_rising else ""),
    ]
    return _finalize("Exit_Short_Risk", factors)


def score_breakout_quality(row: pd.Series, context: dict) -> ScoreResult:
    """Quality of a breakout (higher = cleaner, more sustainable)."""
    inside_va = bool(row.get("inside_value_area", True))
    rvol = _row_get(row, "rvol")
    dist_atr = _row_get(row, "distance_to_vwap_atr")
    near_hvn = bool(row.get("near_hvn", False))
    breadth_q = _ctx(context, "breadth_quality", default=0.5)
    vix_rising = bool(_ctx(context, "vix_rising", default=False))
    range_break = _row_get(row, "range_breakout", 0.0)

    # A clean breakout closes outside value area with strong (but not insane) RVOL
    # and a sensible distance to VWAP, with breadth confirming and no immediate HVN.
    factors = [
        Factor("range_breakout", _saturate(range_break, 1.0), 0.16,
               "ruptura de rango" if range_break > 0.5 else ""),
        Factor("high_rvol", _saturate(max(rvol - 1.0, 0), 1.5), 0.18,
               f"RVOL alto en la ruptura ({rvol:.1f})" if rvol > 1.5 else ""),
        Factor("closed_outside_value_area", 1.0 if not inside_va else 0.0, 0.16,
               "cierre fuera del value area" if not inside_va else ""),
        Factor("reasonable_distance_to_vwap",
               1.0 - _saturate(max(abs(dist_atr) - 1.0, 0), 1.5), 0.14,
               "distancia razonable a VWAP (no sobre-extendido)" if abs(dist_atr) < 2.0 else ""),
        Factor("breadth_confirms",
               breadth_q if dist_atr >= 0 else (1.0 - breadth_q), 0.16,
               "breadth confirma la dirección" if (breadth_q > 0.55 and dist_atr >= 0) or
               (breadth_q < 0.45 and dist_atr < 0) else ""),
        Factor("vix_confirms",
               (1.0 if (dist_atr >= 0 and not vix_rising) or (dist_atr < 0 and vix_rising) else 0.0),
               0.12, "VIX confirma la dirección" if (dist_atr >= 0 and not vix_rising) or
               (dist_atr < 0 and vix_rising) else ""),
        Factor("no_immediate_hvn", 1.0 if not near_hvn else 0.0, 0.08,
               "sin HVN/strike relevante inmediato delante" if not near_hvn else ""),
    ]
    return _finalize("Breakout_Quality", factors)


def score_mean_reversion_probability(row: pd.Series, context: dict) -> ScoreResult:
    """Relative probability that price reverts toward VWAP/value."""
    dist_atr = _row_get(row, "distance_to_vwap_atr")
    dist_band = _row_get(row, "distance_to_vwap_band")  # volume-weighted σ units
    rvol = _row_get(row, "rvol")
    near_node = bool(row.get("near_hvn", False)) or (not bool(row.get("inside_value_area", True)))
    breadth_q = _ctx(context, "breadth_quality", default=0.5)
    vix_rising = bool(_ctx(context, "vix_rising", default=False))

    # No breadth confirmation in the direction of the move raises reversion odds.
    breadth_disagrees = (1.0 - breadth_q) if dist_atr > 0 else breadth_q
    vix_disagrees = 1.0 if (dist_atr > 0 and vix_rising) or (dist_atr < 0 and not vix_rising) else 0.0
    # Stretch beyond the volume-weighted VWAP bands is a strong reversion tell.
    band_stretch = _saturate(abs(dist_band), 1.5) if not np.isnan(dist_band) else 0.0
    factors = [
        Factor("extreme_distance_to_vwap", _saturate(abs(dist_atr), 1.2), 0.24,
               f"distancia extrema a VWAP ({dist_atr:.1f} ATR)" if abs(dist_atr) > 1.5 else ""),
        Factor("beyond_vwap_bands", band_stretch, 0.16,
               f"precio fuera de las bandas VWAP ({dist_band:+.1f}σ)" if abs(dist_band) > 2.0 else ""),
        Factor("climactic_rvol", _saturate(max(rvol - 1.0, 0), 1.5), 0.18,
               f"RVOL climático {rvol:.1f}" if rvol > 1.8 else ""),
        Factor("arrived_at_node", 0.8 if near_node else 0.0, 0.16,
               "llegada a VAH/VAL/HVN" if near_node else ""),
        Factor("breadth_no_confirm", breadth_disagrees, 0.14,
               "ausencia de confirmación de breadth" if breadth_disagrees > 0.55 else ""),
        Factor("vix_no_confirm", vix_disagrees, 0.12,
               "VIX no acompaña la dirección del precio" if vix_disagrees > 0 else ""),
    ]
    return _finalize("Mean_Reversion_Probability", factors)


# --------------------------------------------------------------------------- #
# Candle helper + orchestrator
# --------------------------------------------------------------------------- #
def _detect_rejection_candle(row: pd.Series, bullish: bool) -> float:
    """Crude rejection-candle proxy from a single bar's wick geometry.

    bullish=True looks for a long lower wick (rejection of lows); False looks for
    a long upper wick (rejection of highs). Returns [0, 1].
    """
    o = _row_get(row, "open")
    h = _row_get(row, "high")
    l = _row_get(row, "low")
    c = _row_get(row, "close")
    rng = h - l
    if not np.isfinite(rng) or rng <= 0:
        return 0.0
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    if bullish:
        return float(min(max(lower_wick / rng, 0.0), 1.0))
    return float(min(max(upper_wick / rng, 0.0), 1.0))


SCORE_FUNCS: dict[str, Callable[[pd.Series, dict], ScoreResult]] = {
    "Long_Risk": score_long_risk,
    "Long_Opportunity": score_long_opportunity,
    "Short_Risk": score_short_risk,
    "Short_Opportunity": score_short_opportunity,
    "Exit_Long_Risk": score_exit_long_risk,
    "Exit_Short_Risk": score_exit_short_risk,
    "Breakout_Quality": score_breakout_quality,
    "Mean_Reversion_Probability": score_mean_reversion_probability,
}


def compute_all_scores(row: pd.Series, context: dict | None = None) -> dict[str, ScoreResult]:
    """Compute every score for a single feature row.

    ``context`` carries cross-asset state: breadth_quality, risk_on_proxy,
    tech_leadership, vix_rising and an optional ``options`` sub-dict.
    """
    context = context or {}
    results: dict[str, ScoreResult] = {}
    for name, fn in SCORE_FUNCS.items():
        try:
            res = fn(row, context)
        except Exception:
            res = ScoreResult(name=name, score=50.0, label="medio",
                              explanation="score no disponible (datos insuficientes)")
        results[name] = res
    return results


def compute_scores_timeseries(
    features: pd.DataFrame, context: dict | None = None
) -> pd.DataFrame:
    """Compute the numeric scores for every row (for heatmaps / backtests).

    Returns a DataFrame indexed like ``features`` with one column per score.
    Context is treated as a static (latest) cross-asset snapshot for simplicity.
    """
    context = context or {}
    cols = list(SCORE_FUNCS.keys())
    data = {c: np.full(len(features), np.nan) for c in cols}
    for i, (_, row) in enumerate(features.iterrows()):
        for name, fn in SCORE_FUNCS.items():
            try:
                data[name][i] = fn(row, context).score
            except Exception:
                data[name][i] = np.nan
    return pd.DataFrame(data, index=features.index)
