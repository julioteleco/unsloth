# Plataforma de Agentes Empresariales — Núcleo del contrato

Implementación del **contrato del núcleo (§4)** del documento de arquitectura
(`docs/arquitectura.md`): un esqueleto *runnable* y `mypy --strict` limpio que
*enforce* —no en prosa— el invariante central de la plataforma.

> **Principio rector:** la estocasticidad se confina a la capa de planificación;
> todo lo de abajo es tipado, auditable y —donde la naturaleza del efecto lo
> permite— reproducible. El LLM nunca calcula, decide montos ni produce el output
> final: produce un **plan tipado** que se valida contra el registro de
> herramientas y el policy engine *antes* de ejecutarse.

## Qué demuestra el código (cinco propiedades)

1. **Ejecución determinista y auditable** — dinero en `Decimal`, nunca `float`.
2. **Replay con veredicto por paso** según el tipo de efecto (`ToolKind`):
   `REPRODUCED` para puros e idempotentes (con idempotency key + snapshot),
   `VERIFIED` para efectos no repetibles, `UNREPLAYABLE` para fallos o evidencia rota.
3. **Taint derivada por procedencia** — el runtime la deriva de la procedencia de
   cada argumento y la propaga a las salidas; el plan (output del LLM) no la
   declara. Un dato recuperado *tainted* no dispara un efecto sin gate, ni
   directamente ni a través de pasos derivados.
4. **Camino de reparación re-autorizado** — una reparación maliciosa no evade la policy.
5. **Log tamper-evident** — hash-encadenado y sellado con un ancla externa, no un
   simple append-only.

## Estructura (capas desacopladas)

```
src/agent_platform/
  tools.py        # ToolKind, Tool, REGISTRY, hashing canónico
  contracts.py    # Lit, Ref, Arg, Step, Plan, Value, Meta, AuditEvent (contratos tipados)
  reasoning.py    # ReasoningEngine (Protocol) — la única pieza estocástica
  errors.py       # PolicyError, IntegrityError, Escalation, Budget
  sealing.py      # seal_head — ancla externa (HMAC modela firma/WORM)
  policy.py       # _resolve (deriva taint) + authorize (policy en código)
  execution.py    # execute / _run_step — ejecución + self-healing acotado
  audit.py        # verify_chain — verificación de la cadena (Chain-of-Work)
  replay.py       # Verdict, replay — veredicto tipado por paso
tests/test_core.py   # 13 tests del invariante
examples/demo.py     # demo end-to-end
docs/arquitectura.md # documento de arquitectura completo
```

Cada capa habla con la siguiente por contratos tipados (Pydantic), nunca por
texto libre del LLM. La **trust boundary** está en `policy.py`: el plan y los
datos recuperados se validan (esquema + policy + taint) *antes* de que
`execution.py` los ejecute.

## Uso

```bash
cd agent_platform
make install                  # pip install -e ".[dev]"  (pydantic + mypy + pytest + ruff)

make check                    # lint + typecheck + test, todo de una
# o individualmente:
make lint                     # ruff check
make typecheck                # mypy --strict (config en pyproject.toml)
make test                     # pytest -q  (13 tests)
make demo                     # python examples/demo.py  (end-to-end)
```

Sin `make`, los comandos equivalentes son `ruff check src tests examples`,
`mypy`, `pytest -q` y `python examples/demo.py`. CI los corre en cada push/PR
que toque `agent_platform/` (`.github/workflows/agent_platform-ci.yml`).

## Aplicación incluida: licitaciones públicas (LCSP 9/2017)

El subpaquete `agent_platform.tenders` aplica el núcleo a la **redacción y
validación de pliegos** de contratación pública española:

- **Config-as-data** del pliego (`PliegoSpec`), versionable en git.
- **Motor de reglas LCSP** (`validar`) → informe de hallazgos (ERROR/AVISO) con
  referencia al articulado (suma de criterios = 100, comité de expertos si el
  juicio de valor supera a la fórmula, garantía 5%, condición especial de
  ejecución, plazos mínimos…).
- **Cifras auditables** (`redactar`): garantía y PBL con IVA son tools `PURE` →
  veredicto `REPRODUCED`.
- **Publicación con gate firmado** (`publicar`): acto `EFFECTFUL` → `VERIFIED`,
  bloqueado sin firma del órgano de contratación o si el pliego no es conforme.
- **Evaluación de ofertas** (`evaluar`, `proponer_adjudicacion`): admisibilidad,
  puntuación económica `PURE`→`REPRODUCED`, juicio de valor, detección de baja
  anormal (art. 149) y propuesta de adjudicación con gate de la mesa. Las ofertas
  entran *tainted*, así que la adjudicación nunca se dispara sin firma.
- **CLI**: `python -m agent_platform.tenders validar pliego.json`.

```bash
make demo-licitacion     # redacción + validación + publicación
make demo-evaluacion     # admisibilidad + puntuación + adjudicación
```

Detalle y límites legales en `docs/licitaciones.md`.

## Límites honestos

Esto certifica *qué pasó*, no que el planner sea determinista. No promete "IA
determinista" ni "cero alucinaciones": el planner sigue siendo estocástico. La
promesa es **ejecución verificable y auditable**, con la distinción
reproduce/verifica explícita. Ver §11 y §12 del documento de arquitectura.
