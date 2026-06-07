"""Tests del worker de evaluación de ofertas (LCSP 9/2017) sobre el núcleo."""
from __future__ import annotations

from decimal import Decimal

import pytest

from agent_platform import PolicyError, Verdict
from agent_platform.tenders import (
    Criterio,
    Oferta,
    PliegoSpec,
    Procedimiento,
    TipoContrato,
    TipoCriterio,
    admisibilidad,
    evaluar,
    proponer_adjudicacion,
    umbral_anormalidad,
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


def test_admisibilidad_excluye_docs_incompletos() -> None:
    motivo = admisibilidad(Oferta(licitador="A", importe=Decimal("90000"), docs_completos=False))
    assert motivo is not None and "Documentación" in motivo


def test_admisibilidad_excluye_prohibicion_contratar() -> None:
    motivo = admisibilidad(
        Oferta(licitador="A", importe=Decimal("90000"), prohibicion_contratar=True))
    assert motivo is not None and "prohibición" in motivo


def test_admisibilidad_acepta_oferta_correcta() -> None:
    assert admisibilidad(Oferta(licitador="A", importe=Decimal("90000"))) is None


def test_valoracion_economica_es_reproducible() -> None:
    ofertas = [
        Oferta(licitador="A", importe=Decimal("80000"), puntuacion_tecnica=Decimal("30")),
        Oferta(licitador="B", importe=Decimal("100000"), puntuacion_tecnica=Decimal("35")),
    ]
    res = evaluar(_spec(), ofertas)
    for v in res.veredictos.values():
        assert v is Verdict.REPRODUCED  # toda la puntuación es PURE


def test_oferta_mas_barata_obtiene_maximo_economico() -> None:
    # peso económico 60; la más barata obtiene 60 * (min/min) = 60.
    ofertas = [
        Oferta(licitador="A", importe=Decimal("80000"), puntuacion_tecnica=Decimal("0")),
        Oferta(licitador="B", importe=Decimal("100000"), puntuacion_tecnica=Decimal("0")),
    ]
    res = evaluar(_spec(), ofertas)
    a = next(v for v in res.valoraciones if v.licitador == "A")
    assert a.punt_economica == Decimal("60")


def test_ranking_ordena_por_total() -> None:
    # A: barata pero técnica baja; B: cara pero técnica alta. Comprobamos orden.
    ofertas = [
        Oferta(licitador="A", importe=Decimal("80000"), puntuacion_tecnica=Decimal("10")),
        Oferta(licitador="B", importe=Decimal("100000"), puntuacion_tecnica=Decimal("40")),
    ]
    res = evaluar(_spec(), ofertas)
    # A: eco=60, total=70 ; B: eco=60*80000/100000=48, total=88 -> gana B
    assert res.adjudicatario_propuesto is not None
    assert res.adjudicatario_propuesto.licitador == "B"


def test_baja_anormal_se_marca_no_se_excluye() -> None:
    # Una oferta muy por debajo de la media se marca temeraria pero sigue admitida.
    ofertas = [
        Oferta(licitador="A", importe=Decimal("100000"), puntuacion_tecnica=Decimal("20")),
        Oferta(licitador="B", importe=Decimal("98000"), puntuacion_tecnica=Decimal("20")),
        Oferta(licitador="C", importe=Decimal("50000"), puntuacion_tecnica=Decimal("20")),
    ]
    res = evaluar(_spec(), ofertas, umbral_puntos=Decimal("10"))
    c = next(v for v in res.valoraciones if v.licitador == "C")
    assert c.temeraria and c.admitida
    assert any(h.regla == "baja_anormal" for h in res.hallazgos)


def test_umbral_anormalidad_sin_ofertas_es_none() -> None:
    assert umbral_anormalidad([], Decimal("10")) is None


def test_excluidas_no_obtienen_puntuacion() -> None:
    ofertas = [Oferta(licitador="A", importe=Decimal("80000"), docs_completos=False)]
    res = evaluar(_spec(), ofertas)
    assert res.adjudicatario_propuesto is None
    a = next(v for v in res.valoraciones if v.licitador == "A")
    assert not a.admitida and a.total is None


def test_proponer_adjudicacion_sin_gate_se_rechaza() -> None:
    ofertas = [Oferta(licitador="A", importe=Decimal("80000"), puntuacion_tecnica=Decimal("30"))]
    res = evaluar(_spec(), ofertas)
    with pytest.raises(PolicyError, match="gate"):
        proponer_adjudicacion(res, gate_token="")


def test_proponer_adjudicacion_con_gate_es_verified() -> None:
    ofertas = [Oferta(licitador="A", importe=Decimal("80000"), puntuacion_tecnica=Decimal("30"))]
    res = evaluar(_spec(), ofertas)
    prop = proponer_adjudicacion(res, gate_token="firma:mesa-contratacion")
    assert prop.adjudicatario == "A"
    assert prop.veredicto is Verdict.VERIFIED  # effectful: atestiguado, no re-ejecutado


def test_proponer_adjudicacion_sin_admitidas_se_rechaza() -> None:
    ofertas = [Oferta(licitador="A", importe=Decimal("80000"), prohibicion_contratar=True)]
    res = evaluar(_spec(), ofertas)
    with pytest.raises(PolicyError, match="no hay ofertas admitidas"):
        proponer_adjudicacion(res, gate_token="firma:mesa")
