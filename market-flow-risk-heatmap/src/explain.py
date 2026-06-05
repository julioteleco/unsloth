"""Natural-language explanation of the current market state.

Turns the score objects into a short, plain-Spanish diagnosis covering long entry,
short entry, exit risk and whether we are in a "no-trade" zone. Always framed as a
diagnosis, never as advice.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .scoring import ScoreResult


def _fmt_factors(res: ScoreResult, k: int = 4) -> str:
    reasons = res.top_reasons(k)
    return "; ".join(reasons) if reasons else "sin factores dominantes"


def _annotate_score(res: ScoreResult) -> None:
    """Fill the explanation field of a single score with its top reasons."""
    res.explanation = f"{res.label.upper()} ({res.score:.0f}/100): {_fmt_factors(res)}"


def explain_current_state(features_row: pd.Series, scores: dict[str, ScoreResult]) -> dict:
    """Generate a structured + textual diagnosis of the current bar.

    Returns a dict with per-topic sentences and a combined ``summary`` string.
    """
    for res in scores.values():
        _annotate_score(res)

    long_risk = scores["Long_Risk"]
    long_opp = scores["Long_Opportunity"]
    short_risk = scores["Short_Risk"]
    short_opp = scores["Short_Opportunity"]
    exit_long = scores["Exit_Long_Risk"]
    exit_short = scores["Exit_Short_Risk"]
    mean_rev = scores["Mean_Reversion_Probability"]
    breakout = scores["Breakout_Quality"]

    dist_atr = features_row.get("distance_to_vwap_atr", np.nan)
    rvol = features_row.get("rvol", np.nan)
    dist_txt = f"{dist_atr:+.1f} ATR" if pd.notna(dist_atr) else "n/d"
    rvol_txt = f"{rvol:.1f}" if pd.notna(rvol) else "n/d"

    # Long entry narrative
    if long_risk.score >= 70:
        long_entry = (
            f"Riesgo long {long_risk.label}: el precio está {dist_txt} respecto al VWAP, "
            f"RVOL {rvol_txt}. {_fmt_factors(long_risk)}. Mejor no perseguir largos."
        )
    elif long_opp.score >= 60 and long_risk.score < 50:
        long_entry = (
            f"Entrada long atractiva ({long_opp.label}): {_fmt_factors(long_opp)}."
        )
    else:
        long_entry = (
            f"Largos sin ventaja clara (riesgo {long_risk.score:.0f}, "
            f"oportunidad {long_opp.score:.0f})."
        )

    # Short entry narrative
    if short_risk.score >= 70:
        short_entry = (
            f"Riesgo short {short_risk.label}: {_fmt_factors(short_risk)}. "
            f"Vender aquí es peligroso."
        )
    elif short_opp.score >= 60 and short_risk.score < 50:
        short_entry = f"Entrada short atractiva ({short_opp.label}): {_fmt_factors(short_opp)}."
    else:
        short_entry = (
            f"Cortos sin ventaja clara (riesgo {short_risk.score:.0f}, "
            f"oportunidad {short_opp.score:.0f})."
        )

    # Exit narrative
    exits = []
    if exit_long.score >= 65:
        exits.append(f"Riesgo de salida en largos {exit_long.label}: {_fmt_factors(exit_long, 3)}.")
    if exit_short.score >= 65:
        exits.append(f"Riesgo de salida en cortos {exit_short.label}: {_fmt_factors(exit_short, 3)}.")
    exit_txt = " ".join(exits) if exits else "Sin señales fuertes de salida en este momento."

    # No-trade / mean reversion zone
    no_trade = (
        long_risk.score >= 65 and short_risk.score >= 65
    ) or mean_rev.score >= 75
    if no_trade:
        zone_txt = (
            f"Zona de NO-TRADE / reversión: probabilidad de reversión a la media "
            f"{mean_rev.label} ({mean_rev.score:.0f}). {_fmt_factors(mean_rev, 3)}."
        )
    elif breakout.score >= 65:
        zone_txt = f"Posible breakout de calidad {breakout.label} ({breakout.score:.0f}): {_fmt_factors(breakout, 3)}."
    else:
        zone_txt = "Condiciones de mercado mixtas; sin sesgo estructural dominante."

    summary = "\n".join(
        [
            f"• LARGOS: {long_entry}",
            f"• CORTOS: {short_entry}",
            f"• SALIDAS: {exit_txt}",
            f"• CONTEXTO: {zone_txt}",
        ]
    )

    return {
        "long_entry": long_entry,
        "short_entry": short_entry,
        "exits": exit_txt,
        "zone": zone_txt,
        "no_trade": bool(no_trade),
        "summary": summary,
        "disclaimer": (
            "Diagnóstico cuantitativo con datos gratuitos (yfinance/FRED/FINRA). "
            "No es asesoramiento financiero ni una señal de trading."
        ),
    }
