"""Demo de evaluación de ofertas (revisión de licitación, LCSP 9/2017).

Corre con:  make demo-evaluacion   (o  python examples/evaluacion_demo.py).
"""
from __future__ import annotations

from decimal import Decimal

from agent_platform import PolicyError
from agent_platform.tenders import (
    Criterio,
    Oferta,
    PliegoSpec,
    Procedimiento,
    TipoContrato,
    TipoCriterio,
    evaluar,
    proponer_adjudicacion,
)


def _spec() -> PliegoSpec:
    return PliegoSpec(
        objeto="Suministro de equipamiento informático",
        cpv="30200000",
        tipo=TipoContrato.SUMINISTROS,
        procedimiento=Procedimiento.ABIERTO,
        valor_estimado=Decimal("200000"),
        presupuesto_base=Decimal("100000"),
        plazo_ejecucion_meses=12,
        plazo_presentacion_dias=20,
        criterios=[
            Criterio(nombre="Precio", tipo=TipoCriterio.FORMULA, peso=Decimal("60")),
            Criterio(nombre="Calidad", tipo=TipoCriterio.JUICIO_VALOR, peso=Decimal("40")),
        ],
        condiciones_especiales=["Cláusula social art. 202"],
    )


def main() -> None:
    ofertas = [
        Oferta(licitador="Alfa S.L.", importe=Decimal("100000"), puntuacion_tecnica=Decimal("38")),
        Oferta(licitador="Beta S.A.", importe=Decimal("90000"), puntuacion_tecnica=Decimal("25")),
        Oferta(licitador="Gamma S.L.", importe=Decimal("50000"), puntuacion_tecnica=Decimal("30")),
        Oferta(licitador="Delta S.A.", importe=Decimal("95000"), docs_completos=False),
    ]
    res = evaluar(_spec(), ofertas)

    print("=== Clasificación de ofertas (puntuación REPRODUCED) ===")
    for v in res.valoraciones:
        if v.admitida:
            flag = "  ⚠ baja anormal" if v.temeraria else ""
            print(f"  {v.licitador:<12} téc={v.punt_tecnica:>5} eco={v.punt_economica:>6} "
                  f"total={v.total:>6}{flag}")
        else:
            print(f"  {v.licitador:<12} EXCLUIDA — {v.motivo_exclusion}")

    print("\n=== Hallazgos ===")
    for h in res.hallazgos:
        print(f"  [{h.severidad.value.upper()}] {h.articulo}: {h.mensaje}")

    ganador = res.adjudicatario_propuesto
    assert ganador is not None
    print(f"\n=== Mejor oferta calidad-precio: {ganador.licitador} (total {ganador.total}) ===")

    print("\n=== Propuesta de adjudicación: requiere gate firmado de la mesa ===")
    try:
        proponer_adjudicacion(res, gate_token="")
    except PolicyError as exc:
        print(f"  Sin firma -> RECHAZADO: {exc}")
    prop = proponer_adjudicacion(res, gate_token="firma:mesa-contratacion-2026")
    print(f"  Con firma -> propuesta a {prop.adjudicatario} por {prop.importe} "
          f"[{prop.veredicto.value}]")


if __name__ == "__main__":
    main()
