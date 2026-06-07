"""Motor de reglas LCSP 9/2017 — policy en código, fuera del prompt.

Cada regla es una función pura y tipada que inspecciona un PliegoSpec y emite
hallazgos. Es el análogo de la capa de policy del núcleo: se evalúa sobre el
dato (el pliego) ANTES de cualquier efecto (publicar).

AVISO DE HONESTIDAD: los umbrales (plazos mínimos, % de garantía) son valores
por defecto razonables y CONFIGURABLES. La LCSP se modifica con frecuencia;
verifica los números contra el texto consolidado vigente antes de producción.
Las referencias a artículos orientan, no sustituyen al asesoramiento jurídico.
"""
from __future__ import annotations

from decimal import Decimal

from .models import (
    Hallazgo,
    InformeValidacion,
    PliegoSpec,
    Procedimiento,
    Severidad,
    TipoContrato,
    TipoCriterio,
)

# Plazos mínimos (días) de presentación por (procedimiento, SARA). Defaults
# orientativos (arts. 156, 159, 164 LCSP); ajustables por el órgano de contratación.
PLAZOS_MIN_DIAS: dict[tuple[Procedimiento, bool], int] = {
    (Procedimiento.ABIERTO, True): 35,
    (Procedimiento.ABIERTO, False): 15,
    (Procedimiento.ABIERTO_SIMPLIFICADO, False): 15,
    (Procedimiento.ABIERTO_SUPERSIMPLIFICADO, False): 10,
    (Procedimiento.RESTRINGIDO, True): 30,
    (Procedimiento.RESTRINGIDO, False): 15,
}


def _suma_pesos(spec: PliegoSpec) -> Decimal:
    total = Decimal(0)
    for c in spec.criterios:
        total += c.peso
    return total


def _peso_por_tipo(spec: PliegoSpec, tipo: TipoCriterio) -> Decimal:
    total = Decimal(0)
    for c in spec.criterios:
        if c.tipo is tipo:
            total += c.peso
    return total


def r_objeto_y_cpv(spec: PliegoSpec) -> list[Hallazgo]:
    out: list[Hallazgo] = []
    if not spec.objeto.strip():
        out.append(Hallazgo(regla="objeto_definido", articulo="art. 99 LCSP",
                            severidad=Severidad.ERROR,
                            mensaje="El objeto del contrato no puede estar vacío."))
    cpv = spec.cpv.strip()
    if not cpv or not cpv[:8].isdigit():
        out.append(Hallazgo(regla="cpv_valido", articulo="art. 99 LCSP / Regl. CE 213/2008",
                            severidad=Severidad.ERROR,
                            mensaje=f"CPV ausente o mal formado: '{spec.cpv}'."))
    return out


def r_suma_criterios_100(spec: PliegoSpec) -> list[Hallazgo]:
    total = _suma_pesos(spec)
    if total != Decimal(100):
        return [Hallazgo(regla="suma_criterios_100", articulo="arts. 145-146 LCSP",
                        severidad=Severidad.ERROR,
                        mensaje=f"Los pesos de los criterios suman {total}, deben sumar 100.")]
    return []


def r_juicio_valor_vs_formula(spec: PliegoSpec) -> list[Hallazgo]:
    jdv = _peso_por_tipo(spec, TipoCriterio.JUICIO_VALOR)
    formula = _peso_por_tipo(spec, TipoCriterio.FORMULA)
    if jdv > formula:
        return [Hallazgo(
            regla="comite_expertos", articulo="art. 146.2.a) LCSP",
            severidad=Severidad.AVISO,
            mensaje=(f"Los criterios de juicio de valor ({jdv}) superan a los evaluables "
                     f"por fórmula ({formula}): se exige comité de expertos (≥3 miembros "
                     "no integrados en el órgano proponente) u organismo técnico especializado."))]
    return []


