"""Aplicación del núcleo a licitaciones públicas (LCSP 9/2017).

Worker "Redactor de pliegos": config-as-data del pliego + motor de reglas LCSP
+ cálculo auditable y publicación con gate, sobre el núcleo de agent_platform.
"""
from __future__ import annotations

from .lcsp import validar
from .models import (
    Criterio,
    Hallazgo,
    InformeValidacion,
    PliegoSpec,
    Procedimiento,
    Severidad,
    TipoContrato,
    TipoCriterio,
)
from .worker import ResultadoRedaccion, publicar, redactar

__all__ = [
    "Criterio",
    "Hallazgo",
    "InformeValidacion",
    "PliegoSpec",
    "Procedimiento",
    "ResultadoRedaccion",
    "Severidad",
    "TipoContrato",
    "TipoCriterio",
    "publicar",
    "redactar",
    "validar",
]
