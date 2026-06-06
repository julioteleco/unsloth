#!/usr/bin/env bash
# Bootstrap local install for market-flow-risk-heatmap.
# Usage:  bash install.sh        (Mac/Linux)
# Creates a virtualenv, installs dependencies and runs the test suite.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "==> Using Python: $("$PYTHON_BIN" -V 2>&1)"
if ! "$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null; then
  echo "ERROR: Python 3.11+ is required. Set PYTHON_BIN to a 3.11+ interpreter." >&2
  exit 1
fi

echo "==> Creating virtualenv (.venv)"
"$PYTHON_BIN" -m venv .venv

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Upgrading pip"
pip install --upgrade pip >/dev/null

echo "==> Installing requirements"
pip install -r requirements.txt

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "==> Created .env from .env.example (FRED_API_KEY is optional)"
fi

echo "==> Running test suite"
python -m pytest -q

cat <<'EOF'

============================================================
 Instalación completada.

 Para usar el proyecto (con el venv activado):
   source .venv/bin/activate

 1) Descargar datos reales (necesita internet -> Yahoo Finance):
      python scripts/download_data.py --period 60d --interval 5m

 2) Construir features + diagnóstico de un ticker:
      python scripts/build_features.py --ticker SPY

 3) Lanzar el dashboard (abre http://localhost:8501):
      streamlit run app/streamlit_app.py
============================================================
EOF