def r_garantia_definitiva(spec: PliegoSpec) -> list[Hallazgo]:
    if spec.garantia_definitiva_pct != Decimal(5):
        return [Hallazgo(
            regla="garantia_definitiva", articulo="art. 107.1 LCSP",
            severidad=Severidad.AVISO,
            mensaje=(f"Garantía definitiva al {spec.garantia_definitiva_pct}%; el general es "
                     "5% del precio (IVA excluido). Requiere justificación en el expediente."))]
    return []


def r_coherencia_vec_pbl(spec: PliegoSpec) -> list[Hallazgo]:
    if spec.valor_estimado < spec.presupuesto_base:
        return [Hallazgo(
            regla="coherencia_vec_pbl", articulo="arts. 100-101 LCSP",
            severidad=Severidad.ERROR,
            mensaje=(f"El valor estimado ({spec.valor_estimado}) no puede ser inferior al "
                     f"presupuesto base de licitación sin IVA ({spec.presupuesto_base})."))]
    return []


def r_condicion_especial_ejecucion(spec: PliegoSpec) -> list[Hallazgo]:
    if not spec.condiciones_especiales:
        return [Hallazgo(
            regla="condicion_especial", articulo="art. 202.1 LCSP",
            severidad=Severidad.ERROR,
            mensaje=("Debe establecerse al menos una condición especial de ejecución de tipo "
                     "social, ético, medioambiental o relativo al empleo."))]
    return []


def r_plazo_presentacion(
    spec: PliegoSpec,
    plazos_min: dict[tuple[Procedimiento, bool], int] | None = None,
) -> list[Hallazgo]:
    tabla = plazos_min if plazos_min is not None else PLAZOS_MIN_DIAS
    minimo = tabla.get((spec.procedimiento, spec.sara))
    if minimo is None:
        return [Hallazgo(
            regla="plazo_presentacion", articulo="arts. 156-164 LCSP",
            severidad=Severidad.AVISO,
            mensaje=(f"No hay plazo mínimo configurado para {spec.procedimiento.value} "
                     f"(SARA={spec.sara}); verifícalo manualmente."))]
    if spec.plazo_presentacion_dias < minimo:
        return [Hallazgo(
            regla="plazo_presentacion", articulo="arts. 156-164 LCSP",
            severidad=Severidad.ERROR,
            mensaje=(f"Plazo de presentación de {spec.plazo_presentacion_dias} días < mínimo "
                     f"de {minimo} días para {spec.procedimiento.value} (SARA={spec.sara})."))]
    return []


def r_supersimplificado_solo_servicios_suministros(spec: PliegoSpec) -> list[Hallazgo]:
    # El supersimplificado (art. 159.6) no aplica, p. ej., a contratos de obras de
    # cierta cuantía; aviso orientativo para revisar idoneidad del procedimiento.
    es_supersimplificado = spec.procedimiento is Procedimiento.ABIERTO_SUPERSIMPLIFICADO
    if es_supersimplificado and spec.tipo is TipoContrato.OBRAS:
        return [Hallazgo(
            regla="idoneidad_procedimiento", articulo="art. 159.6 LCSP",
            severidad=Severidad.AVISO,
            mensaje="Revisa la idoneidad del procedimiento supersimplificado para obras.")]
    return []


_REGLAS = (
    r_objeto_y_cpv,
    r_suma_criterios_100,
    r_juicio_valor_vs_formula,
    r_garantia_definitiva,
    r_coherencia_vec_pbl,
    r_condicion_especial_ejecucion,
    r_plazo_presentacion,
    r_supersimplificado_solo_servicios_suministros,
)


def validar(spec: PliegoSpec) -> InformeValidacion:
    """Aplica todas las reglas LCSP y agrega los hallazgos en un informe tipado."""
    hallazgos: list[Hallazgo] = []
    for regla in _REGLAS:
        hallazgos.extend(regla(spec))
    return InformeValidacion(hallazgos=hallazgos)
