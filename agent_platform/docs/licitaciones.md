# Aplicación: Redacción y revisión de licitaciones públicas (LCSP 9/2017)

El subpaquete `agent_platform.tenders` aplica el núcleo del contrato al dominio
de contratación pública española. Es un caso de uso de manual: dinero público,
decisiones legalmente impugnables, criterios medibles y documentos de terceros
(las ofertas) que son **input adversarial por diseño**.

## El mapeo clave: tipo de criterio = `ToolKind`

La LCSP ya distingue dos clases de criterio de adjudicación, y coinciden con la
taxonomía del núcleo:

| Criterio de adjudicación | `ToolKind` | Veredicto replay | Por qué |
|---|---|---|---|
| **Evaluable por fórmula** (precio, plazo, mejoras cuantificables) | `PURE` | `REPRODUCED` | Matemática determinista en `Decimal`: se re-ejecuta y da idéntico. Defiende una puntuación automática ante un recurso. |
| **Juicio de valor** (calidad técnica) | asistido por LLM | `VERIFIED` | Subjetivo: NO se promete reproducible. El log atestigua qué se propuso y qué firmó la mesa. |

## Las fronteras del núcleo, aplicadas

- **Tainting:** cada oferta de un licitador entra *tainted*. Una cifra o
  instrucción embebida en un PDF no puede disparar una publicación/adjudicación
  sin pasar por policy + gate humano (`test_dato_externo_tainted_no_dispara_publicacion_sin_gate`).
- **Gates firmados (`EFFECTFUL`):** publicar el pliego, adjudicar y notificar son
  actos irreversibles → exigen `gate_token` firmado del órgano de contratación.
- **Plan como dato:** el motor de reglas LCSP (`lcsp.py`) valida el pliego ANTES
  de calcular o publicar nada.
- **Chain-of-Work:** log hash-encadenado y sellado → expediente tamper-evident
  para defender impugnaciones (recurso especial en materia de contratación).

## Qué hace hoy el worker "Redactor de pliegos"

`agent_platform.tenders`:

- **`PliegoSpec`** (`models.py`): config-as-data tipada y versionable en git del
  pliego (objeto, CPV, VEC/PBL, criterios, garantía, condiciones especiales…).
- **`validar(spec)`** (`lcsp.py`): motor de reglas que emite un `InformeValidacion`
  con hallazgos (ERROR/AVISO) referenciados al articulado:
  - suma de pesos de criterios = 100 (arts. 145-146)
  - juicio de valor > fórmula → comité de expertos (art. 146.2.a)
  - garantía definitiva = 5% (art. 107.1)
  - coherencia VEC ≥ PBL (arts. 100-101)
  - ≥1 condición especial de ejecución (art. 202.1)
  - plazo mínimo de presentación según procedimiento/SARA (arts. 156-164)
  - objeto y CPV presentes (art. 99)
- **`redactar(spec)`** (`worker.py`): valida y calcula las cifras del pliego
  (garantía, PBL con IVA) de forma auditable → `REPRODUCED`.
- **`publicar(spec, gate_token)`**: acto `EFFECTFUL` que exige conformidad LCSP y
  gate firmado → la publicación queda `VERIFIED` en el log.

```bash
make demo-licitacion    # python examples/licitacion_demo.py
```

## Límites legales (honestidad — no cruzar)

- **La IA no adjudica ni publica por sí misma.** Es un acto administrativo del
  órgano/mesa de contratación. La IA asiste; el humano firma y es responsable.
- **El juicio de valor es del evaluador**, no del modelo: `VERIFIED` atestigua,
  no sustituye.
- **Umbrales configurables:** los plazos y porcentajes son *defaults orientativos*.
  La LCSP se modifica; verifica contra el texto consolidado vigente. Las
  referencias a artículos orientan, no son asesoramiento jurídico.
- `VERIFIED` es tan bueno como la honestidad de los inputs (§12 de la arquitectura).

## Worker "Evaluación de ofertas" (revisión)

`agent_platform.tenders` (módulo `evaluacion.py`) cubre el flujo de la mesa de
contratación, reutilizando las mismas piezas del núcleo:

