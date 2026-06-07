"""Replay: veredicto tipado por paso según el tipo de efecto.

La distinción que hace honesta la promesa frente a clientes técnicos y
reguladores: *reproducir* y *verificar* no son lo mismo, y cuál obtienes
depende del ToolKind del paso (§6).
"""
from __future__ import annotations

from enum import StrEnum

from .audit import verify_chain
from .contracts import AuditEvent
from .sealing import Sealer
from .tools import REGISTRY, ToolKind, _hash


class Verdict(StrEnum):
    REPRODUCED = "reproduced"      # re-ejecutado, output idéntico (pure / idempotent c/ snapshot)
    VERIFIED = "verified"          # no re-ejecutable; output registrado e íntegro (effectful)
    UNREPLAYABLE = "unreplayable"  # paso fallido, sin evidencia, o cadena rota


def replay(log: list[AuditEvent], seal: str, sealer: Sealer | None = None) -> dict[str, Verdict]:
    intact = verify_chain(log, seal, sealer)
    verdicts: dict[str, Verdict] = {}
    for e in log:
        if e.step_id not in intact or e.error is not None or e.output is None:
            verdicts[e.step_id] = Verdict.UNREPLAYABLE
            continue
        if e.args_hash != _hash(e.args):
            verdicts[e.step_id] = Verdict.UNREPLAYABLE
            continue
        tool = REGISTRY[e.op]
        if tool.kind is ToolKind.PURE:
            verdicts[e.step_id] = (
                Verdict.REPRODUCED if tool.fn(e.args) == e.output else Verdict.UNREPLAYABLE
            )
        elif tool.kind is ToolKind.IDEMPOTENT:
            # REPRODUCED solo con idempotency key + snapshot de estado; si no, VERIFIED.
            if e.idempotency_key is not None and e.state_snapshot_hash is not None:
                verdicts[e.step_id] = (
                    Verdict.REPRODUCED if tool.fn(e.args) == e.output else Verdict.UNREPLAYABLE
                )
            else:
                verdicts[e.step_id] = Verdict.VERIFIED
        else:  # EFFECTFUL: jamás se re-ejecuta; solo se atestigua contra el registro
            verdicts[e.step_id] = (
                Verdict.VERIFIED if e.output_hash == _hash(e.output) else Verdict.UNREPLAYABLE
            )
    return verdicts
