"""Tests del worker Redactor de pliegos (LCSP 9/2017) sobre el núcleo."""
from __future__ import annotations

from decimal import Decimal

import pytest

from agent_platform import PolicyError, Value, Verdict, execute
from agent_platform.contracts import Meta, Plan, Ref, Step
from agent_platform.tenders import (
    Criterio,
    PliegoSpec,
    Procedimiento,
    Severidad,
    TipoContrato,
    TipoCriterio,
    publicar,
    redactar,
    validar,
)


def _spec_conforme(**overrides: object) -> PliegoSpec:
    base: dict[str, object] = {
        "objeto": "Servicio de mantenimiento de zonas verdes",
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
        "condiciones_especiales": ["Contratación de personas en riesgo de exclusión (art. 202)"],
    }
    base.update(overrides)
    return PliegoSpec(**base)  # type: ignore[arg-type]


def test_pliego_conforme_sin_errores() -> None:
    informe = validar(_spec_conforme())
    assert informe.conforme
    assert informe.errores == []


def test_suma_pesos_distinta_de_100_es_error() -> None:
    spec = _spec_conforme(criterios=[
        Criterio(nombre="Precio", tipo=TipoCriterio.FORMULA, peso=Decimal("70")),
        Criterio(nombre="Calidad", tipo=TipoCriterio.JUICIO_VALOR, peso=Decimal("40")),
    ])
    informe = validar(spec)
    assert not informe.conforme
    assert any(h.regla == "suma_criterios_100" for h in informe.errores)


def test_juicio_valor_supera_formula_exige_comite_expertos() -> None:
    spec = _spec_conforme(criterios=[
        Criterio(nombre="Precio", tipo=TipoCriterio.FORMULA, peso=Decimal("40")),
        Criterio(nombre="Calidad", tipo=TipoCriterio.JUICIO_VALOR, peso=Decimal("60")),
    ])
    informe = validar(spec)
    assert informe.conforme  # es AVISO, no ERROR
    assert any(h.regla == "comite_expertos" and h.severidad is Severidad.AVISO
               for h in informe.avisos)


def test_sin_condicion_especial_es_error() -> None:
    informe = validar(_spec_conforme(condiciones_especiales=[]))
    assert not informe.conforme
    assert any(h.regla == "condicion_especial" for h in informe.errores)


def test_garantia_distinta_de_5_avisa() -> None:
    informe = validar(_spec_conforme(garantia_definitiva_pct=Decimal("3")))
    assert informe.conforme  # AVISO
    assert any(h.regla == "garantia_definitiva" for h in informe.avisos)


def test_vec_menor_que_pbl_es_error() -> None:
    informe = validar(_spec_conforme(valor_estimado=Decimal("90000"),
                                     presupuesto_base=Decimal("100000")))
    assert not informe.conforme
    assert any(h.regla == "coherencia_vec_pbl" for h in informe.errores)


def test_plazo_corto_para_abierto_sara_es_error() -> None:
    informe = validar(_spec_conforme(sara=True, plazo_presentacion_dias=20))  # mínimo 35
    assert not informe.conforme
    assert any(h.regla == "plazo_presentacion" for h in informe.errores)


def test_redactar_calcula_cifras_reproducibles() -> None:
    # PBL 100.000 -> garantía 5% = 5.000 ; PBL con IVA 21% = 121.000. Ambas PURE.
    res = redactar(_spec_conforme())
    assert res.importes["garantia_definitiva"] == Decimal("5000.00")
    assert res.importes["pbl_con_iva"] == Decimal("121000.00")
    assert res.veredictos["garantia_definitiva"] is Verdict.REPRODUCED
    assert res.veredictos["pbl_con_iva"] is Verdict.REPRODUCED
    assert not res.publicado


def test_redactar_no_calcula_si_hay_errores_lcsp() -> None:
    res = redactar(_spec_conforme(condiciones_especiales=[]))
    assert not res.informe.conforme
    assert not res.publicado
    assert res.importes == {}
    assert res.log == []


def test_publicar_sin_gate_se_rechaza() -> None:
    with pytest.raises(PolicyError, match="gate"):
        publicar(_spec_conforme(), gate_token="")  # token vacío no autoriza


def test_publicar_con_gate_atestigua_la_publicacion() -> None:
    res = publicar(_spec_conforme(), gate_token="firma:organo-contratacion")
    assert res.publicado
    assert res.veredictos["publicar_pliego"] is Verdict.VERIFIED  # effectful: se atestigua
    assert res.veredictos["garantia_definitiva"] is Verdict.REPRODUCED


def test_publicar_pliego_no_conforme_se_rechaza() -> None:
    with pytest.raises(PolicyError, match="errores LCSP"):
        publicar(_spec_conforme(condiciones_especiales=[]), gate_token="firma:organo")


def test_dato_externo_tainted_no_dispara_publicacion_sin_gate() -> None:
    # Inyección indirecta: una cifra copiada de una oferta (TAINTED) usada como
    # PBL para publicar. El núcleo bloquea el efecto desde dato tainted sin gate.
    meta = Meta(model_version="t", temperature=0.0, seed=0, prompt_hash="p",
                retrieved_hashes=(), sandbox_version="n/a")
    retrieved = {"cifra_oferta": Value(Decimal("999999"), tainted=True)}
    plan = Plan(goal="x", steps=[
        Step(id="publicar_pliego", op="publicar_pliego", args={"pbl": Ref(source="cifra_oferta")}),
    ])

    class _R:
        model_version = "t"
        temperature = 0.0
        seed: int | None = 0

        def plan(self, goal: str) -> Plan:
            return Plan(goal=goal, steps=[])

        def repair(self, step: Step, error: str) -> Step:
            return step

    with pytest.raises(PolicyError, match="tainted"):
        execute(plan, _R(), meta, retrieved)