- **`Oferta`**: la oferta de un licitador. Es **dato externo → entra *tainted***.
- **`admisibilidad(oferta)`**: sobre administrativo — prohibición de contratar
  (art. 71) y documentación completa → motivo de exclusión o `None`.
- **`evaluar(spec, ofertas)`**:
  1. excluye las no admisibles,
  2. puntúa lo económico con la fórmula (proporcional a la más baja) como tool
     `PURE` → `REPRODUCED`,
  3. suma la puntuación técnica (juicio de valor, input del comité),
  4. marca las **bajas anormalmente bajas** (art. 149) — no las excluye: exigen
     audiencia y justificación (art. 149.4),
  5. clasifica las ofertas por puntuación total.
- **`proponer_adjudicacion(resultado, gate_token)`**: acto `EFFECTFUL`. Como el
  importe deriva de la oferta del licitador (*tainted*), el núcleo exige gate por
  **doble vía** (effectful + tainted): no se puede auto-adjudicar a partir de
  cifras aportadas por un licitador. Queda `VERIFIED` en el log.

```bash
make demo-evaluacion
```

El umbral de baja anormal (`umbral_puntos`) es **configurable**: el art. 149.2
remite a los parámetros objetivos del pliego (RGLCAP art. 85 como referencia).

## CLI

```bash
python -m agent_platform.tenders validar pliego.json
```

Valida un `PliegoSpec` en JSON contra la LCSP y devuelve el informe; código de
salida 0 (conforme), 1 (errores) o 2 (entrada inválida). Útil en hooks de CI
sobre los pliegos versionados en git.

## Juicio de valor asistido por LLM

`EvaluadorAnthropic` (dependencia opcional `[llm]`) usa Claude (Opus 4.8) para
proponer la puntuación de los criterios de **juicio de valor** a partir de la
memoria técnica del licitador:

```python
from agent_platform.tenders import EvaluadorAnthropic, evaluar_ofertas_con_llm, evaluar
motor = EvaluadorAnthropic()                       # usa ANTHROPIC_API_KEY
puntuadas = evaluar_ofertas_con_llm("Calidad técnica", ofertas, motor, max_puntos=Decimal("40"))
resultado = evaluar(spec, puntuadas)
```

Tres cautelas que lo hacen defendible:

- La memoria del licitador es **dato externo no confiable**: el sistema instruye
  al modelo para ignorar instrucciones embebidas (anti-inyección, §7b).
- La puntuación es una **propuesta**; la mesa/comité la revisa y la asume con su
  firma. La adjudicación derivada queda `VERIFIED`, **nunca `REPRODUCED`** — un
  juicio de valor no se promete reproducible.
- El modelo nunca adjudica ni decide montos: solo sugiere una puntuación acotada
  en código (`min(0, max_puntos)`), porque su salida es dato, no autoridad.

## Persistencia del expediente (Chain-of-Work)

El log de cada acto (publicación, valoración, propuesta de adjudicación) se
vuelca a un almacén durable y se recarga para re-verificar cadena y sello tras un
reinicio — el expediente que defiende un recurso debe sobrevivir al proceso:

```python
from agent_platform import SqliteEventStore   # o PostgresEventStore (sistema de registro)
store = SqliteEventStore("expedientes.db")
store.guardar("LIC-2026-001", resultado.log, resultado.seal)   # append-only
log, seal = store.cargar("LIC-2026-001")                       # re-verificable
```

**Notion como almacén/mirror** (`NotionEventStore`, opcional `[notion]`): vuelca
el expediente a una base de datos de Notion para que la mesa lo revise en una UI
familiar. Notion es mutable y no-WORM, pero la tamper-evidence se mantiene — el
sello se firma con una clave del runtime que no se almacena en Notion, así que
cualquier edición se detecta al recargar con `verify_chain`. Para expediente
regulado, mantén Postgres/WORM como autoritativo y usa Notion solo como espejo.

```python
from agent_platform import NotionEventStore
store = NotionEventStore(database_id="...")   # NOTION_TOKEN en el entorno
store.guardar("LIC-2026-001", resultado.log, resultado.seal)
```

