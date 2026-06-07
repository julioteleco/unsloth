"""Herramienta `effectful` real: golpea un sistema externo por HTTP.

Es el patrón del `transfer` de producción descrito en §4: su `fn` registra la
request (con idempotency key derivada de los argumentos) contra un sistema
externo y devuelve el valor confirmado. El veredicto `VERIFIED` del replay
atestigua exactamente esa llamada — nunca se re-ejecuta.

Usa solo stdlib (`urllib`), así que es probable contra cualquier endpoint
HTTP, incluido un servidor local en los tests de integración.
"""
from __future__ import annotations

import json
import urllib.request
from decimal import Decimal

from .tools import Tool, ToolKind, _hash


def crear_tool_http(name: str, url: str, *, timeout: float = 5.0, version: str = "1") -> Tool:
    """Crea una Tool EFFECTFUL que hace POST de los argumentos a `url`.

    El endpoint debe responder JSON `{"confirmed": <numero>}`. La idempotency key
    (hash de los argumentos resueltos) viaja en el cuerpo para que el sistema
    externo deduplique reintentos.
    """

    def fn(a: dict[str, Decimal]) -> Decimal:
        cuerpo = json.dumps({
            "idempotency_key": _hash(a),
            "args": {k: str(v) for k, v in a.items()},
        }).encode()
        req = urllib.request.Request(
            url, data=cuerpo, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            datos = json.loads(resp.read().decode())
        return Decimal(str(datos["confirmed"]))

    return Tool(name, ToolKind.EFFECTFUL, fn, version=version, requires_gate=True)
