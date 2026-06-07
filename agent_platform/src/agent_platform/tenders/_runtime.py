"""Runtime compartido del dominio de licitaciones sobre el núcleo.

Registra las herramientas del dominio en el registry tipado del núcleo y expone
el reasoner (sin auto-reparación: los actos jurídicos no se auto-corrigen) y la
metadata por defecto. worker.py (redacción) y evaluacion.py (revisión) lo usan.
"""
from __future__ import annotations

from decimal import Decimal

from ..contracts import Meta, Plan, Step
from ..tools import REGISTRY, Tool, ToolKind


def registrar_herramientas() -> None:
    """Idempotente: registra las ops del dominio si no existen ya."""
    REGISTRY.setdefault(
        "pct", Tool("pct", ToolKind.PURE, lambda a: a["base"] * a["rate"] / Decimal(100)))
    REGISTRY.setdefault(
        "con_iva", Tool("con_iva", ToolKind.PURE,
                        lambda a: a["base"] * (Decimal(1) + a["iva"] / Decimal(100))))
    REGISTRY.setdefault(
        "publicar_pliego",
        Tool("publicar_pliego", ToolKind.EFFECTFUL, lambda a: a["pbl"], requires_gate=True))
    # --- evaluación de ofertas ---
    REGISTRY.setdefault(
        "punt_economica",
        Tool("punt_economica", ToolKind.PURE,
             lambda a: a["peso"] * a["oferta_min"] / a["oferta"]))  # proporcional a la más baja
    REGISTRY.setdefault(
        "punt_total",
        Tool("punt_total", ToolKind.PURE, lambda a: a["tecnica"] + a["economica"]))
    REGISTRY.setdefault(
        "proponer_adjudicacion",
        Tool("proponer_adjudicacion", ToolKind.EFFECTFUL,
             lambda a: a["importe"], requires_gate=True))


registrar_herramientas()

META_DEFECTO = Meta(model_version="tenders-1", temperature=0.0, seed=0,
                    prompt_hash="lcsp", retrieved_hashes=(), sandbox_version="n/a")


class ReasonerNulo:
    """Sin reparación automática: la contratación pública no auto-corrige actos
    jurídicos. Si un paso falla, escala a la persona, no inventa un arreglo."""
    model_version = "tenders-1"
    temperature = 0.0
    seed: int | None = 0

    def plan(self, goal: str) -> Plan:
        return Plan(goal=goal, steps=[])

    def repair(self, step: Step, error: str) -> Step:
        return step  # no-op: re-validado por policy en la siguiente vuelta
