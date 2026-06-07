#!/usr/bin/env bash
# Bootstrap de agent_platform en un equipo nuevo: venv + instalación + verificación.
# Uso:   ./bootstrap.sh            (núcleo + dev, y corre los checks)
#        ./bootstrap.sh full       (además: crypto, llm, postgres, notion)
# Requiere: Python 3.11+. Ejecútalo desde la carpeta agent_platform/.
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
EXTRAS="dev"
if [ "${1:-}" = "full" ]; then
  EXTRAS="dev,crypto,llm,postgres,notion"
fi

echo ">> Python: $("$PY" --version)"
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), "Se requiere Python 3.11+"'

echo ">> Creando entorno virtual en .venv"
"$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo ">> Instalando agent_platform[$EXTRAS]"
python -m pip install --upgrade pip -q
python -m pip install -e ".[$EXTRAS]" -q

echo ">> Verificando (ruff + mypy --strict + pytest)"
make check

echo ">> Smoke test del CLI"
cat > /tmp/_pliego_smoke.json <<'JSON'
{"objeto":"Smoke test","cpv":"50000000","tipo":"servicios","procedimiento":"abierto",
 "sara":false,"valor_estimado":"200000","presupuesto_base":"100000","plazo_ejecucion_meses":12,
 "plazo_presentacion_dias":20,
 "criterios":[{"nombre":"Precio","tipo":"formula","peso":"60"},
              {"nombre":"Calidad","tipo":"juicio_valor","peso":"40"}],
 "condiciones_especiales":["Cláusula social art. 202"]}
JSON
licita validar /tmp/_pliego_smoke.json

cat <<'DONE'

OK — agent_platform instalado y verificado.
Activa el entorno con:  source .venv/bin/activate
Demos:                  make demo-licitacion | demo-evaluacion | demo-persistencia | demo-notion
DONE
