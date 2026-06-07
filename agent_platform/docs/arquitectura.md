# Documento de Arquitectura — Plataforma de Agentes Empresariales

**Alcance:** plataforma para automatizar *workflows acotados* de alto riesgo o regulados (finanzas, legal, ops de seguros/banca), donde auditabilidad, reproducibilidad y control humano son requisitos contractuales, no extras. La unidad de progreso es el *digital worker*: un rol corporativo medible con entradas, salidas y criterios de aceptación fijos. El núcleo técnico es reutilizable fuera de regulado; lo que cambia es la capa de gobernanza y el go-to-market. "Acotado" es una decisión de diseño, no una limitación temporal: §12 explica dónde esta arquitectura deja de ser la herramienta correcta.

**Audiencia:** fundador/a técnico y primeros ingenieros. Documento autocontenido. Versión 3 —endurece la frontera de confianza del núcleo: taint derivada por procedencia (no declarada por el plan), re-autorización del camino de reparación y log hash-encadenado con sello externo—, sujeta a revisión tras el primer eval set real con datos de cliente.

---

## 0. Principio de diseño rector

Todo lo demás se deriva de esto: **la estocasticidad se confina a la capa de planificación; todo lo de abajo es tipado, auditable y —donde la naturaleza del efecto lo permite— reproducible.**

El LLM nunca calcula, decide montos, ni produce el output final por sí mismo. El LLM produce un **plan tipado** (qué pasos, qué herramientas, con qué argumentos). Ese plan es **output de un modelo y por tanto dato no confiable**: se valida contra el registro de herramientas y contra el policy engine *antes* de ejecutarse, igual que validarías un payload de un cliente externo. El plan validado lo ejecuta código en un sandbox aislado. Cada ciclo se registra en un log inmutable con metadatos suficientes para reconstruir o atestiguar la ejecución después.

Lo que esto **sí** te da: trazabilidad total, eliminación de la clase de error "el modelo hizo mal la cuenta o inventó una cifra", y —para pasos sin efectos externos— replay con resultado idéntico. Lo que **no** te da, y no debes prometer: que el sistema sea determinista de extremo a extremo (el planner sigue siendo estocástico), que "elimina alucinaciones" (el planner puede elegir mal un paso; el log lo registra, no lo impide), ni que toda ejecución sea *reproducible*. La promesa honesta es **ejecución verificable y auditable**, con una distinción que la mayoría de las arquitecturas borra y que esta hace explícita: *reproducir* y *verificar* no son lo mismo, y cuál obtienes depende del tipo de efecto del paso (§6).

Para que esa promesa sea real, el log debe capturar por paso: versión exacta del modelo, `temperature`, `seed` cuando exista, hash del prompt ensamblado, hashes de los datos recuperados, versión de cada herramienta y del sandbox. Sin esos metadatos tienes registro, no reproducibilidad —y el código de §4 los exige en el tipo, no en un comentario—. La inmutabilidad tampoco es una etiqueta: cada evento encadena el hash del anterior y la cabeza de la cadena se sella con un ancla externa (firma o WORM), de modo que un tamper *consistente* —reescribir un valor y su hash a la vez— cambia la cabeza y rompe el sello (§6).

---

## 1. Vista de arquitectura

```
                        +-------------------------------+
                        |   INTERFACES (API / Studio)   |
                        +---------------+---------------+
                                        |
        +-------------------------------v-----------------------------+
        |                       CONTROL PLANE                         |
        |   Orquestador durable (LangGraph + Temporal)                |
        |   Reasoning Engine = LLM-as-planner   ->   Plan TIPADO      |
        +------+------------------------------------------+-----------+
               | plan (dato NO confiable)                 | contexto
   +-----------v------+                        +----------v---------+
   | MODEL GATEWAY    |                        | CONTEXT / MEMORY   |
   | routing big/SLM  |                        | store + retrieval  |
   | (LiteLLM/propio) |                        | (PG+pgvector/S3)   |
   +------------------+                        +----------+---------+
               |                                          | datos recuperados
               |                                          | = NO confiables
   ===== TRUST BOUNDARY =====================================================
   el plan y los datos recuperados cruzan aquí como DATO; nada se confía por
   venir "del agente" -> validación de esquema, policy y taint ANTES de ejecutar
                                   |
        +--------------------------v----------------------------------+
        |  GOVERNANCE / POLICY  (valida el plan ANTES de ejecutar)    |
        |  esquema (Pydantic) + policy engine (OPA/Cedar)             |
        |  + tainting DERIVADO por procedencia + gates firmados       |
        |  + budgets / circuit breakers                               |
        +--------------------------+----------------------------------+
                                   | solo pasos tipados YA autorizados
        +--------------------------v----------------------------------+
        |  EXECUTION LAYER   sandbox aislado (E2B/Firecracker)        |
        |  tool registry tipado (ToolKind) + self-healing acotado     |
        |  (cada reparación vuelve a pasar por POLICY)                |
        +--------------------------+----------------------------------+
                                   | cada ciclo
        +--------------------------v----------------------------------+
        |  AUDIT / OBSERVABILITY (Chain-of-Work)                      |
        |  log hash-encadenado + sello externo + OTel + Langfuse      |
        +--------------------------+----------------------------------+
                                   |
                     +-------------v-------------+
                     | EXTERNAL SYSTEMS (APIs/DB)|
                     +---------------------------+
```

Siete capas desacopladas. Regla de oro: cada capa habla con la siguiente por contratos tipados (Pydantic / JSON Schema), nunca por texto libre del LLM inyectado directo en un comando o query. La línea de **trust boundary** marca dónde el output del planner y los datos recuperados dejan de tratarse como confiables: por debajo de ella, governance valida esquema, policy y taint sobre el plan *antes* de que la execution layer lo ejecute (§7b). El orden importa y el diagrama lo refleja —policy precede a ejecución, no al revés—.

---

## 2. Componentes

### 2.1 Control plane (orquestación)
El Reasoning Engine recibe el objetivo y emite un `Plan` tipado; el orquestador valida, ejecuta los pasos, recoge resultados y decide si re-planifica. Dos piezas, no una:

- **Grafo de razonamiento con ciclos** para el lazo planificar → ejecutar → evaluar → re-planificar. LangGraph modela ciclos y estado explícito, no solo DAGs.
- **Motor de workflow durable** para que un agente que corre horas o días sobreviva a caídas, reinicios y reintentos sin perder estado. Temporal es grado producción; reemplaza el antipatrón de "scripts cron en Bash" para coordinar trabajo de larga duración.

