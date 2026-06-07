"""Demo del Redactor de pliegos (LCSP 9/2017) sobre el núcleo.

Corre con:  make demo-licitacion   (o  python examples/licitacion_demo.py).
"""
from __future__ import annotations

from decimal import Decimal

from agent_platform import PolicyError
from agent_platform.tenders import (
    Criterio,
    PliegoSpec,
    Procedimiento,
    TipoContrato,
    TipoCriterio,
    publicar,
    redactar,
    validar,
)


def _pliego(**kw: object) -> PliegoSpec:
    base: dict[str, object] = {
        "objeto": "Servicio de mantenimiento de zonas verdes municipales",
        "cpv": "77310000",
        "tipo": TipoContrato.SERVICIOS,
        "procedimiento": Procedimiento.ABIERTO,
        "sara": False,
        "valor_estimado": Decimal("200000"),
        "presupuesto_base": Decimal("100000"),
        "plazo_ejecucion_meses": 24,
        "plazo_presentacion_dias": 20,
        "criterios": [
            Criterio(nombre="Precio", tipo=TipoCriterio.FORMULA, peso=Decimal("60")),
            Criterio(nombre="Calidad técnica", tipo=TipoCriterio.JUICIO_VALOR, peso=Decimal("40")),
        ],
        "condiciones_especiales": ["Inserción laboral de personas en riesgo de exclusión"],
    }
    base.update(kw)
    return PliegoSpec(**base)  # type: ignore[arg-type]


def main() -> None:
    print("=== 1) Pliego conforme: validación LCSP ===")
    spec = _pliego()
    informe = validar(spec)
    print(f"  conforme = {informe.conforme}")
    for h in informe.avisos:
        print(f"  AVISO [{h.articulo}]: {h.mensaje}")

    print("\n=== 2) Redacción: cifras auditables (REPRODUCED) ===")
    res = redactar(spec)
    for k, v in res.importes.items():
        print(f"  {k}: {v}  -> {res.veredictos[k].value}")

    print("\n=== 3) Publicación con gate firmado del órgano de contratación ===")
    pub = publicar(spec, gate_token="firma:organo-contratacion-2026")
    print(f"  publicado = {pub.publicado}")
    print(f"  veredicto publicar_pliego = {pub.veredictos['publicar_pliego'].value} (effectful)")
    print(f"  eventos en el log (Chain-of-Work) = {len(pub.log)}")

    print("\n=== 4) Pliego NO conforme: publicación rechazada ===")
    malo = _pliego(condiciones_especiales=[])  # incumple art. 202.1
    print(f"  conforme = {validar(malo).conforme}")
    try:
        publicar(malo, gate_token="firma:organo")
        print("  ERROR: no debió publicarse")
    except PolicyError as exc:
        print(f"  RECHAZADO: {str(exc)[:80]}...")

    print("\n=== 5) Publicación sin gate humano: rechazada ===")
    try:
        publicar(spec, gate_token="")
        print("  ERROR: no debió publicarse")
    except PolicyError as exc:
        print(f"  RECHAZADO: {exc}")


if __name__ == "__main__":
    main()
