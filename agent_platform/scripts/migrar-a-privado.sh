#!/usr/bin/env bash
# Extrae agent_platform/ a su PROPIO repositorio privado, conservando el historial
# de esa subcarpeta y dejándola como raíz del nuevo repo.
#
# Uso:
#   agent_platform/scripts/migrar-a-privado.sh <owner/nuevo-repo> [rama]
# Ejemplo:
#   agent_platform/scripts/migrar-a-privado.sh julioteleco/agent-platform
#
# Requisitos en TU equipo:
#   - git  (incluye `git subtree`, sin dependencias extra)
#   - gh   (GitHub CLI) autenticado:  gh auth login
#   - Ejecutar desde la RAÍZ del repo unsloth (donde está la carpeta agent_platform/).
#
# Qué hace:
#   1. git subtree split de agent_platform/  -> rama con esa carpeta como raíz.
#   2. gh repo create <owner/nuevo-repo> --private
#   3. push de la rama extraída a main del repo privado.
#   4. Reescribe en el nuevo repo las URLs/rutas de README e INSTALL (quita la
#      subcarpeta y el #subdirectory). Imprime un aviso para que las revises.
set -euo pipefail

DESTINO="${1:-}"
RAMA_BASE="${2:-main}"
if [ -z "$DESTINO" ]; then
  echo "uso: $0 <owner/nuevo-repo> [rama-base]" >&2
  exit 2
fi
NOMBRE_REPO="${DESTINO##*/}"

command -v gh >/dev/null || { echo "ERROR: falta 'gh' (GitHub CLI). Instálalo y 'gh auth login'." >&2; exit 1; }
git rev-parse --show-toplevel >/dev/null 2>&1 || { echo "ERROR: no es un repo git." >&2; exit 1; }
cd "$(git rev-parse --show-toplevel)"
[ -d agent_platform ] || { echo "ERROR: no existe la carpeta agent_platform/ aquí." >&2; exit 1; }

echo ">> 1/4  Extrayendo agent_platform/ con su historial (git subtree split)"
git branch -D _migracion_tmp >/dev/null 2>&1 || true
git subtree split --prefix=agent_platform -b _migracion_tmp

echo ">> 2/4  Creando repo privado $DESTINO"
gh repo create "$DESTINO" --private

echo ">> 3/4  Subiendo a $DESTINO ($RAMA_BASE)"
URL="https://github.com/${DESTINO}.git"   # gh configura el credential helper para HTTPS
git push "$URL" "_migracion_tmp:${RAMA_BASE}"

echo ">> 4/4  Ajustando URLs/rutas en el nuevo repo (clon temporal)"
TMP="$(mktemp -d)"
git clone -q "$URL" "$TMP/repo"
(
  cd "$TMP/repo"
  for f in README.md INSTALL.md; do
    [ -f "$f" ] || continue
    # repo público fork -> repo privado nuevo (la subcarpeta pasa a ser la raíz)
    sed -i.bak \
      -e "s|julioteleco/unsloth|${DESTINO}|g" \
      -e "s|unsloth/agent_platform|${NOMBRE_REPO}|g" \
      -e "s|#subdirectory=agent_platform||g" \
      "$f"
    rm -f "$f.bak"
  done
  if ! git diff --quiet; then
    git add README.md INSTALL.md
    git -c user.email="setup@local" -c user.name="migracion" commit -q \
      -m "docs: ajustar URLs/rutas tras extraer a repo propio (raíz = paquete)"
    git push -q origin "$RAMA_BASE"
  fi
)
rm -rf "$TMP"
git branch -D _migracion_tmp >/dev/null 2>&1 || true

cat <<DONE

OK — agent_platform vive ahora en un repo PRIVADO: $DESTINO
  Clonar e instalar:   git clone $URL && cd ${NOMBRE_REPO} && ./bootstrap.sh
  Como dependencia:    pip install "agent-platform-core @ git+https://github.com/${DESTINO}.git"

AVISO: revisa README.md/INSTALL.md del nuevo repo por si quedó alguna referencia
a la antigua subcarpeta. El repo público fork puede archivarse o borrarse.
DONE