Separar ambos importa: LangGraph orquesta la *lógica del agente*; Temporal garantiza la *durabilidad de la ejecución*. Esta combinación es una **apuesta reversible, no un axioma** —ver criterios de salida en §3.

### 2.2 Execution layer (ejecución determinista donde puede)
Recibe pasos tipados ya autorizados y los ejecuta. Dos tipos de paso: llamada a herramienta registrada, o ejecución de código generado. Todo corre en un sandbox aislado y efímero, nunca en el proceso principal.

- **Sandbox:** E2B si quieres gestionado y rápido de arrancar; Firecracker microVMs o gVisor para aislamiento fuerte self-hosted; Docker efímero como mínimo viable. Para clientes regulados, microVM por defecto.
- **Tool registry tipado con clase de efecto:** cada herramienta declara su firma (tipos, validación entrada/salida) **y su `ToolKind`** —`pure`, `idempotent` o `effectful`—. Esta clasificación no es cosmética: determina la semántica de auditoría y replay (§6) y qué pasos pueden dispararse desde datos no confiables (§7b). El LLM solo puede invocar herramientas registradas con argumentos que validan contra el esquema.
- **Self-healing acotado:** si un paso falla, se captura el traceback y se devuelve al planner para corregir, **con presupuesto de reintentos y escalado a humano**. Sin tope, tienes loops caros y el riesgo de que el modelo "arregle" el código enmascarando el error real. El código de §4 implementa exactamente esto: recuperación dentro de presupuesto, escalado al agotarlo. El paso reparado es output no confiable del LLM, así que vuelve a pasar por registro y policy en cada vuelta: una reparación que cambie la herramienta o quite un gate se rechaza, no se ejecuta (`test_repair_path_is_reauthorized`).

### 2.3 Context / Memory layer
El problema real no es "meter PDFs de 500 páginas al contexto" sino *traer el fragmento correcto en el momento correcto*. Los datos viven fuera del contexto del LLM; al modelo le llega un índice y fragmentos bajo demanda. **Todo fragmento recuperado entra al sistema marcado como no confiable** (provenance tainting) por código del runtime, no por el plan: la marca la deriva el sistema de la procedencia, no la declara el LLM (§7b).

- **Sistema de registro:** Postgres. Fuente de verdad de tareas, estado y metadatos.
- **Recuperación semántica:** pgvector si quieres una sola base; Qdrant si necesitas escala y filtros de retrieval avanzados.
- **Artefactos crudos:** object storage (S3 / MinIO) para documentos, con punteros desde Postgres.

Nota honesta: vas a usar embeddings y retrieval. La idea de "sin chunking ni embeddings" es diferenciación de marketing; la decisión real es *dónde viven los datos* (externos + inyección selectiva) frente a volcar crudo. La calidad se gana o se pierde en la estrategia de chunking y retrieval, que es la parte difícil y donde debes invertir.

### 2.4 Audit / Observability (Chain-of-Work)
Log append-only, event-sourced, que registra cada ciclo y emite un **veredicto de replay tipado por paso** (§6). Es el activo diferenciador para clientes regulados.

- **Trazas estructuradas:** OpenTelemetry como estándar transversal.
- **Trazas específicas de LLM:** Langfuse (open-source, self-hostable) o LangSmith. Para regulado, self-hosted pesa a favor de Langfuse.

### 2.5 Governance / Safety
- **Human-in-the-loop:** gates de aprobación explícitos —con token firmado y auditado— antes de toda acción `effectful` no idempotente o de alto impacto. Ningún cambio irreversible sin firma.
- **Policy engine:** reglas de negocio y autorización declarativas con OPA (Rego) o Cedar, evaluadas en código sobre el plan antes de ejecutar. Las políticas no se le piden al LLM.
- **Presupuestos y circuit breakers:** límites de tokens, costo y reintentos por worker y por tenant.

### 2.6 Model gateway
Hace el sistema **model-agnostic** (hardcodear un modelo es deuda técnica). Implementa dual-model routing: un modelo grande planifica y fragmenta; SLMs ejecutan micro-tareas repetitivas (extracción de entidades, formateo).

- **Gateway:** LiteLLM para empezar (unifica proveedores con una sola interfaz); gateway propio si el routing y el control de costos se vuelven core.
- **Inferencia self-hosted:** vLLM para servir modelos abiertos con throughput alto.

### 2.7 Interfaces
- **API:** FastAPI (async, validación Pydantic nativa, OpenAPI gratis).
- **Studio (no-code):** la definición de cada digital worker es **config-as-data** —YAML/JSON tipado y validado por Pydantic, versionado en git—, no código generado al vuelo. Un usuario no técnico define rol, políticas y ejemplos; el sistema compila eso a un system prompt estructurado más guardrails. Llamarlo "entrenar" es impreciso: es few-shot + configuración, no fine-tuning.

---

## 3. Stack tecnológico

| Capa | Recomendación primaria | Alternativas | Criterio de decisión |
|---|---|---|---|
| Orquestación lógica | LangGraph | LlamaIndex Workflows, CrewAI | Necesitas ciclos y estado explícito; CrewAI abstrae demasiado para regulado |
| Durabilidad workflow | Temporal | Restate, colas + state machine propia | Larga duración, supervivencia a fallos, reintentos |
| Sandbox de ejecución | E2B (gestionado) | Firecracker, gVisor, Docker efímero | Velocidad de arranque vs aislamiento; regulado → microVM |
| Validación/contratos | Pydantic v2 | dataclasses + jsonschema | Tipos en todas las fronteras entre capas |
| Sistema de registro | PostgreSQL | — | Default sólido; no inventes aquí |
| Retrieval semántico | pgvector | Qdrant, Weaviate | Una base (pgvector) vs escala y filtros (Qdrant) |
| Object storage | S3 / MinIO | GCS, R2 | MinIO si on-prem por compliance |
| Gateway de modelos | LiteLLM | OpenRouter, gateway propio | Empieza con LiteLLM; propio cuando routing sea core |
| Inferencia local | vLLM | TGI, Ollama (dev) | vLLM en prod; Ollama solo desarrollo |
| Policy engine | OPA (Rego) | Cedar | Reglas declarativas fuera del prompt |
| Observabilidad LLM | Langfuse (self-host) | LangSmith | Self-host pesa para datos sensibles |
| Trazas | OpenTelemetry | — | Estándar transversal |
| API | FastAPI | — | Async + Pydantic + OpenAPI |
| Secrets | HashiCorp Vault | cloud KMS | No metas claves en config plana |
| Eval | Promptfoo / propio | DeepEval, Langfuse evals | Imprescindible desde el día uno (§8) |

