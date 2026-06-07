"""Config-as-data del pliego (§2.7): definición tipada y versionable en git.

Un pliego se describe como DATO validado por Pydantic, no como código generado
al vuelo. Estos modelos son la entrada del Redactor de pliegos y la base sobre
la que el motor de reglas LCSP (lcsp.py) emite su informe de validación.
"""
from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class TipoContrato(StrEnum):
    OBRAS = "obras"
    SERVICIOS = "servicios"
    SUMINISTROS = "suministros"


class Procedimiento(StrEnum):
    ABIERTO = "abierto"
    ABIERTO_SIMPLIFICADO = "abierto_simplificado"      # art. 159 LCSP
    ABIERTO_SUPERSIMPLIFICADO = "abierto_supersimplificado"  # art. 159.6 LCSP
    RESTRINGIDO = "restringido"
    NEGOCIADO = "negociado"


class TipoCriterio(StrEnum):
    FORMULA = "formula"            # evaluable mediante fórmulas (automático)
    JUICIO_VALOR = "juicio_valor"  # depende de un juicio de valor (subjetivo)


class Criterio(BaseModel):
    nombre: str
    tipo: TipoCriterio
    peso: Decimal  # puntos asignados al criterio


class PliegoSpec(BaseModel):
    """Especificación de una licitación. Fuente de verdad versionada en git."""
    objeto: str
    cpv: str                                   # código CPV (Reglamento CE 213/2008)
    tipo: TipoContrato
    procedimiento: Procedimiento
    sara: bool = False                         # sujeto a regulación armonizada
    valor_estimado: Decimal                    # VEC (art. 101), sin IVA, con prórrogas/mods
    presupuesto_base: Decimal                  # PBL (art. 100), sin IVA
    iva_pct: Decimal = Decimal("21")
    plazo_ejecucion_meses: int
    plazo_presentacion_dias: int               # días para presentar ofertas
    criterios: list[Criterio]
    garantia_definitiva_pct: Decimal = Decimal("5")  # art. 107.1: 5% del precio
    condiciones_especiales: list[str] = Field(default_factory=list)  # art. 202.1


class Severidad(StrEnum):
    ERROR = "error"    # incumplimiento: bloquea la publicación
    AVISO = "aviso"    # requiere revisión/justificación, no bloquea


class Hallazgo(BaseModel):
    regla: str
    articulo: str        # referencia al articulado de la LCSP
    severidad: Severidad
    mensaje: str


class InformeValidacion(BaseModel):
    hallazgos: list[Hallazgo]

    @property
    def conforme(self) -> bool:
        """True si no hay ningún hallazgo de severidad ERROR."""
        return not any(h.severidad is Severidad.ERROR for h in self.hallazgos)

    @property
    def errores(self) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.severidad is Severidad.ERROR]

    @property
    def avisos(self) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.severidad is Severidad.AVISO]
