"""Audit / Observability (Chain-of-Work): verificación de la cadena.

Log append-only, hash-encadenado y sellado con ancla externa. Esto es lo que
hace el log inmutable, no solo append-only.
"""
from __future__ import annotations

from .contracts import AuditEvent
from .sealing import seal_head


def verify_chain(log: list[AuditEvent], seal: str) -> set[str]:
    """Devuelve el conjunto de step_id cuya evidencia está íntegra. Un tamper
    in-place rompe content_hash; un tamper consistente recomputado cambia la
    cabeza y por tanto invalida el sello."""
    ok: set[str] = set()
    prev = "GENESIS"
    for e in log:
        if e.prev_hash != prev or e.event_hash != e.content_hash():
            pass  # eslabón roto: este paso no se añade a 'ok'
        else:
            ok.add(e.step_id)
        prev = e.event_hash
    if seal_head(prev) != seal:
        return set()  # ancla externa rota: toda la cadena pudo recomputarse -> nada es de fiar
    return ok
