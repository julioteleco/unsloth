"""Demo del juicio de valor asistido por LLM (offline, con un motor falso).

Muestra el pipeline completo: el LLM puntúa los criterios de juicio de valor a
partir de la memoria técnica (dato externo), la puntuación alimenta `evaluar`, y
la adjudicación sigue exigiendo la firma de la mesa (VERIFIED).

Aquí se usa un motor FALSO determinista para correr sin clave ni red. En
producción se sustituye por:

    from agent_platform.tenders import EvaluadorAnthropic
    motor = EvaluadorAnthropic()          # usa ANTHROPIC_API_KEY y Claude Opus 4.8

Corre con:  make demo-juicio-valor
"""
from __future__ import annotations

from decimal import Decimal

from agent_platform.tenders import (
    Criterio,
    EvaluacionTecnica,
    Oferta,
    PliegoSpec,
    Procedimiento,
    TipoContrato,
    TipoCriterio,
    evaluar,
    evaluar_ofertas_con_llm,
    proponer_adjudicacion,
)


class _MotorDemo:
    """Motor de juicio de valor falso: puntúa por longitud de la memoria (demo)."""

    def puntuar(self, criterio: str, memoria: str, max_puntos: Decimal) -> EvaluacionTecnica:
        score = min(Decimal(len(memoria)) / Decimal(4), max_puntos)
        return EvaluacionTecnica(puntuacion=score,
                                 justificacion=f"detalle de la memoria: {len(memoria)} car.")


def _spec() -> PliegoSpec:
    return PliegoSpec(
        objeto="Plataforma de cita previa", cpv="72000000", tipo=TipoContrato.SERVICIOS,
        procedimiento=Procedimiento.ABIERTO, valor_estimado=Decimal("200000"),
        presupuesto_base=Decimal("100000"), plazo_ejecucion_meses=24, plazo_presentacion_dias=20,
        criterios=[
            Criterio(nombre="Precio", tipo=TipoCriterio.FORMULA, peso=Decimal("60")),
            Criterio(nombre="Calidad técnica", tipo=TipoCriterio.JUICIO_VALOR, peso=Decimal("40")),
        ],
        condiciones_especiales=["Accesibilidad WCAG y cláusula social (art. 202)"],
    )


def main() -> None:
    ofertas = [
        Oferta(licitador="Alfa", importe=Decimal("90000"),
               memoria_tecnica="Arquitectura, plan de pruebas y soporte detallados. " * 3),
        Oferta(licitador="Beta", importe=Decimal("80000"),
               memoria_tecnica="Propuesta breve."),
    ]
    print("=== Juicio de valor asistido por LLM (motor de demo) ===")
    puntuadas = evaluar_ofertas_con_llm("Calidad técnica", ofertas, _MotorDemo(),
                                        max_puntos=Decimal("40"))
    for o in puntuadas:
        print(f"  {o.licitador}: puntuación técnica propuesta = {o.puntuacion_tecnica}")

    res = evaluar(_spec(), puntuadas)
    print("\n=== Clasificación ===")
    for v in res.valoraciones:
        print(f"  {v.licitador:<6} téc={v.punt_tecnica} eco={v.punt_economica} total={v.total}")

    ganador = res.adjudicatario_propuesto
    assert ganador is not None
    prop = proponer_adjudicacion(res, gate_token="firma:mesa-contratacion")
    print(f"\nPropuesta de adjudicación: {prop.adjudicatario} [{prop.veredicto.value}] "
          "(el juicio de valor lo asume la mesa con su firma)")


if __name__ == "__main__":
    main()
