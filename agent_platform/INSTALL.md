# Instalación local

Requisitos: **Python 3.11+** (y opcionalmente `make`).

> El paquete vive en la subcarpeta `agent_platform/` del repositorio. Todos los
> comandos de abajo se ejecutan **dentro de esa carpeta**.

## Desde otro equipo (recomendado)

### Opción A — un solo comando (clonar + instalar + verificar)

```bash
git clone https://github.com/julioteleco/unsloth.git
cd unsloth/agent_platform
./bootstrap.sh            # núcleo + dev, crea .venv y corre los checks
./bootstrap.sh full       # además: crypto, llm, postgres, notion
```

`bootstrap.sh` comprueba la versión de Python, crea el entorno virtual, instala
el paquete y ejecuta `ruff + mypy --strict + pytest` y un smoke test del CLI.

### Opción B — instalar directamente desde git (sin clonar)

```bash
pip install "agent-platform-core @ git+https://github.com/julioteleco/unsloth.git#subdirectory=agent_platform"
# con extras:
pip install "agent-platform-core[crypto,llm] @ git+https://github.com/julioteleco/unsloth.git#subdirectory=agent_platform"
```

Útil para usarlo como dependencia en otro proyecto. Tras instalar, tendrás el
comando `licita` y podrás `import agent_platform`.

## Instalación manual (paso a paso)

### 1. Entorno virtual + núcleo

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

El wheel resultante (`agent_platform_core-*.whl`) es instalable en cualquier
equipo con `pip install agent_platform_core-*.whl` e incluye el subpaquete
`tenders`, el marcador `py.typed` y el comando `licita`.

## Solución de problemas

- **`ModuleNotFoundError: No module named 'agent_platform'`** — no activaste el
  entorno (`source .venv/bin/activate`) o no instalaste desde `agent_platform/`.
- **`cryptography` / `_cffi_backend` (Ed25519)** — si el sistema trae una
  `cryptography` antigua o rota, instala una moderna en el venv:
  `pip install -U cryptography`. Sin el extra `crypto`, el núcleo funciona igual
  (usa el sello HMAC por defecto) y los tests de Ed25519 se omiten solos.
- **El comando `licita` no aparece** — reinstala tras activar el venv
  (`pip install -e .`); el script se crea en `.venv/bin/`.
- **Tests de LLM/Notion** — pasan sin claves: usan dobles de prueba. Solo
  `EvaluadorAnthropic`/`ClaudePlanner`/`NotionEventStore` reales necesitan
  `ANTHROPIC_API_KEY` / `NOTION_TOKEN`.

## Reproducibilidad

`pyproject.toml` fija rangos de versiones. Para un despliegue reproducible,
congela las versiones exactas tras instalar:

```bash
pip freeze > requirements.lock        # y versiona este archivo
# en el otro equipo:  pip install -r requirements.lock
```
