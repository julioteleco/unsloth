"""Execution layer: determinista donde puede, auditable siempre.

Recibe pasos tipados y los ejecuta tras pasar por policy. El self-healing es
acotado: cada reparación es output no confiable del LLM y vuelve a pasar por
registro y policy en cada vuelta -> no hay bypass por el camino de repair.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from .contracts import AuditEvent, Meta, Plan, Step, Value
from .errors import Budget, Escalation, PolicyError
from .policy import _resolve, authorize
from .reasoning import ReasoningEngine
from .sealing import seal_head
from .tools import REGISTRY, Tool, ToolKind, _hash


def _event(step: Step, tool: Tool, resolved: dict[str, Decimal], tainted: bool,
           meta: Meta, attempt: int, out: Decimal | None, err: str | None,
           prev_hash: str, values: dict[str, Value]) -> AuditEvent:
    idem = _hash(resolved) if tool.kind is ToolKind.IDEMPOTENT else None
    snap = _hash({k: str(v.amount) for k, v in sorted(values.items())}) \
        if tool.kind is ToolKind.IDEMPOTENT else None
    e = AuditEvent(
        step_id=step.id, op=step.op, kind=tool.kind, attempt=attempt,
        args=resolved, args_hash=_hash(resolved), tainted=tainted,
        output=out, output_hash=_hash(out) if out is not None else None, error=err,
        idempotency_key=idem, state_snapshot_hash=snap,
        model_version=meta.model_version, temperature=meta.temperature, seed=meta.seed,
        prompt_hash=meta.prompt_hash, retrieved_hashes=list(meta.retrieved_hashes),
        tool_version=tool.version, sandbox_version=meta.sandbox_version,
        prev_hash=prev_hash,
    )
    return e.model_copy(update={"event_hash": e.content_hash()})


def _run_step(step: Step, reasoner: ReasoningEngine, meta: Meta,
              values: dict[str, Value], budget: Budget, log: list[AuditEvent],
              prev_hash: str) -> tuple[Value, str]:
    current = step
    while True:
        if not budget.consume(step.id):
            raise Escalation(step.id, log)
        attempt = budget.used(step.id)
        # FIX: la herramienta se re-resuelve y la policy se re-evalúa EN CADA
        # iteración, incluida la del paso reparado. La reparación es output del
        # LLM y por tanto no confiable: no hay bypass por el camino de repair.
        tool = REGISTRY.get(current.op)
        if tool is None:
            raise PolicyError(f"herramienta no registrada: {current.op}")
        resolved, tainted = _resolve(current, values)
        authorize(current, tool, tainted)
        try:
            out = tool.fn(resolved)
        except Exception as exc:  # captura traceback -> self-healing acotado
            log.append(_event(current, tool, resolved, tainted, meta, attempt, None, repr(exc),
                              prev_hash, values))
            prev_hash = log[-1].event_hash
            current = reasoner.repair(current, repr(exc))  # re-validado arriba en la próxima vuelta
            continue
        log.append(_event(current, tool, resolved, tainted, meta, attempt, out, None,
                          prev_hash, values))
        return Value(out, tainted), log[-1].event_hash


def execute(plan: Plan, reasoner: ReasoningEngine, meta: Meta,
            retrieved: Mapping[str, Value] | None = None,
            budget: Budget | None = None) -> tuple[dict[str, Decimal], list[AuditEvent], str]:
    budget = budget or Budget()
    values: dict[str, Value] = dict(retrieved or {})  # datos recuperados entran TAINTED
    results: dict[str, Decimal] = {}
    log: list[AuditEvent] = []
    prev_hash = "GENESIS"
    for step in plan.steps:
        out, prev_hash = _run_step(step, reasoner, meta, values, budget, log, prev_hash)
        values[step.id] = out          # la salida queda disponible (con su taint) para refs
        results[step.id] = out.amount
    return results, log, seal_head(prev_hash)
