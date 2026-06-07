"""Redactor de pliegos: aplica el núcleo al flujo de licitación (LCSP 9/2017).

Demuestra las cinco fronteras del núcleo en este dominio:
- Las CIFRAS del pliego (garantía, PBL con IVA) son tools PURE -> el log las
  registra y el replay las marca REPRODUCED: reproducibles y verificables, justo
  lo que defiende una puntuación automática ante un recurso.
- La PUBLICACIÓN del pliego es EFFECTFUL y exige gate firmado del órgano de
  contratación: ningún acto administrativo irreversible sin firma humana.
- Un dato externo (p. ej. una cifra copiada de una oferta) entra TAINTED y no
  puede disparar la publicación sin gate -> contención de inyección indirecta.
- El plan se valida contra LCSP (motor de reglas) ANTES de ejecutar nada.
- El log es hash-encadenado y sellado: expediente tamper-evident.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..contracts import AuditEvent, Lit, Meta, Plan, Ref, Step
from ..errors import PolicyError
from ..execution import execute
from ..replay import Verdict, replay
from ..tools import REGISTRY, Tool, ToolKind
from .lcsp import validar
from .models import InformeValidacion, PliegoSpec


# === Herramientas del dominio: registradas en el registry tipado del núcleo ===
def _registrar_herramientas() -> None:
    REGISTRY.setdefault(
        "pct", Tool("pct", ToolKind.PURE, lambda a: a["base"] * a["rate"] / Decimal(100)))
    REGISTRY.setdefault(
        "con_iva", Tool("con_iva", ToolKind.PURE,
                        lambda a: a["base"] * (Decimal(1) + a["iva"] / Decimal(100))))
    REGISTRY.setdefault(
        "publicar_pliego",
        Tool("publicar_pliego", ToolKind.EFFECTFUL, lambda a: a["pbl"], requires_gate=True))


_registrar_herramientas()

_META = Meta(model_version="tenders-redactor-1", temperature=0.0, seed=0,
             prompt_hash="pliego:lcsp", retrieved_hashes=(), sandbox_version="n/a")


class _ReasonerNulo:
    """Sin reparación automática: la redacción de pliegos no auto-corrige actos
    jurídicos. Si un paso falla, escala a la persona, no inventa un arreglo."""
    model_version = "tenders-redactor-1"
    temperature = 0.0
    seed: int | None = 0

    def plan(self, goal: str) -> Plan:
        return Plan(goal=goal, steps=[])

    def repair(self, step: Step, error: str) -> Step:
        return step  # no-op: re-validado por policy en la siguiente vuelta


@dataclass(frozen=True)
class ResultadoRedaccion:
    informe: InformeValidacion
    publicado: bool
    importes: dict[str, Decimal]          # cifras calculadas (garantía, PBL con IVA)
    log: list[AuditEvent]
    seal: str
    veredictos: dict[str, Verdict]


def _pasos_calculo(spec: PliegoSpec) -> list[Step]:
    return [
        Step(id="garantia_definitiva", op="pct",
             args={"base": Lit(value=spec.presupuesto_base),
                   "rate": Lit(value=spec.garantia_definitiva_pct)}),
        Step(id="pbl_con_iva", op="con_iva",
             args={"base": Lit(value=spec.presupuesto_base),
                   "iva": Lit(value=spec.iva_pct)}),
    ]


def redactar(spec: PliegoSpec, meta: Meta | None = None) -> ResultadoRedaccion:
    """Valida el pliego contra LCSP y calcula sus cifras de forma auditable.

    NO publica: la redacción/validación es separable del acto formal de
    publicación. Si hay errores LCSP, no se calcula ni se ejecuta nada.
    """
    informe = validar(spec)
    if not informe.conforme:
        return ResultadoRedaccion(informe, False, {}, [], "", {})
    plan = Plan(goal=f"Calcular cifras del pliego: {spec.objeto}", steps=_pasos_calculo(spec))
    importes, log, seal = execute(plan, _ReasonerNulo(), meta or _META)
    return ResultadoRedaccion(informe, False, importes, log, seal, replay(log, seal))


def publicar(spec: PliegoSpec, gate_token: str, meta: Meta | None = None) -> ResultadoRedaccion:
    """Publica el pliego: acto EFFECTFUL que exige gate firmado y conformidad LCSP.

    Sin gate -> PolicyError (gate). Pliego no conforme -> PolicyError. El paso
    de publicación queda atestiguado (VERIFIED), nunca re-ejecutado.
    """
    if not gate_token.strip():
        raise PolicyError("publicar_pliego: requiere gate humano firmado (token vacío no autoriza)")
    informe = validar(spec)
    if not informe.conforme:
        raise PolicyError(
            "no se puede publicar un pliego con errores LCSP: "
            + "; ".join(h.mensaje for h in informe.errores))
    pasos = _pasos_calculo(spec)
    pasos.append(Step(id="publicar_pliego", op="publicar_pliego",
                      args={"pbl": Ref(source="pbl_con_iva")}, gate_token=gate_token))
    plan = Plan(goal=f"Publicar pliego: {spec.objeto}", steps=pasos)
    importes, log, seal = execute(plan, _ReasonerNulo(), meta or _META)
    return ResultadoRedaccion(informe, True, importes, log, seal, replay(log, seal))
