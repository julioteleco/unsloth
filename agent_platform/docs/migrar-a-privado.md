# Migrar `agent_platform` a un repositorio privado propio

`julioteleco/unsloth` es un **fork de un repo público**, y GitHub no permite
convertir en privado un fork desde los ajustes. La vía limpia —y la recomendable,
porque `agent_platform/` es tu producto y es autocontenido— es **extraerlo a su
propio repositorio privado**, con su historial y con el paquete en la raíz.

El script `scripts/migrar-a-privado.sh` lo automatiza.

## Requisitos (en tu equipo)

- `git` (incluye `git subtree`, sin dependencias extra).
- [`gh`](https://cli.github.com/) (GitHub CLI) autenticado: `gh auth login`.

## Uso

Desde la **raíz** del repo `unsloth` (donde está la carpeta `agent_platform/`):

```bash
agent_platform/scripts/migrar-a-privado.sh julioteleco/agent-platform
```

## Qué hace

1. `git subtree split --prefix=agent_platform` → una rama con `agent_platform/`
   como **raíz**, conservando el historial de esa subcarpeta.
2. `gh repo create julioteleco/agent-platform --private`.
3. `push` de la rama extraída a `main` del repo privado.
4. Reescribe en el nuevo repo las URLs/rutas de `README.md`/`INSTALL.md` (quita la
   subcarpeta y el `#subdirectory=agent_platform`) y avisa para que las revises.

## Después de migrar

```bash
# Clonar e instalar (ya sin subcarpeta):
git clone https://github.com/julioteleco/agent-platform.git
cd agent-platform && ./bootstrap.sh

# Como dependencia en otro proyecto:
pip install "agent-platform-core @ git+https://github.com/julioteleco/agent-platform.git"
```

- Revisa `README.md`/`INSTALL.md` del nuevo repo por si quedó alguna mención a la
  antigua subcarpeta `agent_platform/` (p. ej. la nota "el paquete vive en la
  subcarpeta…", que en el repo nuevo ya no aplica).
- El fork público `julioteleco/unsloth` puede **archivarse o borrarse** una vez
  confirmes que el privado está completo.
- Da acceso a tu equipo en *Settings → Collaborators* del repo privado.

## Alternativa sin extraer (todo el fork a privado)

Si prefieres llevar el fork entero a privado en vez de extraer solo el paquete,
duplica a un repo privado nuevo (no se puede togglear la visibilidad de un fork):

```bash
gh repo create julioteleco/unsloth-priv --private
git clone --bare https://github.com/julioteleco/unsloth.git
cd unsloth.git && git push --mirror https://github.com/julioteleco/unsloth-priv.git
```
