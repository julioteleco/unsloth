"""Errores de control y presupuesto de reintentos (governance).

La validación de plan y policy va en excepciones tipadas, NUNCA en `assert`:
`python -O` elimina los asserts y con ellos la frontera de confianza (§11).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import AuditEvent


class PolicyError(Exception):
    pass


class IntegrityError(Exception):
    """La cadena de auditoría no verifica: evidencia rota o manipulada."""


class Escalation(Exception):
    """Presupuesto de reintentos agotado -> handoff a humano, no loop infinito."""

    def __init__(self, step_id: str, log: list[AuditEvent]) -> None:
        super().__init__(f"escalado en {step_id} tras agotar reintentos")
        self.step_id = step_id
        self.log = log


@dataclass
class Budget:
    max_retries: int = 2
    _used: dict[str, int] = field(default_factory=dict)

    def consume(self, step_id: str) -> bool:
        self._used[step_id] = self._used.get(step_id, 0) + 1
        return self._used[step_id] <= self.max_retries + 1  # intento inicial + reintentos

    def used(self, step_id: str) -> int:
        return self._used.get(step_id, 0)
