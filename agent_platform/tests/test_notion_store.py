"""Tests de NotionEventStore con un cliente de Notion falso (sin red).

Verifica round-trip (incluido troceado de JSON largo), append-only, y que un
tamper en una fila de Notion se detecta al recargar — la tamper-evidence viaja
con el dato, así que el almacén no necesita ser de confianza.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from agent_platform import (
    AuditEvent,
    IntegrityError,
    Lit,
    Meta,
    NotionEventStore,
    Plan,
    Step,
    Verdict,
    execute,
    replay,
    verify_chain,
)


# --- Cliente de Notion falso (imita el shape del SDK notion-client) -------
class _FakePages:
    def __init__(self, store: list[dict[str, Any]]) -> None:
        self._store = store

    def create(self, parent: object, properties: dict[str, Any]) -> dict[str, Any]:
        pagina = {"properties": properties}
        self._store.append(pagina)
        return pagina


class _FakeDatabases:
    def __init__(self, store: list[dict[str, Any]]) -> None:
        self._store = store

    def query(self, **kwargs: Any) -> dict[str, Any]:
        run = kwargs["filter"]["title"]["equals"]
        res = [p for p in self._store
               if p["properties"]["run"]["title"][0]["text"]["content"] == run]
        return {"results": res, "has_more": False, "next_cursor": None}


class _FakeNotion:
    def __init__(self) -> None:
        self._store: list[dict[str, Any]] = []
        self.pages = _FakePages(self._store)
        self.databases = _FakeDatabases(self._store)


class _Reasoner:
    model_version = "n-1"
    temperature = 0.0
    seed: int | None = 0

    def plan(self, goal: str) -> Plan:
        return Plan(goal=goal, steps=[])

    def repair(self, step: Step, error: str) -> Step:
        return step


_META = Meta(model_version="n-1", temperature=0.0, seed=0, prompt_hash="p",
             retrieved_hashes=(), sandbox_version="n/a")


def _run() -> tuple[list[AuditEvent], str]:
    plan = Plan(goal="demo", steps=[
        Step(id="s1", op="sum", args={"x": Lit(value=Decimal("10")), "y": Lit(value=Decimal("5"))}),
        Step(id="s3", op="transfer", args={"amount": Lit(value=Decimal("100"))},
             gate_token="sig:alice"),
    ])
    _, log, seal = execute(plan, _Reasoner(), _META)
    return log, seal


def test_round_trip_en_notion_conserva_la_cadena() -> None:
    log, seal = _run()
    store = NotionEventStore("db-1", client=_FakeNotion())
    store.guardar("run-1", log, seal)
    log2, seal2 = store.cargar("run-1")
    assert seal2 == seal
    assert [e.event_hash for e in log2] == [e.event_hash for e in log]
    assert verify_chain(log2, seal2) == {"s1", "s3"}
    assert replay(log2, seal2)["s1"] is Verdict.REPRODUCED


def test_notion_es_append_only() -> None:
    log, seal = _run()
    store = NotionEventStore("db-1", client=_FakeNotion())
    store.guardar("run-1", log, seal)
    with pytest.raises(IntegrityError, match="append-only"):
        store.guardar("run-1", log, seal)


def test_cargar_run_inexistente_en_notion_es_error() -> None:
    store = NotionEventStore("db-1", client=_FakeNotion())
    with pytest.raises(IntegrityError, match="no encontrado"):
        store.cargar("desconocido")


def test_tamper_en_fila_de_notion_se_detecta_al_recargar() -> None:
    log, seal = _run()
    fake = _FakeNotion()
    store = NotionEventStore("db-1", client=fake)
    store.guardar("run-1", log, seal)
    # Edita el JSON de un evento directamente en el "almacén" (simula tamper).
    for pagina in fake._store:
        seg = pagina["properties"]["evento"]["rich_text"][0]["text"]
        if '"output":"100"' in seg["content"]:
            seg["content"] = seg["content"].replace('"output":"100"', '"output":"999"')
    log2, seal2 = store.cargar("run-1")
    assert "s3" not in verify_chain(log2, seal2)
    assert replay(log2, seal2)["s3"] is Verdict.UNREPLAYABLE


def test_troceado_de_evento_largo() -> None:
    # Un evento serializado supera el límite de 2000 car. por segmento: debe
    # trocearse al guardar y reconstruirse intacto al cargar.
    log, seal = _run()
    inflado = log[0].model_copy(update={"prompt_hash": "x" * 5000})
    inflado = inflado.model_copy(update={"event_hash": inflado.content_hash()})
    store = NotionEventStore("db-1", client=_FakeNotion())
    store.guardar("run-1", [inflado], seal)
    log2, _ = store.cargar("run-1")
    assert log2[0].prompt_hash == "x" * 5000
