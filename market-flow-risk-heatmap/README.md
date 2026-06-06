# market-flow-risk-heatmap

**Fase 0** de un dashboard cuantitativo para índices USA que genera un *mapa de
calor de riesgo de entrada/salida* usando **solo datos gratuitos** (yfinance,
FRED, y opcionalmente FINRA). Construido como herramienta de **diagnóstico**, no
como generador de señales mágicas.

> ⚠️ **No es asesoramiento financiero.** No vende señales, no ejecuta órdenes y no
> se conecta a brokers. Es un instrumento de diagnóstico cuantitativo con datos
> públicos y limitados.

---

## ¿Qué hace?

A partir de OHLCV intradía (5m) y diario, más un puñado de proxies macro y de
breadth, calcula para cada barra ocho **scores 0-100** con etiqueta
(`bajo` / `medio` / `alto` / `extremo`) y una **explicación textual** de los 3-6
factores dominantes:

- **Long_Risk** — riesgo de perseguir un largo aquí.
- **Long_Opportunity** — atractivo de entrada larga (pullback/recuperación).
- **Short_Risk** — riesgo de vender en corto aquí.
- **Short_Opportunity** — atractivo de entrada corta (rechazo/ruptura).
- **Exit_Long_Risk** — riesgo de que un largo deba cerrarse.
- **Exit_Short_Risk** — riesgo de que un corto deba cubrirse.
- **Breakout_Quality** — calidad de una ruptura.
- **Mean_Reversion_Probability** — probabilidad relativa de reversión a la media.

Además calcula features de microestructura aproximada:

- **VWAP de sesión** (reinicio diario) + distancia en valor, %, múltiplos de ATR y
  **unidades de σ**. Incluye **bandas VWAP ±1σ/±2σ ponderadas por volumen**
  (desviación típica volumen-ponderada acumulada por sesión).
- **ATR intradía** con **suavizado de Wilder (RMA)** por defecto, o media simple.
- **RVOL por minuto de sesión** — compara el volumen de cada barra con la *mediana
  histórica del mismo minuto de sesión*, no con una media global (respeta la curva
  de volumen en U). Vectorizado, winsorizado y con **z-score log-RVOL**.
- **Volume Profile aproximado** — POC, VAH/VAL (área de valor 70%), HVN/LVN.
- **Breadth proxy gratis** — ratios RSP/SPY, SMH/QQQ, IWM/SPY, HYG/TLT, XLK/SPY, XLF/SPY.
- **Opciones lite** (SPY/QQQ) — put/call ratios, strikes de OI máxima, "gamma wall" proxy.
- **Macro (FRED, opcional)** — term spread 10y-2y, nivel del 10Y, señal de curva
  invertida; alimenta el régimen y el contexto de scoring sin romper si no hay key.
- **Régimen** — bullish/bearish trend, mean_reversion, high_volatility,
  low_quality_rally, risk_off, neutral.

Y para validación, un **labeling triple-barrier** con etiquetas **long y short
simétricas** (barreras espejo), MFE/MAE y un **backtest analítico por buckets de
score** (sin ejecución) que valida cada score contra el outcome correcto
(long vs short).

## ¿Qué NO hace?

- ❌ No usa datos de pago, **OPRA**, CME tick data ni order book real.
- ❌ No ejecuta órdenes ni se conecta a ningún broker.
- ❌ No hace recomendaciones financieras absolutas.
- ❌ No promete aciertos: los scores son diagnósticos, no señales.
- ❌ El "short volume" de FINRA **no** es short interest ni posicionamiento.

## Fuentes de datos (gratuitas)