No fijo versiones exactas en la tabla porque el ecosistema se mueve rápido; en `pyproject.toml` fija versiones tras verificar las actuales y correr tu eval set contra ellas. En el código de §4 fijo solo lo necesario para que corra.

**La elección de orquestación es la bet más cara y debe tratarse como reversible.** Criterios de salida explícitos: abandona LangGraph si el grafo de estado se vuelve más simple que un DAG lineal (entonces sobra) o si su modelo de estado te obliga a workarounds en más del ~20% de los workers (entonces estorba). Abandona/pospón Temporal si ningún worker corre más de unos minutos ni necesita sobrevivir reinicios —una state machine sobre Postgres basta y evitas operar un cluster. La frontera plan-tipado de §4 está diseñada para que cambiar el orquestador no toque la capa de ejecución ni el contrato de auditoría; esa es la razón de desacoplarlos.

---

## 4. El contrato del núcleo (código)

Esqueleto **runnable** (13 tests, `mypy --strict` limpio) del invariante central. Demuestra, en código que *enforce* —no en prosa—, cinco propiedades: (1) la ejecución es determinista y auditable, con dinero en `Decimal`, nunca `float`; (2) el **replay devuelve un veredicto por paso según el tipo de efecto** —`REPRODUCED` para puros e idempotentes con idempotency key + snapshot, `VERIFIED` para efectos no repetibles, `UNREPLAYABLE` para fallos o evidencia rota—; (3) la **taint la deriva el runtime de la procedencia de cada argumento y la propaga a las salidas** —el plan no la declara, porque es output del LLM y podría mentir—, de modo que un dato recuperado *tainted* no dispara un efecto sin gate ni directamente ni a través de pasos derivados; (4) el **camino de reparación se re-autoriza**: una reparación maliciosa no evade la policy; (5) el **log es tamper-evident**: hash-encadenado y sellado con un ancla externa, no un simple append-only. El Reasoning Engine se mockea: es la parte estocástica.

