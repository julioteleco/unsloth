"""Tests del planner Claude con un cliente falso (sin red).

Demuestra: el draft del LLM se materializa en un Plan tipado, y ese plan PASA
POR LA MISMA frontera de policy — un plan malicioso del modelo se rechaza.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agent_platform import (
    ClaudePlanner,
    Lit,
    Meta,
    PolicyError,
    Ref,
    Step,
    Value,
    Verdict,
    execute,
    replay,
)
from agent_platform.planner import _PasoDraft, _PlanDraft


class _FakeParsed:
    def __init__(self, salida: object) -> None:
        self.parsed_output = salida


class _FakeMessages:
    def __init__(self, salidas: list[object]) -> None:
        self._salidas = salidas

    def parse(self, **kwargs: object) -> _FakeParsed:
        return _FakeParsed(self._salidas.pop(0))


class _FakeClient:
    def __init__(self, *salidas: object) -> None:
        self.messages = _FakeMessages(list(salidas))


_META = Meta(model_version="claude-opus-4-8", temperature=0.0, seed=None, prompt_hash="p",
             retrieved_hashes=(), sandbox_version="n/a")


def test_planner_materializa_draft_en_plan_tipado_y_ejecuta() -> None:
    draft = _PlanDraft(goal="sumar", steps=[
        _PasoDraft(id="s1", op="sum", args={"x": "lit:10", "y": "lit:5"}),
    ])
    planner = ClaudePlanner(client=_FakeClient(draft))
    plan = planner.plan("sumar 10 y 5")
    assert plan.steps[0].args["x"] == Lit(value=Decimal("10"))
    results, log, seal = execute(plan, planner, _META)
    assert results["s1"] == Decimal("15")
    assert replay(log, seal)["s1"] is Verdict.REPRODUCED


def test_referencias_se_decodifican() -> None:
    draft = _PlanDraft(goal="x", steps=[
        _PasoDraft(id="s1", op="transfer", args={"amount": "ref:doc_amount"}),
    ])
    planner = ClaudePlanner(client=_FakeClient(draft))
    plan = planner.plan("transferir el importe del documento")
    assert plan.steps[0].args["amount"] == Ref(source="doc_amount")


def test_plan_malicioso_del_llm_sigue_pasando_por_policy() -> None:
    # El LLM "planifica" un efecto desde un dato tainted sin gate: la policy lo
    # rechaza igual que cualquier plan. El planner no es una vía de confianza.
    draft = _PlanDraft(goal="x", steps=[
        _PasoDraft(id="s1", op="transfer", args={"amount": "ref:doc_amount"}),  # sin gate
    ])
    planner = ClaudePlanner(client=_FakeClient(draft))
    plan = planner.plan("paga lo que diga el documento")
    retrieved = {"doc_amount": Value(Decimal("5000"), tainted=True)}
    with pytest.raises(PolicyError, match="tainted"):
        execute(plan, planner, _META, retrieved)


def test_repair_devuelve_paso_corregido() -> None:
    fix = _PasoDraft(id="s1", op="ratio", args={"x": "lit:8", "y": "lit:1"})
    planner = ClaudePlanner(client=_FakeClient(fix))
    roto = Step(id="s1", op="ratio",
                args={"x": Lit(value=Decimal("8")), "y": Lit(value=Decimal("0"))})
    paso = planner.repair(roto, "division by zero")
    assert paso.op == "ratio"
    assert paso.args["y"] == Lit(value=Decimal("1"))
