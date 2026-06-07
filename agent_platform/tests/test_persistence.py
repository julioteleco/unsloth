"""Tests de persistencia del Chain-of-Work: round-trip íntegro y append-only."""
from __future__ import annotations

from decimal import Decimal

import pytest

from agent_platform import (
    AuditEvent,
    IntegrityError,
    Lit,
    Meta,
    Plan,
    SqliteEventStore,
    Step,
    Verdict,
    execute,
    replay,
    verify_chain,
)


class _Reasoner:
    model_version = "p-1"
    temperature = 0.0
    seed: int | None = 0

    def plan(self, goal: str) -> Plan:
        return Plan(goal=goal, steps=[])

    def repair(self, step: Step, error: str) -> Step:
        return step


_META = Meta(model_version="p-1", temperature=0.0, seed=0, prompt_hash="p",
             retrieved_hashes=(), sandbox_version="n/a")


def _lit(x: str) -> Lit:
    return Lit(value=Decimal(x))


def _run() -> tuple[list[AuditEvent], str]:
    plan = Plan(goal="demo", steps=[
        Step(id="s1", op="sum", args={"x": _lit("10"), "y": _lit("5")}),
        Step(id="s2", op="ratio", args={"x": _lit("30"), "y": _lit("4")}),
        Step(id="s3", op="transfer", args={"amount": _lit("100")}, gate_token="sig:alice"),
    ])
    _, log, seal = execute(plan, _Reasoner(), _META)
    return log, seal


def test_round_trip_conserva_la_integridad_de_la_cadena() -> None:
    log, seal = _run()
    store = SqliteEventStore()
    store.guardar("run-1", log, seal)
    log2, seal2 = store.cargar("run-1")
    # el sello y todos los eventos sobreviven al volcado durable...
    assert seal2 == seal
    assert [e.event_hash for e in log2] == [e.event_hash for e in log]
    # ...y la cadena recargada sigue verificando y reproduciendo igual
    assert verify_chain(log2, seal2) == {"s1", "s2", "s3"}
    v = replay(log2, seal2)
    assert v["s1"] is Verdict.REPRODUCED
    assert v["s3"] is Verdict.VERIFIED


def test_almacen_es_append_only() -> None:
    log, seal = _run()
    store = SqliteEventStore()
    store.guardar("run-1", log, seal)
    with pytest.raises(IntegrityError, match="append-only"):
        store.guardar("run-1", log, seal)


def test_cargar_run_inexistente_es_error() -> None:
    store = SqliteEventStore()
    with pytest.raises(IntegrityError, match="no encontrado"):
        store.cargar("desconocido")


def test_tamper_en_el_almacen_se_detecta_al_recargar() -> None:
    # Si alguien edita un evento persistido, content_hash deja de casar al recargar.
    log, seal = _run()
    store = SqliteEventStore()
    store.guardar("run-1", log, seal)
    store._con.execute(  # manipulación directa de la fila (simula tamper en disco)
        "UPDATE eventos SET evento = REPLACE(evento, '\"output\":\"100\"', '\"output\":\"999\"') "
        "WHERE run_id = 'run-1' AND idx = 2")
    store._con.commit()
    log2, seal2 = store.cargar("run-1")
    assert "s3" not in verify_chain(log2, seal2)
    assert replay(log2, seal2)["s3"] is Verdict.UNREPLAYABLE
