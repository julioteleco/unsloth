"""Plataforma de Agentes Empresariales — núcleo del contrato (§4).

Esqueleto runnable del invariante central: la estocasticidad se confina a la
capa de planificación; todo lo de abajo es tipado, auditable y —donde la
naturaleza del efecto lo permite— reproducible. Ver README.md y el documento
de arquitectura para el contexto completo.
"""
from __future__ import annotations

from .audit import verify_chain
from .contracts import (
    Arg,
    AuditEvent,
    Lit,
    Meta,
    Plan,
    Ref,
    Step,
    Value,
)
from .errors import Budget, Escalation, IntegrityError, PolicyError
from .execution import execute
from .policy import authorize
from .reasoning import ReasoningEngine
from .replay import Verdict, replay
from .sealing import seal_head
from .tools import REGISTRY, Tool, ToolKind

__all__ = [
    "Arg",
    "AuditEvent",
    "Budget",
    "Escalation",
    "IntegrityError",
    "Lit",
    "Meta",
    "Plan",
    "PolicyError",
    "REGISTRY",
    "ReasoningEngine",
    "Ref",
    "Step",
    "Tool",
    "ToolKind",
    "Value",
    "Verdict",
    "authorize",
    "execute",
    "replay",
    "seal_head",
    "verify_chain",
]
