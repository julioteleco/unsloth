"""Reasoning Engine real con Claude (la pieza estocástica del sistema).

El planner emite un *draft* en JSON con tipos simples (salida estructurada del
modelo); el runtime confiable lo convierte al `Plan` tipado. CLAVE: el plan
producido por el LLM sigue siendo DATO NO CONFIABLE — pasa por el registro y la
policy igual que cualquier otro, así que un plan malicioso no evade los gates.

Codificación de argumentos en el draft (solo strings, robusto para structured
outputs): "lit:<decimal>" para un literal, "ref:<fuente>" para una referencia a
un dato recuperado o a la salida de un paso previo.

Dependencia opcional:  pip install 'agent-platform-core[llm]'
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from .contracts import Arg, Lit, Plan, Ref, Step
from .tools import REGISTRY

_MODELO_POR_DEFECTO = "claude-opus-4-8"

_SISTEMA = (
    "Eres el motor de planificación de una plataforma de agentes auditable. NO calculas "
    "ni decides montos: solo eliges qué herramientas registradas invocar y con qué "
    "argumentos. Devuelve un plan como lista de pasos. Cada argumento es un string: "
    "'lit:<numero>' para un literal, o 'ref:<fuente>' para referenciar un dato recuperado "
    "o la salida de un paso previo (por su id). Usa SOLO herramientas de esta lista; si una "
    "acción con efecto requiere aprobación, deja que la policy y el gate humano la validen "
    "—no inventes tokens—. Herramientas disponibles: {ops}."
)


class _PasoDraft(BaseModel):
    id: str
    op: str
    args: dict[str, str]
    gate_token: str | None = None


class _PlanDraft(BaseModel):
    goal: str
    steps: list[_PasoDraft]


def _a_arg(valor: str) -> Arg:
    if valor.startswith("ref:"):
        return Ref(source=valor[4:])
    if valor.startswith("lit:"):
        return Lit(value=Decimal(valor[4:]))
    return Lit(value=Decimal(valor))  # por defecto, literal


def _a_paso(d: _PasoDraft) -> Step:
    return Step(id=d.id, op=d.op, args={k: _a_arg(v) for k, v in d.args.items()},
                gate_token=d.gate_token)


class ClaudePlanner:
    """ReasoningEngine sobre la API de Claude (Opus 4.8, salida estructurada)."""

    def __init__(self, client: Any | None = None, model: str = _MODELO_POR_DEFECTO,
                 ops: list[str] | None = None) -> None:
        if client is None:
            import anthropic  # dependencia opcional [llm]
            client = anthropic.Anthropic()
        self._client: Any = client
        self.model_version = model
        self.temperature = 0.0           # metadato de auditoría (Opus 4.8 no acepta el parámetro)
        self.seed: int | None = None
        self._ops = ops if ops is not None else sorted(REGISTRY)

    def _system(self) -> str:
        return _SISTEMA.format(ops=", ".join(self._ops))

    def plan(self, goal: str) -> Plan:
        draft: _PlanDraft = self._client.messages.parse(
            model=self.model_version, max_tokens=4096, thinking={"type": "adaptive"},
            system=self._system(),
            messages=[{"role": "user", "content": f"Objetivo: {goal}"}],
            output_format=_PlanDraft,
        ).parsed_output
        # El draft del LLM se materializa en el Plan tipado; NO se confía: lo valida policy.
        return Plan(goal=draft.goal, steps=[_a_paso(p) for p in draft.steps])

    def repair(self, step: Step, error: str) -> Step:
        draft: _PasoDraft = self._client.messages.parse(
            model=self.model_version, max_tokens=2048, thinking={"type": "adaptive"},
            system=self._system(),
            messages=[{"role": "user", "content":
                       f"El paso '{step.id}' (op={step.op}) falló con: {error}. "
                       "Devuelve un paso corregido con el mismo id."}],
            output_format=_PasoDraft,
        ).parsed_output
        return _a_paso(draft)
