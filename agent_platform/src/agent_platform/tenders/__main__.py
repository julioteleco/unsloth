"""CLI del Redactor de pliegos: valida un PliegoSpec desde un fichero JSON.

Uso:
    python -m agent_platform.tenders validar pliego.json

El JSON debe corresponder al esquema de PliegoSpec (ver docs/licitaciones.md).
Salida: informe de validación LCSP (errores y avisos) y código de salida 0 si
el pliego es conforme, 1 si tiene errores, 2 ante un problema de entrada.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .lcsp import validar
from .models import PliegoSpec


def _validar_fichero(ruta: str) -> int:
    path = Path(ruta)
    if not path.is_file():
        print(f"error: no existe el fichero '{ruta}'", file=sys.stderr)
        return 2
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
        spec = PliegoSpec.model_validate(datos)
    except (json.JSONDecodeError, ValidationError) as exc:
        print(f"error: pliego inválido: {exc}", file=sys.stderr)
        return 2

    informe = validar(spec)
    print(f"Pliego: {spec.objeto}")
    print(f"Conforme: {'SÍ' if informe.conforme else 'NO'}")
    for h in informe.errores:
        print(f"  [ERROR] {h.articulo}: {h.mensaje}")
    for h in informe.avisos:
        print(f"  [AVISO] {h.articulo}: {h.mensaje}")
    return 0 if informe.conforme else 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 2 and args[0] == "validar":
        return _validar_fichero(args[1])
    print("uso: python -m agent_platform.tenders validar <pliego.json>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