| Fuente | Uso | Clave API |
|--------|-----|-----------|
| **yfinance** | OHLCV intradía 5m, diario, options chain SPY/QQQ | No |
| **yfinance (vol)** | Estructura VIX: `^VIX`, `^VIX9D`, `^VIX3M`, `^VVIX` | No |
| **yfinance (sectores)** | Set completo XLY/XLP/XLV/XLI/XLU/XLB/XLRE/XLC (rotación) | No |
| **yfinance (contexto)** | `BTC-USD` como proxy de apetito de riesgo 24/7 | No |
| **FRED** | Curva (DGS10/2/3MO, DFF, T10YIE), VIXCLS, dólar (DTWEXBGS), crédito (HY/IG OAS), condiciones financieras (NFCI/ANFCI), liquidez (WALCL/RRP) | `FRED_API_KEY` **opcional** |
| **FINRA** | Short-sale *volume* diario (proxy débil) | No |
| **Calendario** | Estacionalidad derivada localmente (OPEX, quad-witching, fin de mes, ventana de cierre) — **sin red** | No |

Si no hay `FRED_API_KEY`, el sistema funciona **solo con yfinance** sin romperse.
Todas las fuentes degradan de forma independiente: si una falla, el resto sigue.

### Señales derivadas de las fuentes nuevas
- **Estructura VIX**: ratio `VIX/VIX3M` (>1 = backwardation = estrés), spread VIX9D-VIX, VVIX. Alimenta el régimen `high_volatility`.
- **Crédito (FRED)**: HY/IG OAS como medidor de estrés (mejor que el proxy HYG/TLT).
- **Condiciones financieras**: NFCI > 0 = entorno restrictivo (tailwind risk-off).
- **Curva**: spreads 10y-2y y 10y-3m, tasa real 10y, señal de inversión.
- **Rotación sectorial**: ratios XLY/XLP y XLI/XLU (cíclico vs defensivo).
- **Estacionalidad**: flags de OPEX, quad-witching, fin de mes y ventana de cierre.

## Datos: robustez, modo offline y diagnóstico

El sistema está diseñado para que **nunca** se quede sin datos ni se bloquee:

1. **Descarga con reintentos** — yfinance se llama con reintentos + backoff
   exponencial y, si está instalado, una sesión `curl_cffi` que imita un navegador
   (evita errores intermitentes de rate-limit/cookies).
2. **Circuit breaker** — si la red está caída, tras 2 fallos consecutivos deja de
   reintentar en vivo y pasa directo a caché/demo (build offline en ~5s, no ~100s).
3. **Caché local** (parquet) con *fallback a caché obsoleta* si una descarga falla.
4. **Modo demo / offline** — datos sintéticos **reproducibles** para usar el panel
   sin red. Se activa con la casilla del sidebar, con `MFRH_DEMO_MODE=1`, o
   automáticamente como último recurso (`MFRH_DEMO_FALLBACK=1`, por defecto).
5. **Provenance transparente** — el dashboard muestra un banner indicando si los
   datos son reales (`live`/`cache`) o demo, y un desglose por ticker.

```bash
# Diagnóstico: ¿qué fuentes funcionan en esta máquina?
python scripts/check_data.py --ticker SPY --period 5d

# Sembrar datos demo en caché para usar el panel sin red:
python scripts/seed_demo_data.py --period 60d --interval 5m

# Forzar modo demo en cualquier comando / dashboard:
MFRH_DEMO_MODE=1 streamlit run app/streamlit_app.py
```

> Los datos demo son **sintéticos y deterministas**, solo para demostración/offline.
> NO son datos reales de mercado y nunca se presentan como tales.

## Limitaciones importantes

- **yfinance intradía**: el histórico de 5m suele limitarse a ~60 días; los datos
  pueden tener huecos, retrasos o revisiones. Hay caché local y *fallback* a caché
  obsoleta si una descarga falla.
- **FINRA short volume**: es volumen marcado *short* en las facilities de FINRA en
  un día dado. **No** es short interest, no refleja cobertura ni posicionamiento
  neto. Se trata como **proxy débil y ruidoso**.
- **Volume profile**: sin tick data, el volumen de cada vela se reparte de forma
  *uniforme* entre `high` y `low`. Es una aproximación, no un perfil real.
- **Opciones**: snapshot gratuito de yfinance; sin Greeks reales ni OPRA. La
  "gamma wall" es simplemente el strike con mayor OI combinada (proxy de contexto).

## Instalación

### Opción rápida (un comando)

