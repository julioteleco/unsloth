"""Streamlit dashboard for market-flow-risk-heatmap (Phase 0).

Run with::

    streamlit run app/streamlit_app.py

The dashboard is a DIAGNOSTIC tool built on free data (yfinance/FRED/FINRA). It is
not financial advice and does not generate trade signals.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest import run_score_backtest  # noqa: E402
from src.config import load_config  # noqa: E402
from src.data_finra import download_short_sale_volume, short_volume_features  # noqa: E402
from src.explain import explain_current_state  # noqa: E402
from src.labeling import label_triple_barrier  # noqa: E402
from src.pipeline import (  # noqa: E402
    build_ticker_bundle,
    latest_scores,
    scores_timeseries_for_bundle,
)

st.set_page_config(page_title="Market Flow Risk Heatmap", layout="wide")

cfg = load_config()

SCORE_COLORS = {
    "bajo": "#2ecc71",
    "medio": "#f1c40f",
    "alto": "#e67e22",
    "extremo": "#e74c3c",
}


@st.cache_data(show_spinner=True, ttl=cfg.download.cache_ttl_minutes * 60)
def _load_bundle(ticker: str, period: str, interval: str, use_options: bool, nonce: int):
    """Cached bundle builder. ``nonce`` busts the cache on manual refresh."""
    return build_ticker_bundle(
        ticker, period=period, interval=interval, use_options=use_options, force_refresh=bool(nonce)
    )


def price_chart(feats: pd.DataFrame, profile) -> go.Figure:
    fig = go.Figure()
    # Volume-weighted VWAP sigma bands (drawn first so price overlays them).
    if {"vwap_upper_2", "vwap_lower_2"}.issubset(feats.columns):
        fig.add_trace(go.Scatter(x=feats.index, y=feats["vwap_upper_2"], name="+2σ",
                                 line=dict(color="rgba(155,89,182,0.0)"), showlegend=False))
        fig.add_trace(go.Scatter(x=feats.index, y=feats["vwap_lower_2"], name="VWAP ±2σ",
                                 fill="tonexty", fillcolor="rgba(155,89,182,0.10)",
                                 line=dict(color="rgba(155,89,182,0.0)")))
    if {"vwap_upper_1", "vwap_lower_1"}.issubset(feats.columns):
        fig.add_trace(go.Scatter(x=feats.index, y=feats["vwap_upper_1"], name="+1σ",
                                 line=dict(color="rgba(155,89,182,0.0)"), showlegend=False))
        fig.add_trace(go.Scatter(x=feats.index, y=feats["vwap_lower_1"], name="VWAP ±1σ",
                                 fill="tonexty", fillcolor="rgba(155,89,182,0.18)",
                                 line=dict(color="rgba(155,89,182,0.0)")))
    fig.add_trace(go.Scatter(x=feats.index, y=feats["close"], name="Close", line=dict(color="#3498db")))
    if "vwap" in feats.columns:
        fig.add_trace(go.Scatter(x=feats.index, y=feats["vwap"], name="VWAP",
                                 line=dict(color="#9b59b6", dash="dot")))
    for level, color, name in [
        (profile.poc, "#e67e22", "POC"),
        (profile.vah, "#e74c3c", "VAH"),
        (profile.val, "#2ecc71", "VAL"),
    ]:
        if level is not None and np.isfinite(level):
            fig.add_hline(y=level, line=dict(color=color, dash="dash"),
                          annotation_text=name, annotation_position="right")
    for hv in (profile.hvn or [])[:6]:
        fig.add_hline(y=hv, line=dict(color="rgba(230,126,34,0.25)", width=1))
    for lv in (profile.lvn or [])[:6]:
        fig.add_hline(y=lv, line=dict(color="rgba(52,152,219,0.25)", width=1, dash="dot"))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h"), title="Precio + VWAP + Volume Profile")
    return fig


def score_heatmap(scores_ts: pd.DataFrame) -> go.Figure:
    """Temporal heatmap: rows = scores, columns = time, color = 0-100."""
    if scores_ts.empty:
        return go.Figure()
    # Downsample columns for readability if very long.
    ts = scores_ts.tail(150)
    fig = go.Figure(
        data=go.Heatmap(
            z=ts.T.values,
            x=[t.strftime("%m-%d %H:%M") for t in ts.index],
            y=list(ts.columns),
            colorscale="RdYlGn_r",
            zmin=0,
            zmax=100,
            colorbar=dict(title="score"),
        )
    )
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10),
                      title="Heatmap temporal de scores (0-100)")
    return fig


def render_scores(scores: dict) -> None:
    cols = st.columns(4)
    order = [
        "Long_Risk", "Long_Opportunity", "Short_Risk", "Short_Opportunity",
        "Exit_Long_Risk", "Exit_Short_Risk", "Breakout_Quality", "Mean_Reversion_Probability",
    ]
    for i, name in enumerate(order):
        res = scores.get(name)
        if not res:
            continue
        color = SCORE_COLORS.get(res.label, "#bdc3c7")
        with cols[i % 4]:
            st.markdown(
                f"<div style='border-radius:8px;padding:10px;background:{color}22;"
                f"border-left:6px solid {color};margin-bottom:8px'>"
                f"<b>{name.replace('_',' ')}</b><br>"
                f"<span style='font-size:1.6em'>{res.score:.0f}</span> "
                f"<span style='color:{color}'><b>{res.label}</b></span></div>",
                unsafe_allow_html=True,
            )


def main() -> None:
    st.title("📊 Market Flow Risk Heatmap — Fase 0")
    st.caption(
        "Diagnóstico cuantitativo de riesgo de entrada/salida para índices USA con datos "
        "**gratuitos** (yfinance / FRED / FINRA). No es asesoramiento financiero ni una señal."
    )

    # ----------------------------- Sidebar -------------------------------- #
    with st.sidebar:
        st.header("Configuración")
        ticker = st.selectbox("Ticker principal", cfg.universe.primary_tickers, index=0)
        period = st.selectbox("Periodo", ["5d", "10d", "30d", "60d"], index=3)
        interval = st.selectbox("Intervalo", ["5m", "15m", "1h"], index=0)
        use_options = st.checkbox("Opciones lite (SPY/QQQ)", value=True)
        use_finra = st.checkbox("FINRA short-volume (proxy débil)", value=False)
        if "refresh_nonce" not in st.session_state:
            st.session_state.refresh_nonce = 0
        if st.button("🔄 Actualizar datos"):
            st.session_state.refresh_nonce += 1
            st.cache_data.clear()
        st.markdown("---")
        st.caption("Las opciones y FINRA degradan sin romper si fallan.")

    bundle = _load_bundle(ticker, period, interval, use_options, st.session_state.refresh_nonce)

    if bundle.features is None or bundle.features.empty:
        st.error(
            "No se pudieron obtener datos para este ticker/periodo. "
            "yfinance limita el histórico intradía (5m suele ser ~60 días). Prueba otro periodo."
        )
        return

    feats = bundle.features
    scores, row = latest_scores(bundle)
    diag = explain_current_state(row, scores)

    regime = bundle.regime.get("regime", "neutral")
    st.markdown(f"### Régimen actual: `{regime}`  ·  Ticker: `{ticker}`")
    for r in bundle.regime.get("reasons", []):
        st.caption(f"• {r}")
    # Macro context (FRED) shown only when a key is configured.
    macro = bundle.context.get("macro") or {}
    if macro:
        rf = bundle.regime.get("features", {})
        ts10y2y = rf.get("term_spread_10y_2y")
        bits = []
        if ts10y2y is not None and np.isfinite(ts10y2y):
            inv = " (invertida)" if ts10y2y < 0 else ""
            bits.append(f"spread 10y-2y: {ts10y2y:+.2f}%{inv}")
        if "DGS10" in macro:
            bits.append(f"10Y: {macro['DGS10']:.2f}%")
        if bits:
            st.caption("Macro (FRED): " + " · ".join(bits))

    # ----------------------------- Price + heatmap ------------------------ #
    col_a, col_b = st.columns([3, 2])
    with col_a:
        st.plotly_chart(price_chart(feats, bundle.profile), use_container_width=True)
    with col_b:
        scores_ts = scores_timeseries_for_bundle(bundle)
        st.plotly_chart(score_heatmap(scores_ts), use_container_width=True)

    # ----------------------------- Scores --------------------------------- #
    st.subheader("Panel de scores (última barra)")
    render_scores(scores)

    # ----------------------------- Diagnosis ------------------------------ #
    st.subheader("🧭 Diagnóstico automático")
    if diag["no_trade"]:
        st.warning("Zona de posible NO-TRADE / reversión a la media.")
    st.text(diag["summary"])
    st.caption(diag["disclaimer"])

    # ----------------------------- Breadth -------------------------------- #
    st.subheader("Breadth proxy (relative strength)")
    bcols = st.columns(4)
    breadth_keys = ["RSP/SPY", "SMH/QQQ", "IWM/SPY", "HYG/TLT"]
    for i, key in enumerate(breadth_keys):
        snap = bundle.breadth_snap.get(key)
        with bcols[i]:
            if snap:
                trend = snap["ratio_trend"]
                arrow = "🟢↑" if trend > 0 else ("🔴↓" if trend < 0 else "⚪→")
                st.metric(key, f"{snap['ratio_close']:.4f}",
                          f"{snap['ratio_return_3'] * 100:+.2f}% (3b) {arrow}")
            else:
                st.metric(key, "n/d")

    # ----------------------------- Options -------------------------------- #
    if use_options:
        st.subheader("Opciones lite")
        opt = bundle.options_features
        if opt.get("available"):
            ocols = st.columns(4)
            ocols[0].metric("Put/Call vol", f"{opt['put_call_volume_ratio']:.2f}")
            ocols[1].metric("Put/Call OI", f"{opt['put_call_oi_ratio']:.2f}")
            ocols[2].metric("Gamma wall (OI)", f"{opt['approximate_gamma_wall']:.0f}")
            dist = opt.get("distance_to_max_oi_strike")
            ocols[3].metric("Dist. a max OI", f"{dist:+.2f}" if dist is not None and np.isfinite(dist) else "n/d")
            st.caption(opt.get("note", ""))
        else:
            st.info(f"options data unavailable — {opt.get('note', '')}")

    # ----------------------------- FINRA ---------------------------------- #
    if use_finra:
        st.subheader("FINRA short-sale volume (proxy débil, NO short interest)")
        finra = download_short_sale_volume(symbols=[ticker], lookback_days=10)
        sv = short_volume_features(finra, ticker)
        if sv.get("available"):
            fcols = st.columns(3)
            fcols[0].metric("Short vol ratio (últ.)", f"{sv['latest_short_volume_ratio']:.2%}")
            fcols[1].metric("Media", f"{sv['avg_short_volume_ratio']:.2%}")
            trend = sv.get("short_volume_ratio_trend")
            fcols[2].metric("Tendencia", f"{trend:+.2%}" if trend is not None else "n/d")
        else:
            st.info("FINRA short-volume no disponible (opcional, proxy débil).")
        st.caption("Volumen marcado short en facilities de FINRA. NO es short interest ni posicionamiento.")

    # ----------------------------- Last session table -------------------- #
    st.subheader("Tabla última sesión")
    table_cols = [
        "close", "vwap", "rvol", "rvol_zscore", "atr", "distance_to_vwap_atr",
        "distance_to_vwap_band", "inside_value_area",
    ]
    present = [c for c in table_cols if c in feats.columns]
    last_session = feats[feats["session_date"] == feats["session_date"].iloc[-1]] if "session_date" in feats.columns else feats.tail(40)
    show = last_session[present].copy()
    show["regime"] = regime
    st.dataframe(show.tail(40), use_container_width=True)

    # ----------------------------- MFE/MAE backtest ----------------------- #
    st.subheader("Análisis MFE/MAE por buckets de score (sin ejecución)")
    bt_cols = st.columns([2, 1, 1, 1])
    score_name = bt_cols[0].selectbox("Score", list(scores.keys()), index=1)
    upper = bt_cols[1].number_input("Upper ATR", value=cfg.labeling.triple_barrier.upper_atr, step=0.1)
    lower = bt_cols[2].number_input("Lower ATR", value=cfg.labeling.triple_barrier.lower_atr, step=0.1)
    horizon = bt_cols[3].number_input("Horizonte (barras)", value=cfg.labeling.triple_barrier.horizon_bars, step=1)
    labels = label_triple_barrier(feats, upper_atr=upper, lower_atr=lower, horizon_bars=int(horizon))
    scores_ts = scores_timeseries_for_bundle(bundle)
    try:
        table = run_score_backtest(feats, scores_ts, labels, score_name=score_name)
        st.dataframe(table, use_container_width=True)
    except Exception as exc:
        st.info(f"No se pudo calcular el backtest: {exc}")
    st.caption("Análisis estadístico de excursiones. Sin broker, sin ejecución, sin recomendación.")


if __name__ == "__main__":
    main()
