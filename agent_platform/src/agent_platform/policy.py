"""Governance / Policy: resolución de args con DERIVACIÓN de taint + autorización.

Valida el plan ANTES de ejecutar. La taint NO la declara el plan (output del
LLM, mentiría): el runtime la deriva de la procedencia de cada argumento y la
propaga a las salidas. La policy se evalúa en código, fuera del prompt.
"""
from __future__ import annotations

from decimal import Decimal

from .contracts import Lit, Step, Value
from .errors import PolicyError
from .tools import Tool, ToolKind


# === Resolución de args + DERIVACIÓN de taint (runtime confiable) ========
def _resolve(step: Step, values: dict[str, Value]) -> tuple[dict[str, Decimal], bool]:
    resolved: dict[str, Decimal] = {}
    tainted = False
    for name, arg in step.args.items():
        if isinstance(arg, Lit):
            resolved[name] = arg.value           # literal del plan: confiable
        else:
            src = values.get(arg.source)
            if src is None:
                raise PolicyError(f"{step.id}: referencia a fuente desconocida '{arg.source}'")
            resolved[name] = src.amount
            tainted = tainted or src.tainted      # la taint VIAJA con cualquier arg derivado
    return resolved, tainted


# === Policy engine (en código, fuera del prompt) =========================
def authorize(step: Step, tool: Tool, tainted: bool) -> None:
    # Mitigación de prompt injection indirecta: dato no confiable (tainted) no
    # puede disparar un efecto sin gate humano. La taint es la COMPUTADA, no la
    # declarada por el plan -> un plan inyectado no puede evadirla mintiendo.
    if tool.kind is ToolKind.EFFECTFUL and tainted and step.gate_token is None:
        raise PolicyError(f"{step.op}: arg tainted no puede disparar efecto sin gate")
    if tool.requires_gate and step.gate_token is None:
        raise PolicyError(f"{step.op}: requiere gate humano")
