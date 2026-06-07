"""Contratos tipados entre capas (datos que cruzan fronteras de confianza).

El Plan es OUTPUT DE UN LLM: dato no confiable. CLAVE del fix v3: el plan NO
declara su propia taint. Un arg es un literal (confiable) o una REFERENCIA a
un valor del contexto (dato recuperado) o a la salida de un paso previo. La
taint la DERIVA código confiable a partir de la procedencia, ignorando lo que
el planner afirme. Un plan inyectado no puede "auto-declararse" no-tainted.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .tools import ToolKind, _hash


class Lit(BaseModel):
    kind: Literal["lit"] = "lit"
    value: Decimal


class Ref(BaseModel):
    kind: Literal["ref"] = "ref"
    source: str  # clave de un dato recuperado, o id de un paso previo


Arg = Annotated[Lit | Ref, Field(discriminator="kind")]


class Step(BaseModel):
    id: str
    op: str
    args: dict[str, Arg]
    gate_token: str | None = None
    # No hay campo 'tainted': la taint es propiedad de la procedencia, computada
    # por el runtime confiable (ver _resolve), nunca tomada del output del LLM.


class Plan(BaseModel):
    goal: str
    steps: list[Step]


@dataclass(frozen=True)
class Value:
    """Valor en el runtime confiable, con su marca de procedencia (taint)."""
    amount: Decimal
    tainted: bool


@dataclass(frozen=True)
class Meta:
    model_version: str
    temperature: float
    seed: int | None
    prompt_hash: str
    retrieved_hashes: tuple[str, ...]
    sandbox_version: str


class AuditEvent(BaseModel):
    # --- qué pasó ---
    step_id: str
    op: str
    kind: ToolKind
    attempt: int
    args: dict[str, Decimal]          # args YA resueltos (literales + refs materializadas)
    args_hash: str
    tainted: bool                     # taint COMPUTADA por el runtime, no declarada por el plan
    output: Decimal | None            # None si el paso falló
    output_hash: str | None           # base del veredicto VERIFIED en ops effectful
    error: str | None
    # --- replay de idempotentes (REPRODUCED solo con key + snapshot, §6) ---
    idempotency_key: str | None
    state_snapshot_hash: str | None
    # --- reproducibilidad del planner (lo que §6 declara obligatorio) ---
    model_version: str
    temperature: float
    seed: int | None
    prompt_hash: str
    retrieved_hashes: list[str]
    # --- versiones de ejecución ---
    tool_version: str
    sandbox_version: str
    # --- tamper-evidence: hash-chain ---
    prev_hash: str
    event_hash: str = ""              # se rellena al sellar el evento

    def content_hash(self) -> str:
        # Hash sobre TODO el contenido + prev_hash, excluyendo event_hash. Cualquier
        # edición in-place (aunque el atacante recomponga output_hash) cambia esto.
        body = self.model_dump(exclude={"event_hash"})
        return _hash(body)