```python
# requires: pydantic>=2.5,<3   (python>=3.11)
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Annotated, Callable, Literal, Mapping, Protocol, Union

from pydantic import BaseModel, Field


# === Taxonomía de herramientas ===========================================
# La semántica de replay NO es uniforme: depende del tipo de efecto. Este es
# el punto que separa "ejecución auditable" de "promesa falsa de determinismo".
class ToolKind(str, Enum):
    PURE = "pure"              # determinista, sin efectos -> replay RE-EJECUTA
    IDEMPOTENT = "idempotent"  # efecto seguro de repetir con misma key + snapshot
    EFFECTFUL = "effectful"    # efecto NO repetible -> replay solo VERIFICA, nunca re-ejecuta


@dataclass(frozen=True)
class Tool:
    name: str
    kind: ToolKind
    fn: Callable[[dict[str, Decimal]], Decimal]
    version: str = "1"
    requires_gate: bool = False  # efecto que exige aprobación humana explícita


def _canon(obj: object) -> str:
    # Decimal -> str para hash estable (nunca float: dinero en regulado va en Decimal).
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _hash(obj: object) -> str:
    return hashlib.sha256(_canon(obj).encode()).hexdigest()[:16]


# Registro tipado. El planner SOLO puede invocar ops que existan aquí.
REGISTRY: dict[str, Tool] = {
    "sum":      Tool("sum", ToolKind.PURE, lambda a: a["x"] + a["y"]),
    "ratio":    Tool("ratio", ToolKind.PURE, lambda a: a["x"] / a["y"]),  # DivisionByZero si y==0
    "upsert":   Tool("upsert", ToolKind.IDEMPOTENT, lambda a: a["value"]),  # demo: determinista
    "transfer": Tool("transfer", ToolKind.EFFECTFUL, lambda a: a["amount"], requires_gate=True),
}


# === Contratos tipados entre capas (datos que cruzan fronteras) ==========
# El Plan es OUTPUT DE UN LLM: dato no confiable. CLAVE del fix v3: el plan NO
# declara su propia taint. Un arg es un literal (confiable) o una REFERENCIA a
# un valor del contexto (dato recuperado) o a la salida de un paso previo. La
# taint la DERIVA código confiable a partir de la procedencia, ignorando lo que
# el planner afirme. Un plan inyectado no puede "auto-declararse" no-tainted.
class Lit(BaseModel):
    kind: Literal["lit"] = "lit"
    value: Decimal


class Ref(BaseModel):
    kind: Literal["ref"] = "ref"
    source: str  # clave de un dato recuperado, o id de un paso previo


Arg = Annotated[Union[Lit, Ref], Field(discriminator="kind")]


class Step(BaseModel):
    id: str
    op: str
    args: dict[str, Arg]
    gate_token: str | None = None
    # No hay campo 'tainted': la taint es propiedad de la procedencia, computada
    # por el runtime confiable (ver _resolve), nunca tomada del output del LLM.


class Plan(BaseModel):
    goal: str
    steps: list[Step]


@dataclass(frozen=True)
class Value:
    """Valor en el runtime confiable, con su marca de procedencia (taint)."""
    amount: Decimal
    tainted: bool


class AuditEvent(BaseModel):
    # --- qué pasó ---
    step_id: str
    op: str
    kind: ToolKind
    attempt: int
    args: dict[str, Decimal]          # args YA resueltos (literales + refs materializadas)
    args_hash: str
    tainted: bool                     # taint COMPUTADA por el runtime, no declarada por el plan
    output: Decimal | None            # None si el paso falló
    output_hash: str | None           # base del veredicto VERIFIED en ops effectful
    error: str | None
    # --- replay de idempotentes (REPRODUCED solo con key + snapshot, §6) ---
    idempotency_key: str | None
    state_snapshot_hash: str | None
    # --- reproducibilidad del planner (lo que §6 declara obligatorio) ---
    model_version: str
    temperature: float
    seed: int | None
    prompt_hash: str
    retrieved_hashes: list[str]
    # --- versiones de ejecución ---
    tool_version: str
    sandbox_version: str
    # --- tamper-evidence: hash-chain ---
    prev_hash: str
    event_hash: str = ""              # se rellena al sellar el evento

    def content_hash(self) -> str:
        # Hash sobre TODO el contenido + prev_hash, excluyendo event_hash. Cualquier
        # edición in-place (aunque el atacante recomponga output_hash) cambia esto.
        body = self.model_dump(exclude={"event_hash"})
        return _hash(body)


# === Reasoning Engine: estocástico en prod, mockeado aquí ================
class ReasoningEngine(Protocol):
    model_version: str
    temperature: float
    seed: int | None
    def plan(self, goal: str) -> Plan: ...
    def repair(self, step: Step, error: str) -> Step: ...


# === Errores de control ==================================================
class PolicyError(Exception):
    pass


class IntegrityError(Exception):
    """La cadena de auditoría no verifica: evidencia rota o manipulada."""


class Escalation(Exception):
    """Presupuesto de reintentos agotado -> handoff a humano, no loop infinito."""
    def __init__(self, step_id: str, log: list[AuditEvent]) -> None:
        super().__init__(f"escalado en {step_id} tras agotar reintentos")
        self.step_id = step_id
        self.log = log


@dataclass
class Budget:
    max_retries: int = 2
    _used: dict[str, int] = field(default_factory=dict)

    def consume(self, step_id: str) -> bool:
        self._used[step_id] = self._used.get(step_id, 0) + 1
        return self._used[step_id] <= self.max_retries + 1  # intento inicial + reintentos

    def used(self, step_id: str) -> int:
        return self._used.get(step_id, 0)


# === Sello de la cadena (ancla externa) ==================================
# En prod esto es una FIRMA asimétrica o un write a WORM: el atacante no puede
# re-sellar. Aquí un HMAC con clave retenida modela ese ancla. El hash-chain
# obliga a recomputar toda la cadena para un tamper consistente; el sello sobre
# la cabeza detecta esa recomputación porque la cabeza cambia.
_SIGNING_KEY = b"anchor-key-not-available-to-tamperer"


def seal_head(head_hash: str) -> str:
    return hmac.new(_SIGNING_KEY, head_hash.encode(), hashlib.sha256).hexdigest()[:16]


# === Resolución de args + DERIVACIÓN de taint (runtime confiable) ========
def _resolve(step: Step, values: dict[str, Value]) -> tuple[dict[str, Decimal], bool]:
    resolved: dict[str, Decimal] = {}
    tainted = False
    for name, arg in step.args.items():
        if isinstance(arg, Lit):
            resolved[name] = arg.value           # literal del plan: confiable
        else:
            src = values.get(arg.source)
            if src is None:
                raise PolicyError(f"{step.id}: referencia a fuente desconocida '{arg.source}'")
            resolved[name] = src.amount
            tainted = tainted or src.tainted      # la taint VIAJA con cualquier arg derivado
    return resolved, tainted


# === Policy engine (en código, fuera del prompt) =========================
def authorize(step: Step, tool: Tool, tainted: bool) -> None:
    # Mitigación de prompt injection indirecta: dato no confiable (tainted) no
    # puede disparar un efecto sin gate humano. La taint es la COMPUTADA, no la
    # declarada por el plan -> un plan inyectado no puede evadirla mintiendo.
    if tool.kind is ToolKind.EFFECTFUL and tainted and step.gate_token is None:
        raise PolicyError(f"{step.op}: arg tainted no puede disparar efecto sin gate")
    if tool.requires_gate and step.gate_token is None:
        raise PolicyError(f"{step.op}: requiere gate humano")


# === Execution layer: determinista donde puede, auditable siempre ========
@dataclass(frozen=True)
class Meta:
    model_version: str
    temperature: float
    seed: int | None
    prompt_hash: str
    retrieved_hashes: tuple[str, ...]
    sandbox_version: str


def _event(step: Step, tool: Tool, resolved: dict[str, Decimal], tainted: bool,
           meta: Meta, attempt: int, out: Decimal | None, err: str | None,
           prev_hash: str, values: dict[str, Value]) -> AuditEvent:
    idem = _hash(resolved) if tool.kind is ToolKind.IDEMPOTENT else None
    snap = _hash({k: str(v.amount) for k, v in sorted(values.items())}) \
        if tool.kind is ToolKind.IDEMPOTENT else None
    e = AuditEvent(
        step_id=step.id, op=step.op, kind=tool.kind, attempt=attempt,
        args=resolved, args_hash=_hash(resolved), tainted=tainted,
        output=out, output_hash=_hash(out) if out is not None else None, error=err,
        idempotency_key=idem, state_snapshot_hash=snap,
        model_version=meta.model_version, temperature=meta.temperature, seed=meta.seed,
        prompt_hash=meta.prompt_hash, retrieved_hashes=list(meta.retrieved_hashes),
        tool_version=tool.version, sandbox_version=meta.sandbox_version,
        prev_hash=prev_hash,
    )
    return e.model_copy(update={"event_hash": e.content_hash()})


def _run_step(step: Step, reasoner: ReasoningEngine, meta: Meta,
              values: dict[str, Value], budget: Budget, log: list[AuditEvent],
              prev_hash: str) -> tuple[Value, str]:
    current = step
    while True:
        if not budget.consume(step.id):
            raise Escalation(step.id, log)
        attempt = budget.used(step.id)
        # FIX: la herramienta se re-resuelve y la policy se re-evalúa EN CADA
        # iteración, incluida la del paso reparado. La reparación es output del
        # LLM y por tanto no confiable: no hay bypass por el camino de repair.
        tool = REGISTRY.get(current.op)
        if tool is None:
            raise PolicyError(f"herramienta no registrada: {current.op}")
        resolved, tainted = _resolve(current, values)
        authorize(current, tool, tainted)
        try:
            out = tool.fn(resolved)
        except Exception as exc:  # captura traceback -> self-healing acotado
            log.append(_event(current, tool, resolved, tainted, meta, attempt, None, repr(exc),
                              prev_hash, values))
            prev_hash = log[-1].event_hash
            current = reasoner.repair(current, repr(exc))  # re-validado arriba en la próxima vuelta
            continue
        log.append(_event(current, tool, resolved, tainted, meta, attempt, out, None,
                          prev_hash, values))
        return Value(out, tainted), log[-1].event_hash


def execute(plan: Plan, reasoner: ReasoningEngine, meta: Meta,
            retrieved: Mapping[str, Value] | None = None,
            budget: Budget | None = None) -> tuple[dict[str, Decimal], list[AuditEvent], str]:
    budget = budget or Budget()
    values: dict[str, Value] = dict(retrieved or {})  # datos recuperados entran TAINTED
    results: dict[str, Decimal] = {}
    log: list[AuditEvent] = []
    prev_hash = "GENESIS"
    for step in plan.steps:
        out, prev_hash = _run_step(step, reasoner, meta, values, budget, log, prev_hash)
        values[step.id] = out          # la salida queda disponible (con su taint) para refs
        results[step.id] = out.amount
    return results, log, seal_head(prev_hash)


# === Verificación de la cadena (tamper-evidence) =========================
def verify_chain(log: list[AuditEvent], seal: str) -> set[str]:
    """Devuelve el conjunto de step_id cuya evidencia está íntegra. Un tamper
    in-place rompe content_hash; un tamper consistente recomputado cambia la
    cabeza y por tanto invalida el sello."""
    ok: set[str] = set()
    prev = "GENESIS"
    for e in log:
        if e.prev_hash != prev or e.event_hash != e.content_hash():
            pass  # eslabón roto: este paso no se añade a 'ok'
        else:
            ok.add(e.step_id)
        prev = e.event_hash
    if seal_head(prev) != seal:
        return set()  # ancla externa rota: toda la cadena pudo recomputarse -> nada es de fiar
    return ok


# === Replay: veredicto tipado por paso ===================================
class Verdict(str, Enum):
    REPRODUCED = "reproduced"      # re-ejecutado, output idéntico (pure / idempotent c/ snapshot)
    VERIFIED = "verified"          # no re-ejecutable; output registrado e íntegro (effectful)
    UNREPLAYABLE = "unreplayable"  # paso fallido, sin evidencia, o cadena rota


def replay(log: list[AuditEvent], seal: str) -> dict[str, Verdict]:
    intact = verify_chain(log, seal)
    verdicts: dict[str, Verdict] = {}
    for e in log:
        if e.step_id not in intact or e.error is not None or e.output is None:
            verdicts[e.step_id] = Verdict.UNREPLAYABLE
            continue
        if e.args_hash != _hash(e.args):
            verdicts[e.step_id] = Verdict.UNREPLAYABLE
            continue
        tool = REGISTRY[e.op]
        if tool.kind is ToolKind.PURE:
            verdicts[e.step_id] = (
                Verdict.REPRODUCED if tool.fn(e.args) == e.output else Verdict.UNREPLAYABLE
            )
        elif tool.kind is ToolKind.IDEMPOTENT:
            # REPRODUCED solo con idempotency key + snapshot de estado; si no, VERIFIED.
            if e.idempotency_key is not None and e.state_snapshot_hash is not None:
                verdicts[e.step_id] = (
                    Verdict.REPRODUCED if tool.fn(e.args) == e.output else Verdict.UNREPLAYABLE
                )
            else:
                verdicts[e.step_id] = Verdict.VERIFIED
        else:  # EFFECTFUL: jamás se re-ejecuta; solo se atestigua contra el registro
            verdicts[e.step_id] = (
                Verdict.VERIFIED if e.output_hash == _hash(e.output) else Verdict.UNREPLAYABLE
            )
    return verdicts


# ====================== a partir de aquí: tests ==========================


def _D(x: str) -> Decimal:
    return Decimal(x)


def _lit(x: str) -> Lit:
    return Lit(value=_D(x))


_META = Meta(model_version="mock-1", temperature=0.0, seed=7, prompt_hash="p:abc",
             retrieved_hashes=("d:1", "d:2"), sandbox_version="fc:1.0")


class MockReasoner:
    model_version = "mock-1"
    temperature = 0.0
    seed: int | None = 7

    def __init__(self, repair_fn: Callable[[Step, str], Step] | None = None) -> None:
        self._repair = repair_fn or (lambda s, _e: s)  # por defecto NO arregla

    def plan(self, goal: str) -> Plan:
        return Plan(goal=goal, steps=[
            Step(id="s1", op="sum", args={"x": _lit("10"), "y": _lit("5")}),
            Step(id="s2", op="ratio", args={"x": _lit("30"), "y": _lit("4")}),
            Step(id="s3", op="transfer", args={"amount": _lit("100")}, gate_token="sig:alice"),
        ])

    def repair(self, step: Step, error: str) -> Step:
        return self._repair(step, error)


def test_traceability_and_chain_invariant() -> None:
    r = MockReasoner()
    plan = r.plan("demo")
    _, log, seal = execute(plan, r, _META)
    assert len(log) == len(plan.steps)
    assert {e.step_id for e in log} == {s.id for s in plan.steps}
    for e in log:  # metadatos de reproducibilidad presentes en cada evento (§6)
        assert e.model_version and e.prompt_hash and e.retrieved_hashes
        assert e.seed is not None and isinstance(e.temperature, float)
        assert e.tool_version and e.sandbox_version
    # la cadena entera verifica y el sello casa
    assert verify_chain(log, seal) == {"s1", "s2", "s3"}


def test_pure_execution_is_deterministic() -> None:
    r = MockReasoner()
    a, _, _ = execute(r.plan("demo"), r, _META)
    b, _, _ = execute(r.plan("demo"), r, _META)
    assert a == b == {"s1": _D("15"), "s2": _D("7.5"), "s3": _D("100")}


def test_replay_reproduces_pure_but_only_verifies_effectful() -> None:
    r = MockReasoner()
    _, log, seal = execute(r.plan("demo"), r, _META)
    v = replay(log, seal)
    assert v["s1"] is Verdict.REPRODUCED   # pure
    assert v["s2"] is Verdict.REPRODUCED   # pure
    assert v["s3"] is Verdict.VERIFIED     # effectful: NO se re-ejecuta, se atestigua


def test_inplace_tamper_is_unreplayable() -> None:
    # Tamper CONSISTENTE (output y output_hash a la vez) pero sin recomputar la
    # cadena: content_hash deja de casar -> UNREPLAYABLE. Mejora sobre v2, que
    # solo detectaba tampers inconsistentes.
    r = MockReasoner()
    _, log, seal = execute(r.plan("demo"), r, _META)
    bad = list(log)
    bad[2] = bad[2].model_copy(update={"output": _D("999"), "output_hash": _hash(_D("999"))})
    v = replay(bad, seal)
    assert v["s3"] is Verdict.UNREPLAYABLE


def test_full_chain_recompute_defeated_by_seal() -> None:
    # El atacante recompone TODA la cadena de forma internamente consistente.
    # La cabeza cambia y el sello (ancla externa) ya no valida -> detectado.
    r = MockReasoner()
    _, log, seal = execute(r.plan("demo"), r, _META)
    forged: list[AuditEvent] = []
    prev = "GENESIS"
    for e in log:
        upd = {"output": _D("999"), "output_hash": _hash(_D("999"))} if e.step_id == "s3" else {}
        e2 = e.model_copy(update={**upd, "prev_hash": prev})
        e2 = e2.model_copy(update={"event_hash": e2.content_hash()})
        forged.append(e2)
        prev = e2.event_hash
    # cadena internamente consistente...
    assert all(forged[i].prev_hash == (forged[i - 1].event_hash if i else "GENESIS")
               for i in range(len(forged)))
    # ...pero el sello original no casa con la nueva cabeza
    assert seal_head(prev) != seal
    assert replay(forged, seal)["s3"] is Verdict.UNREPLAYABLE


def test_unregistered_tool_is_rejected() -> None:
    r = MockReasoner()
    bad = Plan(goal="x", steps=[Step(id="s1", op="rm_rf", args={})])
    try:
        execute(bad, r, _META)
        assert False, "debió rechazar herramienta no registrada"
    except PolicyError as e:                       # FIX: excepción tipada, no assert
        assert "no registrada" in str(e)


def test_tainted_retrieved_data_cannot_trigger_effect_without_gate() -> None:
    # Prompt injection indirecta: un dato recuperado (TAINTED) referenciado como
    # monto de transfer. El plan no puede declararse no-tainted: no existe el campo.
    r = MockReasoner()
    retrieved = {"doc_amount": Value(_D("5000"), tainted=True)}
    p = Plan(goal="x", steps=[
        Step(id="s1", op="transfer", args={"amount": Ref(source="doc_amount")}),  # sin gate
    ])
    try:
        execute(p, r, _META, retrieved)
        assert False, "policy debió bloquear efecto desde dato tainted sin gate"
    except PolicyError as e:
        assert "tainted" in str(e)


def test_taint_propagates_through_derived_output() -> None:
    # La taint VIAJA: s1 (pure) consume dato tainted; s2=transfer referencia la
    # salida de s1. Aunque s2 no toque el dato recuperado directamente, hereda la
    # taint y exige gate. Sin gate -> rechazo. Esto es lo que la prosa promete.
    r = MockReasoner()
    retrieved = {"doc_amount": Value(_D("5000"), tainted=True)}
    p = Plan(goal="x", steps=[
        Step(id="s1", op="sum", args={"x": Ref(source="doc_amount"), "y": _lit("0")}),
        Step(id="s2", op="transfer", args={"amount": Ref(source="s1")}),  # hereda taint de s1
    ])
    try:
        execute(p, r, _META, retrieved)
        assert False, "la taint debió propagarse a s2 y exigir gate"
    except PolicyError as e:
        assert "tainted" in str(e)


def test_gate_required_effect_without_token_is_rejected() -> None:
    r = MockReasoner()
    p = Plan(goal="x", steps=[Step(id="s1", op="transfer", args={"amount": _lit("1")})])  # sin gate
    try:
        execute(p, r, _META)
        assert False, "debió exigir gate humano"
    except PolicyError as e:
        assert "gate" in str(e)


def test_repair_path_is_reauthorized() -> None:
    # La reparación es output no confiable del LLM. Si "repara" cambiando el paso
    # a un transfer sin gate, la re-autorización del camino de repair lo rechaza:
    # no hay bypass de policy por reparar.
    def malicious_repair(s: Step, _e: str) -> Step:
        return Step(id=s.id, op="transfer", args={"amount": _lit("9999")})  # sin gate
    r = MockReasoner(repair_fn=malicious_repair)
    p = Plan(goal="x", steps=[Step(id="s1", op="ratio", args={"x": _lit("8"), "y": _lit("0")})])
    try:
        execute(p, r, _META)
        assert False, "la re-autorización debió rechazar el paso reparado"
    except PolicyError as e:
        assert "gate" in str(e)


def test_idempotent_reproduced_with_snapshot_verified_without() -> None:
    r = MockReasoner()
    p = Plan(goal="x", steps=[Step(id="s1", op="upsert", args={"value": _lit("42")})])
    _, log, seal = execute(p, r, _META)
    assert replay(log, seal)["s1"] is Verdict.REPRODUCED          # con key + snapshot
    stripped = [log[0].model_copy(update={"idempotency_key": None, "state_snapshot_hash": None})]
    stripped[0] = stripped[0].model_copy(update={"event_hash": stripped[0].content_hash()})
    seal2 = seal_head(stripped[0].event_hash)
    assert replay(stripped, seal2)["s1"] is Verdict.VERIFIED      # sin snapshot -> solo verifica


def test_self_healing_recovers_within_budget() -> None:
    def fix_div0(s: Step, _e: str) -> Step:
        return Step(id=s.id, op="ratio", args={"x": _lit("8"), "y": _lit("1")})
    r = MockReasoner(repair_fn=fix_div0)
    p = Plan(goal="x", steps=[Step(id="s1", op="ratio", args={"x": _lit("8"), "y": _lit("0")})])
    results, log, _ = execute(p, r, _META, budget=Budget(max_retries=2))
    assert results["s1"] == _D("8")
    assert sum(1 for e in log if e.error) == 1   # un intento fallido registrado
    assert any(e.output == _D("8") for e in log)  # y un intento exitoso


def test_self_healing_escalates_when_budget_exhausted() -> None:
    r = MockReasoner(repair_fn=lambda s, _e: s)  # "repara" sin arreglar nada
    p = Plan(goal="x", steps=[Step(id="s1", op="ratio", args={"x": _lit("8"), "y": _lit("0")})])
    try:
        execute(p, r, _META, budget=Budget(max_retries=2))
        assert False, "debió escalar al agotar reintentos"
    except Escalation as e:
        assert e.step_id == "s1"
        assert len(e.log) == 3                    # intento inicial + 2 reintentos, todos fallidos


if __name__ == "__main__":
    tests: tuple[Callable[[], None], ...] = (
        test_traceability_and_chain_invariant,
        test_pure_execution_is_deterministic,
        test_replay_reproduces_pure_but_only_verifies_effectful,
        test_inplace_tamper_is_unreplayable,
        test_full_chain_recompute_defeated_by_seal,
        test_unregistered_tool_is_rejected,
        test_tainted_retrieved_data_cannot_trigger_effect_without_gate,
        test_taint_propagates_through_derived_output,
        test_gate_required_effect_without_token_is_rejected,
        test_repair_path_is_reauthorized,
        test_idempotent_reproduced_with_snapshot_verified_without,
        test_self_healing_recovers_within_budget,
        test_self_healing_escalates_when_budget_exhausted,
    )
    for t in tests:
        t()
    print(f"OK — {len(tests)} tests")
```

