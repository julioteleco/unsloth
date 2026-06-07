"""Aplicación del núcleo a licitaciones públicas (LCSP 9/2017).

Cubre el ciclo completo:
- Redacción de pliegos: `PliegoSpec` (config-as-data) + `validar` + `redactar` / `publicar`.
- Revisión/evaluación de ofertas: `Oferta` + `evaluar` + `proponer_adjudicacion`.
"""
from __future__ import annotations

from .evaluacion import (
    Oferta,
    OfertaValorada,
    PropuestaAdjudicacion,
    ResultadoEvaluacion,
    admisibilidad,
    evaluar,
    proponer_adjudicacion,
    umbral_anormalidad,
)
from .lcsp import validar
from .llm import (
    EvaluacionTecnica,
    EvaluadorAnthropic,
    MotorJuicioValor,
    evaluar_ofertas_con_llm,
)
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
    "EvaluacionTecnica",
    "EvaluadorAnthropic",
    "Hallazgo",
    "InformeValidacion",
    "MotorJuicioValor",
    "Oferta",
    "OfertaValorada",
    "PliegoSpec",
    "Procedimiento",
    "PropuestaAdjudicacion",
    "ResultadoEvaluacion",
    "ResultadoRedaccion",
    "Severidad",
    "TipoContrato",
    "TipoCriterio",
    "admisibilidad",
    "evaluar",
    "evaluar_ofertas_con_llm",
    "proponer_adjudicacion",
    "publicar",
    "redactar",
    "umbral_anormalidad",
    "validar",
]
