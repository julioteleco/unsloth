"""Capa de ejecución — taxonomía y registro tipado de herramientas.

La semántica de replay NO es uniforme: depende del tipo de efecto. Este es
el punto que separa "ejecución auditable" de "promesa falsa de determinismo".
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Callable


# === Taxonomía de herramientas ===========================================
class ToolKind(str, Enum):
    PURE = "pure"              # determinista, sin efectos -> replay RE-EJECUTA
    IDEMPOTENT = "idempotent"  # efecto seguro de repetir con misma key + snapshot
    EFFECTFUL = "effectful"    # efecto NO repetible -> replay solo VERIFICA, nunca re-ejecuta


@dataclass(frozen=True)
class Tool:
    name: str
    kind: ToolKind
    fn: Callable[[dict[str, Decimal]], Decimal]
    version: str = "1"
    requires_gate: bool = False  # efecto que exige aprobación humana explícita


def _canon(obj: object) -> str:
    # Decimal -> str para hash estable (nunca float: dinero en regulado va en Decimal).
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _hash(obj: object) -> str:
    return hashlib.sha256(_canon(obj).encode()).hexdigest()[:16]


# Registro tipado. El planner SOLO puede invocar ops que existan aquí.
REGISTRY: dict[str, Tool] = {
    "sum":      Tool("sum", ToolKind.PURE, lambda a: a["x"] + a["y"]),
    "ratio":    Tool("ratio", ToolKind.PURE, lambda a: a["x"] / a["y"]),  # DivisionByZero si y==0
    "upsert":   Tool("upsert", ToolKind.IDEMPOTENT, lambda a: a["value"]),  # demo: determinista
    "transfer": Tool("transfer", ToolKind.EFFECTFUL, lambda a: a["amount"], requires_gate=True),
}