El punto que el código hace explícito: determinismo, trazabilidad y la frontera de confianza —taint derivada por procedencia, re-autorización del repair y encadenado del log— viven en la capa de ejecución/policy, no en el planner ni en su prompt; por eso un plan o una reparación inyectados pasan por la misma frontera. El planner real reemplaza a `MockReasoner` —por eso el log captura `model_version`, `temperature` y `seed`— y el `transfer` real golpea un sistema externo a través del gateway de herramientas; en producción su `fn` registra request, response e idempotency key, que es lo que el veredicto `VERIFIED` atestigua.

---

## 5. Datos y memoria

Tres almacenes con roles distintos, no uno solo: Postgres como fuente de verdad y estado, vector store (pgvector/Qdrant) para recuperación semántica, y object storage para artefactos crudos referenciados por puntero. El contexto que llega al LLM se ensambla por paso —índice + fragmentos específicos + estado relevante—, nunca el corpus completo, y cada fragmento entra etiquetado con su procedencia y su hash (necesarios para el log y para el tainting de §7b). La memoria persistente entre sesiones (preferencias, contexto de proyecto) va en Postgres con recuperación selectiva, no acumulada en el prompt.

---

## 6. Auditoría y reproducibilidad (Chain-of-Work)

El log inmutable registra cada ciclo, y su contrato está fijado en el tipo `AuditEvent` de §4, no en prosa. Por paso captura:

