"""Test de integración de una herramienta EFFECTFUL real contra HTTP local.

Levanta un servidor stdlib en localhost, registra una tool que hace POST contra
él, ejecuta un plan y comprueba que: (1) el efecto realmente ocurrió (el servidor
recibió la request con su idempotency key), (2) el output queda registrado, y
(3) el replay lo atestigua como VERIFIED (no lo re-ejecuta).
"""
from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from agent_platform import (
    Lit,
    Meta,
    Plan,
    Step,
    Verdict,
    crear_tool_http,
    execute,
    replay,
)
from agent_platform.tools import REGISTRY


class _Handler(BaseHTTPRequestHandler):
    recibidos: ClassVar[list[dict[str, object]]] = []

    def do_POST(self) -> None:
        n = int(self.headers["Content-Length"])
        cuerpo = json.loads(self.rfile.read(n).decode())
        _Handler.recibidos.append(cuerpo)
        respuesta = json.dumps({"confirmed": cuerpo["args"]["amount"]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(respuesta)

    def log_message(self, *args: object) -> None:
        pass  # silencio en los tests


@pytest.fixture
def servidor() -> Iterator[str]:
    _Handler.recibidos = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    try:
        puerto = httpd.server_address[1]
        yield f"http://127.0.0.1:{puerto}/pago"
    finally:
        httpd.shutdown()


class _Reasoner:
    model_version = "h-1"
    temperature = 0.0
    seed: int | None = 0

    def plan(self, goal: str) -> Plan:
        return Plan(goal=goal, steps=[])

    def repair(self, step: Step, error: str) -> Step:
        return step


_META = Meta(model_version="h-1", temperature=0.0, seed=0, prompt_hash="p",
             retrieved_hashes=(), sandbox_version="n/a")


def test_tool_effectful_real_golpea_el_sistema_externo(servidor: str) -> None:
    REGISTRY["pagar_http"] = crear_tool_http("pagar_http", servidor)
    try:
        plan = Plan(goal="pagar", steps=[
            Step(id="p1", op="pagar_http", args={"amount": Lit(value=Decimal("250"))},
                 gate_token="firma:tesoreria"),
        ])
        results, log, seal = execute(plan, _Reasoner(), _META)

        # (1) el efecto ocurrió de verdad
        assert len(_Handler.recibidos) == 1
        assert _Handler.recibidos[0]["args"] == {"amount": "250"}
        assert _Handler.recibidos[0]["idempotency_key"]  # presente para deduplicar
        # (2) output registrado, (3) atestiguado pero no re-ejecutado
        assert results["p1"] == Decimal("250")
        assert replay(log, seal)["p1"] is Verdict.VERIFIED
    finally:
        del REGISTRY["pagar_http"]


def test_tool_effectful_sin_gate_no_golpea_el_sistema(servidor: str) -> None:
    from agent_platform import PolicyError
    REGISTRY["pagar_http"] = crear_tool_http("pagar_http", servidor)
    try:
        plan = Plan(goal="pagar", steps=[
            Step(id="p1", op="pagar_http", args={"amount": Lit(value=Decimal("250"))}),  # sin gate
        ])
        with pytest.raises(PolicyError, match="gate"):
            execute(plan, _Reasoner(), _META)
        assert _Handler.recibidos == []  # la policy bloqueó ANTES de llamar al exterior
    finally:
        del REGISTRY["pagar_http"]
