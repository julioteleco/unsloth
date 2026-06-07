"""Worker de evaluación de ofertas (revisión de licitaciones, LCSP 9/2017).

Cubre el flujo de la mesa de contratación:
  1. Admisibilidad (sobre administrativo): documentación y prohibiciones.
  2. Valoración técnica (juicio de valor): input del comité -> se atestigua.
  3. Valoración económica (criterio por fórmula): tool PURE -> REPRODUCED.
  4. Baja anormalmente baja (art. 149): se MARCA, no se excluye sin audiencia.
  5. Clasificación de ofertas por puntuación total.
  6. Propuesta de adjudicación: acto EFFECTFUL con gate firmado de la mesa.

Las ofertas son DATO EXTERNO de los licitadores: entran *tainted*. La cadena de
puntuación deriva de ellas, así que la propuesta de adjudicación (effectful)
hereda la taint y NO puede dispararse sin el gate de la mesa: no se puede
auto-adjudicar a partir de cifras aportadas por un licitador.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from ..contracts import AuditEvent, Lit, Meta, Plan, Ref, Step, Value
from ..errors import PolicyError
from ..execution import execute
from ..replay import Verdict, replay
from ._runtime import META_DEFECTO, ReasonerNulo
from .models import Hallazgo, PliegoSpec, Severidad, TipoCriterio


class Oferta(BaseModel):
    """Oferta de un licitador. Es input externo -> el runtime la trata tainted."""
    licitador: str
    importe: Decimal                          # oferta económica (sin IVA)
    docs_completos: bool = True               # sobre administrativo en regla
    prohibicion_contratar: bool = False       # art. 71 LCSP
    puntuacion_tecnica: Decimal = Decimal(0)  # juicio de valor (input del comité)


@dataclass(frozen=True)
class OfertaValorada:
    licitador: str
    admitida: bool
    motivo_exclusion: str | None
    importe: Decimal
    punt_tecnica: Decimal
    punt_economica: Decimal | None
    total: Decimal | None
    temeraria: bool


@dataclass(frozen=True)
class ResultadoEvaluacion:
    valoraciones: list[OfertaValorada]   # admitidas ordenadas desc por total, luego excluidas
    hallazgos: list[Hallazgo]
    log: list[AuditEvent]
    seal: str
    veredictos: dict[str, Verdict]

    @property
    def adjudicatario_propuesto(self) -> OfertaValorada | None:
        for v in self.valoraciones:
            if v.admitida and v.total is not None:
                return v
        return None


@dataclass(frozen=True)
class PropuestaAdjudicacion:
    adjudicatario: str
    importe: Decimal
    log: list[AuditEvent]
    seal: str
    veredicto: Verdict


def _pesos(spec: PliegoSpec) -> tuple[Decimal, Decimal]:
    peso_eco = Decimal(0)
    peso_tec = Decimal(0)
    for c in spec.criterios:
        if c.tipo is TipoCriterio.FORMULA:
            peso_eco += c.peso
        else:
            peso_tec += c.peso
    return peso_eco, peso_tec


def admisibilidad(oferta: Oferta) -> str | None:
    """Devuelve el motivo de exclusión, o None si la oferta es admisible."""
    if oferta.prohibicion_contratar:
        return "Licitador incurso en prohibición de contratar (art. 71 LCSP)."
    if not oferta.docs_completos:
        return "Documentación del sobre administrativo incompleta."
    return None


def umbral_anormalidad(importes: list[Decimal], umbral_puntos: Decimal) -> Decimal | None:
    """Umbral de presunción de anormalidad (art. 149.2 LCSP): ofertas por debajo
    de la media en más de `umbral_puntos` puntos porcentuales. Es un parámetro
    objetivo CONFIGURABLE que el pliego concreta (RGLCAP art. 85 como referencia)."""
    if not importes:
        return None
    total = Decimal(0)
    for x in importes:
        total += x
    media = total / Decimal(len(importes))
    return media * (Decimal(1) - umbral_puntos / Decimal(100))


def evaluar(spec: PliegoSpec, ofertas: list[Oferta], *,
            umbral_puntos: Decimal = Decimal(10),
            meta: Meta | None = None) -> ResultadoEvaluacion:
    """Evalúa las ofertas: admisibilidad + puntuación auditable + clasificación."""
    hallazgos: list[Hallazgo] = []
    peso_eco, _peso_tec = _pesos(spec)

    admitidas: list[Oferta] = []
    excluidas: list[OfertaValorada] = []
    for of in ofertas:
        motivo = admisibilidad(of)
        if motivo is not None:
            hallazgos.append(Hallazgo(regla="admisibilidad", articulo="arts. 71, 140 LCSP",
                                      severidad=Severidad.AVISO,
                                      mensaje=f"{of.licitador}: excluida. {motivo}"))
            excluidas.append(OfertaValorada(of.licitador, False, motivo, of.importe,
                                            of.puntuacion_tecnica, None, None, False))
        else:
            admitidas.append(of)

    if not admitidas:
        return ResultadoEvaluacion(excluidas, hallazgos, [], "", {})

    importes = [of.importe for of in admitidas]
    oferta_min = min(importes)
    umbral = umbral_anormalidad(importes, umbral_puntos)

    # Las ofertas (y su mínimo, derivado) entran TAINTED: son dato del licitador.
    retrieved: dict[str, Value] = {"of_min": Value(oferta_min, tainted=True)}
    steps: list[Step] = []
    for i, of in enumerate(admitidas):
        retrieved[f"of_{i}"] = Value(of.importe, tainted=True)
        steps.append(Step(id=f"eco_{i}", op="punt_economica",
                          args={"peso": Lit(value=peso_eco),
                                "oferta": Ref(source=f"of_{i}"),
                                "oferta_min": Ref(source="of_min")}))
        steps.append(Step(id=f"total_{i}", op="punt_total",
                          args={"tecnica": Lit(value=of.puntuacion_tecnica),
                                "economica": Ref(source=f"eco_{i}")}))

    plan = Plan(goal=f"Valorar ofertas: {spec.objeto}", steps=steps)
    results, log, seal = execute(plan, ReasonerNulo(), meta or META_DEFECTO, retrieved)
    veredictos = replay(log, seal)

    valoradas: list[OfertaValorada] = []
    for i, of in enumerate(admitidas):
        temeraria = umbral is not None and of.importe < umbral
        if temeraria:
            hallazgos.append(Hallazgo(
                regla="baja_anormal", articulo="art. 149 LCSP",
                severidad=Severidad.AVISO,
                mensaje=(f"{of.licitador}: oferta en presunción de anormalidad ({of.importe}); "
                         "requiere audiencia y justificación antes de excluir (art. 149.4).")))
        valoradas.append(OfertaValorada(
            of.licitador, True, None, of.importe, of.puntuacion_tecnica,
            results[f"eco_{i}"], results[f"total_{i}"], temeraria))

    valoradas.sort(key=lambda v: v.total if v.total is not None else Decimal(0), reverse=True)
    return ResultadoEvaluacion(valoradas + excluidas, hallazgos, log, seal, veredictos)


def proponer_adjudicacion(resultado: ResultadoEvaluacion, gate_token: str,
                          meta: Meta | None = None) -> PropuestaAdjudicacion:
    """Propone la adjudicación a la mejor oferta: acto EFFECTFUL con gate firmado.

    Sin gate -> PolicyError. El importe deriva de la oferta del licitador (tainted),
    así que el núcleo ya exige gate por doble vía (effectful + tainted)."""
    if not gate_token.strip():
        raise PolicyError("proponer_adjudicacion: requiere gate firmado de la mesa (token vacío)")
    ganador = resultado.adjudicatario_propuesto
    if ganador is None:
        raise PolicyError("no hay ofertas admitidas: no procede propuesta de adjudicación")

    retrieved = {"importe_adj": Value(ganador.importe, tainted=True)}
    plan = Plan(goal=f"Proponer adjudicación a {ganador.licitador}", steps=[
        Step(id="proponer_adjudicacion", op="proponer_adjudicacion",
             args={"importe": Ref(source="importe_adj")}, gate_token=gate_token),
    ])
    _, log, seal = execute(plan, ReasonerNulo(), meta or META_DEFECTO, retrieved)
    return PropuestaAdjudicacion(ganador.licitador, ganador.importe, log, seal,
                                 replay(log, seal)["proponer_adjudicacion"])