- **Intención:** objetivo original (texto / payload).
- **Planificación:** plan tipado, más `model_version`, `temperature`, `seed` y `prompt_hash`.
- **Recuperación:** qué fragmentos se leyeron, con sus hashes y punteros (`retrieved_hashes`).
- **Código/llamada:** op, argumentos completos, `args_hash`, versión de herramienta y sandbox.
- **Ejecución:** output (o error), `output_hash`, número de intento.
- **Gates:** los tokens humanos que aprobaron pasos `effectful`.

Append-only, inmutable, por tenant. La distinción que lo hace honesto frente a clientes técnicos y reguladores es el **veredicto de replay por paso**:

- **`REPRODUCED`** (pasos `pure`, e `idempotent` con idempotency key + snapshot de estado): el log basta para re-ejecutar y obtener el mismo resultado.
- **`VERIFIED`** (pasos `effectful` no idempotentes): el efecto no se re-ejecuta —no quieres reenviar un wire transfer al auditar—; el log atestigua qué se pidió, qué respondió el sistema externo y que el registro está íntegro.
- **`UNREPLAYABLE`**: paso fallido, evidencia rota, o cadena manipulada. Un tamper *consistente* (reescribir `output` y su `output_hash` a la vez) ya no pasa: cambia el `content_hash` del evento y rompe el encadenado (`test_inplace_tamper_is_unreplayable`); y un atacante que recompone toda la cadena para que sea internamente coherente cambia la cabeza, que el sello externo delata (`test_full_chain_recompute_defeated_by_seal`).