```bash
bash install.sh                 # Mac / Linux
# Windows PowerShell:
powershell -ExecutionPolicy Bypass -File install.ps1
```

El script crea el virtualenv `.venv`, instala dependencias, copia `.env.example`
a `.env` y ejecuta los tests.

### Opción manual

```bash
python -m venv .venv
source .venv/bin/activate   # Mac/Linux  (Windows: .venv\Scripts\activate)
pip install -r requirements.txt

cp .env.example .env        # opcional: añade FRED_API_KEY si la tienes
```

## Ejecución

```bash
# 1. Descargar y cachear datos del universo
python scripts/download_data.py --period 60d --interval 5m
#    extras opcionales:
python scripts/download_data.py --period 60d --interval 5m --with-fred --with-finra --with-daily

# 2. Construir features + scores para un ticker (imprime diagnóstico)
python scripts/build_features.py --ticker SPY

# 3. Backtest analítico por buckets (MFE/MAE, sin ejecución)
python scripts/run_backtest.py --ticker SPY --score Long_Opportunity

# 4. Dashboard interactivo
streamlit run app/streamlit_app.py
```

## El dashboard

- **Sidebar**: ticker principal (SPY/QQQ/IWM/DIA), periodo (5d/10d/30d/60d),
  intervalo, botón *Actualizar datos*, toggles de opciones lite y FINRA.
- **Panel principal**:
  1. Gráfico de precio con Close, VWAP, POC, VAH, VAL y niveles HVN/LVN.
  2. Heatmap temporal de scores (eje X tiempo, eje Y scores, color 0-100).
  3. Panel de los 8 scores con etiqueta y color.
  4. Diagnóstico automático en lenguaje natural (incluye aviso de zona *no-trade*).
  5. Breadth proxy (RSP/SPY, SMH/QQQ, IWM/SPY, HYG/TLT).
  6. Opciones lite y FINRA (si se activan; degradan sin romper).
  7. Tabla de la última sesión (close, vwap, rvol, atr, distancia a VWAP en ATR,
     dentro del área de valor, régimen).
  8. Análisis MFE/MAE por buckets de score.

## Estructura

```
market-flow-risk-heatmap/
├── config/default_config.yaml     # universo, parámetros, rutas
├── data/{raw,processed,features,options_snapshots}/   # caché local (parquet)
├── scripts/                       # download_data, build_features, run_backtest
├── src/
│   ├── config.py                  # carga config (pydantic) + .env
│   ├── data_yfinance.py           # OHLCV + opciones, caché, errores robustos
│   ├── data_fred.py               # FRED (API key opcional)
│   ├── data_finra.py              # short volume proxy (opcional)
│   ├── features_vwap.py           # VWAP de sesión + ATR
│   ├── features_rvol.py           # RVOL por minuto de sesión
│   ├── features_volume_profile.py # POC/VAH/VAL/HVN/LVN
│   ├── features_breadth.py        # ratios relative-strength
│   ├── features_options.py        # put/call, OI, gamma wall proxy
│   ├── features_regime.py         # clasificación de régimen
│   ├── scoring.py                 # 8 scores 0-100 + factores
│   ├── labeling.py                # triple barrier + MFE/MAE
│   ├── backtest.py                # buckets de score (sin ejecución)
│   ├── explain.py                 # diagnóstico textual
│   ├── pipeline.py                # orquestación end-to-end
│   └── utils.py                   # logging, caché, timezone, parquet
├── app/streamlit_app.py
└── tests/                         # vwap, rvol, volume_profile, scoring, labeling
```

## Tests

```bash
python -m pytest
```

Cubren: VWAP exacto en dataset pequeño, RVOL por minuto de sesión (no media
global), coherencia POC/VAH/VAL del volume profile, scores siempre en [0, 100], y
que el labeling triple-barrier **no usa lookahead** (la barra de entrada nunca se
auto-etiqueta).

## Filosofía

La herramienta ayuda a **diagnosticar contexto y riesgo**, no a predecir el futuro.
Prioriza la transparencia: cada score expone sus factores, cada limitación se
declara, y nada se presenta como asesoramiento financiero.
