# Changelog

## [Unreleased]

### Añadido (persistencia + LLM real)
- **Persistencia del Chain-of-Work** (`agent_platform.persistence`): `EventStore`
  con `SqliteEventStore` (stdlib, testeado, append-only) y `PostgresEventStore`
  (sistema de registro, opcional `[postgres]`). El expediente se recarga y se
  re-verifica (cadena + sello) tras un reinicio.
- **Juicio de valor con LLM real**: `EvaluadorAnthropic` (Claude Opus 4.8, vía
  `messages.parse` con salida estructurada, opcional `[llm]`) implementa
  `MotorJuicioValor`; `evaluar_ofertas_con_llm` puebla la puntuación técnica. La
  memoria del licitador se trata como dato no confiable (anti-inyección) y la
  adjudicación derivada sigue exigiendo gate de la mesa (`VERIFIED`).
- Demos `persistencia_demo.py` y `juicio_valor_demo.py` (offline), 8 tests nuevos
  (46 en total), overrides de mypy para dependencias opcionales.

### Añadido
- Subpaquete `agent_platform.tenders`: aplicación del núcleo a **licitaciones
  públicas (LCSP 9/2017)**, cubriendo el ciclo completo.
- **Redacción** (worker "Redactor de pliegos"):
  - `PliegoSpec` config-as-data (Pydantic), versionable en git.
  - Motor de reglas LCSP (`validar`) → `InformeValidacion` con hallazgos
    referenciados al articulado.
  - `redactar` calcula cifras `PURE` (garantía, PBL con IVA) → `REPRODUCED`.
  - `publicar` como acto `EFFECTFUL` con gate firmado → `VERIFIED`.
- **Evaluación/revisión** (worker "Evaluación de ofertas"):
  - `Oferta` (dato externo *tainted*), `admisibilidad`, `evaluar`,
    `proponer_adjudicacion`.
  - Puntuación económica `PURE`→`REPRODUCED`, juicio de valor, baja anormal
    (art. 149), clasificación y propuesta de adjudicación con gate de la mesa.
- **CLI**: `python -m agent_platform.tenders validar <pliego.json>`.
- Runtime compartido (`_runtime.py`), demos (`examples/licitacion_demo.py`,
  `examples/evaluacion_demo.py`), `docs/licitaciones.md`. 25 tests del dominio
  (38 en total).

## [3.0.0] — Núcleo del contrato (§4)

Primera implementación del esqueleto runnable del invariante central, derivado
del documento de arquitectura v3 (`docs/arquitectura.md`).

### Añadido
- Paquete `agent_platform` organizado por capas (tools, contracts, reasoning,
  policy, execution, audit, replay, errors, sealing) en lugar de un módulo único.
- Taint **derivada por procedencia** por el runtime y propagada a las salidas;
  el plan (output del LLM) no la declara.
- Replay con **veredicto tipado por paso**: `REPRODUCED` / `VERIFIED` / `UNREPLAYABLE`.
- Log **tamper-evident**: hash-encadenado + sello con ancla externa.
- Camino de reparación **re-autorizado** en cada vuelta (sin bypass de policy).
- 13 tests del invariante (`pytest`), demo end-to-end, `mypy --strict` limpio.
- Toolchain de calidad: `ruff` (E/F/I/UP/B/SIM/C4/RUF), `Makefile`, CI en
  GitHub Actions.

### Notas
- Target Python 3.11: enums modernizados a `StrEnum`, anotaciones `X | Y`,
  imports desde `collections.abc`.
- Dinero en `Decimal`, nunca `float`.