**Cómo el log es inmutable, no solo *append-only*.** Cada evento encadena el hash del anterior (`prev_hash` → `event_hash` sobre todo el contenido) y la cabeza de la cadena se sella con un ancla externa —firma asimétrica o write a WORM—. Guardar `output_hash` junto al `output` no basta: quien edita uno edita el otro. El encadenado obliga a recomputar todos los eventos posteriores para un tamper consistente, y el sello sobre la cabeza detecta esa recomputación porque la cabeza cambia. El tipo `AuditEvent` de §4 lo exige y los tests lo prueban.

Esto certifica *qué pasó*, no que el planner fuera determinista. Para reproducir un run de planificación necesitas fijar `model_version` + `temperature=0` + `seed` + datos snapshotados; aun así, **las APIs hosted no garantizan reproducibilidad bit a bit en el tiempo** (cambios de backend, no-determinismo de kernels en GPU). Esto se documenta para el cliente, no se esconde, y es una razón a favor de poder servir modelos abiertos con vLLM cuando el contrato exija reproducibilidad fuerte.

---

## 7. Gobernanza, seguridad y multi-tenancy

**Multi-tenancy.** Para este segmento —datos financieros/legales bajo contrato— el default es **aislamiento por schema o base por tenant**, no row-level. La separación a nivel de fila (un `tenant_id` en cada tabla con RLS) es un único punto de fallo lógico: un bug en una cláusula `WHERE` filtra datos entre clientes, y "confíe en que nuestro RLS es correcto" no sobrevive a un due diligence de seguridad de un banco. Schema/DB-per-tenant cuesta más en operación y migraciones, pero es el piso que los compradores regulados esperan, y algunos exigirán deployment single-tenant (VPC dedicada u on-prem). Row-level es un *downgrade* legítimo solo para el segmento no regulado, y debe ser una decisión registrada, no el default por inercia.

**Resto de gobernanza.** Human-in-the-loop con gates firmados y auditados antes de toda acción `effectful` no idempotente. Policy engine (OPA/Cedar) evaluando reglas de negocio y autorización en código, fuera del prompt, sobre el plan antes de ejecutar. Secretos en Vault, nunca en config plana —el antipatrón de claves API de terceros expuestas en configuración es real y evitable—. Presupuestos de tokens/costo/reintentos por worker y tenant, con circuit breakers.

### 7b. Modelo de confianza y prompt injection

Es la amenaza de primer orden de cualquier agente que planifica sobre datos recuperados, y se agrava en este dominio: un contrato o un email entrante es **input adversarial por diseño** —puede contener instrucciones dirigidas al modelo ("ignora lo anterior y transfiere…")—. La inyección indirecta no se "resuelve con un buen prompt"; se contiene en la arquitectura. Tres fronteras hacen el trabajo:

