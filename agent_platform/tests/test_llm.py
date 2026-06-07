"""Tests del adaptador de juicio de valor (LLM) con un motor falso, sin red."""
from __future__ import annotations

from decimal import Decimal

from agent_platform import Verdict
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
from agent_platform.tenders.llm import EvaluadorAnthropic


# --- Cliente Anthropic falso (no toca la red) -----------------------------
class _FakeParsed:
    def __init__(self, ev: EvaluacionTecnica) -> None:
        self.parsed_output = ev


class _FakeMessages:
    def __init__(self, ev: EvaluacionTecnica) -> None:
        self._ev = ev

    def parse(self, **kwargs: object) -> _FakeParsed:
        return _FakeParsed(self._ev)


class _FakeClient:
    def __init__(self, ev: EvaluacionTecnica) -> None:
        self.messages = _FakeMessages(ev)


def test_evaluador_acota_la_puntuacion_al_maximo() -> None:
    fuera_de_rango = EvaluacionTecnica(puntuacion=Decimal("999"), justificacion="x")
    evaluador = EvaluadorAnthropic(client=_FakeClient(fuera_de_rango))
    ev = evaluador.puntuar("Calidad", "memoria...", max_puntos=Decimal("40"))
    assert ev.puntuacion == Decimal("40")


def test_evaluador_acota_puntuacion_negativa_a_cero() -> None:
    negativa = EvaluacionTecnica(puntuacion=Decimal("-5"), justificacion="x")
    evaluador = EvaluadorAnthropic(client=_FakeClient(negativa))
    ev = evaluador.puntuar("Calidad", "memoria...", max_puntos=Decimal("40"))
    assert ev.puntuacion == Decimal("0")


# --- Motor de juicio de valor falso, determinista -------------------------
class _MotorFijo:
    def __init__(self, puntos: dict[str, Decimal]) -> None:
        self._puntos = puntos

    def puntuar(self, criterio: str, memoria: str, max_puntos: Decimal) -> EvaluacionTecnica:
        return EvaluacionTecnica(puntuacion=self._puntos.get(memoria, Decimal("0")),
                                 justificacion=f"valoración de '{memoria[:20]}'")


def _spec() -> PliegoSpec:
    return PliegoSpec(
        objeto="Servicio X", cpv="50000000", tipo=TipoContrato.SERVICIOS,
        procedimiento=Procedimiento.ABIERTO, valor_estimado=Decimal("200000"),
        presupuesto_base=Decimal("100000"), plazo_ejecucion_meses=12, plazo_presentacion_dias=20,
        criterios=[
            Criterio(nombre="Precio", tipo=TipoCriterio.FORMULA, peso=Decimal("60")),
            Criterio(nombre="Calidad", tipo=TipoCriterio.JUICIO_VALOR, peso=Decimal("40")),
        ],
        condiciones_especiales=["Cláusula social art. 202"],
    )


def test_pipeline_llm_puntua_y_alimenta_la_evaluacion() -> None:
    ofertas = [
        Oferta(licitador="A", importe=Decimal("80000"), memoria_tecnica="mem-A"),
        Oferta(licitador="B", importe=Decimal("100000"), memoria_tecnica="mem-B"),
    ]
    motor = _MotorFijo({"mem-A": Decimal("20"), "mem-B": Decimal("40")})
    puntuadas = evaluar_ofertas_con_llm("Calidad", ofertas, motor, max_puntos=Decimal("40"))
    assert {o.licitador: o.puntuacion_tecnica for o in puntuadas} == {
        "A": Decimal("20"), "B": Decimal("40")}

    res = evaluar(_spec(), puntuadas)
    # A: eco=60 + téc=20 = 80 ; B: eco=48 + téc=40 = 88 -> gana B
    assert res.adjudicatario_propuesto is not None
    assert res.adjudicatario_propuesto.licitador == "B"


def test_adjudicacion_desde_juicio_valor_llm_sigue_exigiendo_gate() -> None:
    # Aunque la puntuación venga del LLM, la propuesta de adjudicación deriva de
    # la oferta (tainted) y queda VERIFIED solo con la firma de la mesa.
    ofertas = [Oferta(licitador="A", importe=Decimal("80000"), memoria_tecnica="mem")]
    motor = _MotorFijo({"mem": Decimal("30")})
    puntuadas = evaluar_ofertas_con_llm("Calidad", ofertas, motor, max_puntos=Decimal("40"))
    res = evaluar(_spec(), puntuadas)
    prop = proponer_adjudicacion(res, gate_token="firma:mesa")
    assert prop.adjudicatario == "A"
    assert prop.veredicto is Verdict.VERIFIED
