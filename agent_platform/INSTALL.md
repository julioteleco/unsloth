# Instalación local

Requisitos: **Python 3.11+** (y opcionalmente `make`).

## 1. Entorno virtual + núcleo

```bash
cd agent_platform
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .                                       # núcleo (solo pydantic)
```

Esto instala el núcleo y deja disponible el comando de consola **`licita`**.

## 2. Extras opcionales

Instala solo lo que necesites (combinables: `pip install -e ".[dev,crypto]"`):

| Extra | Para qué | Trae |
|---|---|---|
| `dev` | Desarrollo y CI | `pytest`, `mypy`, `ruff`, `cryptography` |
| `crypto` | Sello asimétrico `Ed25519Sealer` | `cryptography` |
| `llm` | Planner y juicio de valor con Claude | `anthropic` |
| `postgres` | `PostgresEventStore` (sistema de registro) | `psycopg` |
| `notion` | `NotionEventStore` (almacén/mirror) | `notion-client` |

```bash
pip install -e ".[dev,crypto,llm,postgres,notion]"     # todo
```

## 3. Variables de entorno (solo para los extras en uso)

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # llm: ClaudePlanner / EvaluadorAnthropic
export NOTION_TOKEN=ntn_...                # notion: NotionEventStore
# PostgresEventStore recibe el DSN como argumento: PostgresEventStore("postgresql://...")
```

> **Seguridad en producción.** El sello por defecto es un HMAC con clave de
> ejemplo (`_SIGNING_KEY`). Para uso real, usa `Ed25519Sealer` (custodia la clave
> privada fuera del almacén) y pásalo a `execute`/`verify_chain`/`replay`. No
> dejes la clave de ejemplo.

## 4. Comprobar la instalación

```bash
make check            # ruff + mypy --strict + pytest   (requiere [dev])
make demo-licitacion  # o: demo-evaluacion / demo-persistencia / demo-notion / demo-juicio-valor

# CLI: valida un pliego en JSON contra la LCSP (exit 0 conforme, 1 errores, 2 entrada inválida)
licita validar mi_pliego.json
```

Sin `make`, los equivalentes son `pytest -q`, `mypy`, `ruff check src tests examples`
y `python examples/<demo>.py`.

## 5. Uso como librería

```python
from decimal import Decimal
from agent_platform import execute, replay, Ed25519Sealer
from agent_platform.tenders import PliegoSpec, validar, publicar
# ... ver README.md y docs/
```

## Build de distribución (opcional)

```bash
pip install build && python -m build      # genera dist/*.whl y *.tar.gz (hatchling)
```