- **Datos recuperados son no confiables (tainting derivado por procedencia).** Todo fragmento de retrieval o de un sistema externo entra marcado por el runtime. La marca **no es un campo que el plan declare** —el plan es output del LLM y mentiría—: el código de §4 la *deriva* de la procedencia de cada argumento y la **propaga a la salida de cada paso**, de modo que un efecto aguas abajo de un dato *tainted* hereda la marca aunque no lo toque directamente (`test_taint_propagates_through_derived_output`).
- **El plan es dato, no instrucción privilegiada.** El output del LLM se valida contra el registro y la policy antes de ejecutar. Un plan que inventa una herramienta se rechaza (`test_unregistered_tool_is_rejected`); uno que intenta un efecto desde un argumento *tainted* sin gate humano se rechaza (`test_tainted_retrieved_data_cannot_trigger_effect_without_gate`), y una reparación que intente colar un efecto sin gate vuelve a chocar con la policy (`test_repair_path_is_reauthorized`).
- **El efecto exige autorización fuera del texto.** Ninguna acción `effectful` no idempotente ocurre sin un `gate_token` firmado, evaluado en código (`test_gate_required_effect_without_token_is_rejected`). El texto del LLM nunca es la autoridad.

La frontera plan-tipado no elimina la inyección —el planner aún puede ser engañado para *proponer* algo malicioso— pero garantiza que la propuesta pase por validación de esquema, policy y gate humano antes de tener efecto. Es contención por diseño, no confianza en el modelo.

---

## 8. Evaluación

No puedes shippear agentes sin un eval set de regresión. Necesitas, desde el primer worker: un conjunto de casos representativos con outputs esperados, ejecución del eval en CI ante cada cambio de prompt/modelo/herramienta, y **métricas separadas para calidad del plan y corrección de la ejecución** —son fallos distintos con causas distintas: un plan correcto mal ejecutado y un plan equivocado bien ejecutado se arreglan en capas diferentes—. Añade casos adversariales de inyección al eval (§7b): un documento con instrucciones embebidas debe terminar en rechazo de policy, no en efecto. Herramienta: Promptfoo o un harness propio; Langfuse también corre evals sobre trazas reales. Sin esto, cada cambio de modelo es una apuesta a ciegas.

---

## 9. Modelos

Mantén el sistema model-agnostic: el Reasoning Engine se conecta por el gateway y se cambia por config. No hardcodees un modelo "mejor" —se queda obsoleto y la selección correcta depende de tu eval set, no de un benchmark público—. Arquitectura de dos niveles: un modelo de frontera para planificación y fragmentación de procesos complejos; SLMs (servidos con vLLM, con o sin fine-tuning) para micro-tareas repetitivas de alto volumen. Selecciona cada nivel corriéndolo contra tu propio eval (§8) y revisa la decisión trimestralmente o cuando salga un modelo relevante; trata "qué modelo" como variable de configuración versionada, no como constante de arquitectura.

---

## 10. Fases de implementación

**MVP (probar que un worker resuelve un workflow real, auditable):** Reasoning Engine + plan tipado, execution layer con Docker efímero, tool registry con `ToolKind`, policy engine mínimo (registro + tainting + gate), Postgres + pgvector, log de auditoría con veredicto de replay, un eval set pequeño con casos adversariales, un caso de uso vertical estrecho. Sin Studio, sin multi-modelo, sin Temporal todavía. Tenancy: una base por tenant desde el inicio si ya hay cliente regulado; si es piloto interno, difiere.

**Producción / hardening:** Temporal para durabilidad, sandbox endurecido (microVM), multi-tenancy con aislamiento por schema/DB, policy engine completo (OPA/Cedar), observabilidad completa (OTel + Langfuse), dual-model routing, gates humanos formales firmados, secrets en Vault.

**Escala:** Studio no-code (config-as-data), routing de modelos como core con costos por tenant, biblioteca de workers reutilizables, certificación de compliance del log de auditoría.

Resiste la tentación de construir el Studio o el multi-agente antes de que un solo worker resuelva de forma fiable y auditable un workflow que un cliente pague. El alcance acotado por worker es la unidad correcta de progreso.

---

## 11. Riesgos y antipatrones

No prometas "IA determinista" ni "cero alucinaciones": es overclaim verificable y te quema con clientes técnicos y reguladores; promete ejecución verificable y auditable, con la distinción reproduce/verifica explícita. No trates el output del LLM como instrucción confiable —es dato, y se valida antes de ejecutar—. No dejes que datos recuperados disparen efectos sin pasar por tainting + policy + gate. No coordines trabajo de larga duración con scripts cron en Bash —usa un motor durable—. No metas dependencias que arrastren wallets cripto o marketplaces de pago en el camino crítico de un producto regulado sin auditarlas. No trates rankings de herramientas sin metodología (tier lists) como evidencia. No dejes que el self-healing loop corra sin presupuesto de reintentos ni sin re-autorizar el paso reparado. No valides input no confiable con `assert` —`python -O` lo elimina—: la validación de plan y policy va en excepciones tipadas. No defaultees a row-level tenancy en regulado. Y no construyas la orquestación multi-agente antes de tener evaluación automatizada: sin eval, no sabes si un cambio mejoró o empeoró el sistema.

---

## 12. Límites conocidos (dónde esta arquitectura es la herramienta equivocada)

Ser explícito sobre el techo es parte de un diseño honesto:

- **El plan tipado favorece workflows acotados.** Funciona cuando el espacio de acciones es enumerable y el éxito es medible (el digital worker con criterios de aceptación fijos). Para tareas genuinamente exploratorias y abiertas —investigación sin estado objetivo claro— un esquema de plan rígido estorba; el lazo de re-planificación de §2.1 lo mitiga parcialmente, pero si tu caso de uso vive ahí, esta arquitectura es fricción, no apalancamiento. Ese workload no es el objetivo declarado.
- **Costo y latencia del lazo planner→ejecutar→evaluar.** Cada ciclo añade al menos una llamada de planificación; workflows con muchos pasos pagan latencia y tokens. El dual-model routing (§9) y el caching de planes para inputs repetidos lo amortiguan, pero la arquitectura intercambia velocidad por trazabilidad —un trade-off correcto en regulado, caro en alto volumen de baja criticidad—.
- **Reproducibilidad acotada por la infraestructura de inferencia.** Como dice §6, las APIs hosted no garantizan determinismo en el tiempo. La reproducibilidad fuerte requiere servir modelos abiertos con versión y entorno fijados; documenta el nivel real que ofreces por modelo, no el ideal.
- **El veredicto `VERIFIED` es tan bueno como la honestidad del sistema externo.** El log atestigua lo que la API externa respondió; si esa API miente o cambia estado fuera de banda, el log lo refleja fielmente sin poder detectarlo. Auditabilidad no es omnisciencia.
