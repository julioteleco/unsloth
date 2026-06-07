"""Reasoning Engine: la única pieza estocástica del sistema.

En producción es un LLM detrás del model gateway; aquí se define como Protocol
para que la capa de ejecución dependa del contrato, no de una implementación.
El planner emite un Plan tipado (dato no confiable) y repara pasos fallidos.
"""
from __future__ import annotations

from typing import Protocol

from .contracts import Plan, Step


class ReasoningEngine(Protocol):
    model_version: str
    temperature: float
    seed: int | None

    def plan(self, goal: str) -> Plan: ...
    def repair(self, step: Step, error: str) -> Step: ...
