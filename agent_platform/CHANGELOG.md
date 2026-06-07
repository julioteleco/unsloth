# Changelog

## [Unreleased]

### Añadido
- Subpaquete `agent_platform.tenders`: aplicación del núcleo a **licitaciones
  públicas (LCSP 9/2017)**, worker "Redactor de pliegos".
  - `PliegoSpec` config-as-data (Pydantic), versionable en git.
  - Motor de reglas LCSP (`validar`) → `InformeValidacion` con hallazgos
    referenciados al articulado.
  - `redactar` calcula cifras `PURE` (garantía, PBL con IVA) → `REPRODUCED`.
  - `publicar` como acto `EFFECTFUL` con gate firmado → `VERIFIED`.
  - 13 tests del worker, demo (`examples/licitacion_demo.py`), `docs/licitaciones.md`.

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
