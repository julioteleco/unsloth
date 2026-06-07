"""Persistencia del Chain-of-Work (sistema de registro, §5).

El log hash-encadenado vive hoy en memoria; aquí se vuelca a un almacén durable
y se puede recargar para re-verificar la cadena y el sello DESPUÉS de un reinicio.
Eso es lo que convierte la auditoría en un expediente, no en un artefacto efímero.

Dos backends con el MISMO contrato (EventStore):
- SqliteEventStore: stdlib, cero dependencias, ejercitado por los tests.
- PostgresEventStore: el sistema de registro de la arquitectura (§3); misma
  interfaz, import perezoso de psycopg, para producción.

El almacén es append-only por run: re-guardar un run existente es un IntegrityError.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Protocol

from .contracts import AuditEvent
from .errors import IntegrityError

_DDL_EVENTOS = (
    "CREATE TABLE IF NOT EXISTS eventos ("
    "run_id TEXT NOT NULL, idx INTEGER NOT NULL, evento TEXT NOT NULL, "
    "PRIMARY KEY (run_id, idx))"
)
_DDL_SELLOS = "CREATE TABLE IF NOT EXISTS sellos (run_id TEXT PRIMARY KEY, seal TEXT NOT NULL)"


class EventStore(Protocol):
    def guardar(self, run_id: str, log: list[AuditEvent], seal: str) -> None: ...
    def cargar(self, run_id: str) -> tuple[list[AuditEvent], str]: ...


class SqliteEventStore:
    """Almacén durable sobre SQLite (stdlib). En producción regulada se usa
    PostgresEventStore; el contrato y el round-trip son idénticos."""

    def __init__(self, ruta: str = ":memory:") -> None:
        self._con = sqlite3.connect(ruta)
        self._con.execute(_DDL_EVENTOS)
        self._con.execute(_DDL_SELLOS)
        self._con.commit()

    def guardar(self, run_id: str, log: list[AuditEvent], seal: str) -> None:
        existe = self._con.execute("SELECT 1 FROM sellos WHERE run_id = ?", (run_id,)).fetchone()
        if existe is not None:
            raise IntegrityError(f"run '{run_id}' ya existe: el log es append-only")
        self._con.executemany(
            "INSERT INTO eventos (run_id, idx, evento) VALUES (?, ?, ?)",
            [(run_id, i, e.model_dump_json()) for i, e in enumerate(log)],
        )
        self._con.execute("INSERT INTO sellos (run_id, seal) VALUES (?, ?)", (run_id, seal))
        self._con.commit()

    def cargar(self, run_id: str) -> tuple[list[AuditEvent], str]:
        sello = self._con.execute("SELECT seal FROM sellos WHERE run_id = ?", (run_id,)).fetchone()
        if sello is None:
            raise IntegrityError(f"run '{run_id}' no encontrado")
        filas = self._con.execute(
            "SELECT evento FROM eventos WHERE run_id = ? ORDER BY idx", (run_id,)
        ).fetchall()
        log = [AuditEvent.model_validate_json(f[0]) for f in filas]
        seal: str = sello[0]
        return log, seal

    def cerrar(self) -> None:
        self._con.close()


class PostgresEventStore:
    """Mismo contrato sobre PostgreSQL (sistema de registro, §3/§5).

    Requiere `psycopg` y una base accesible (`pip install 'agent-platform-core[postgres]'`).
    No se ejercita en los tests porque no hay servidor; la lógica de (de)serialización
    es idéntica a SqliteEventStore.
    """

    def __init__(self, dsn: str) -> None:
        import psycopg  # dependencia opcional, import perezoso
        self._conn: Any = psycopg.connect(dsn)
        with self._conn.cursor() as cur:
            cur.execute(_DDL_EVENTOS)
            cur.execute(_DDL_SELLOS)
        self._conn.commit()

    def guardar(self, run_id: str, log: list[AuditEvent], seal: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1 FROM sellos WHERE run_id = %s", (run_id,))
            if cur.fetchone() is not None:
                raise IntegrityError(f"run '{run_id}' ya existe: el log es append-only")
            cur.executemany(
                "INSERT INTO eventos (run_id, idx, evento) VALUES (%s, %s, %s)",
                [(run_id, i, e.model_dump_json()) for i, e in enumerate(log)],
            )
            cur.execute("INSERT INTO sellos (run_id, seal) VALUES (%s, %s)", (run_id, seal))
        self._conn.commit()

    def cargar(self, run_id: str) -> tuple[list[AuditEvent], str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT seal FROM sellos WHERE run_id = %s", (run_id,))
            sello = cur.fetchone()
            if sello is None:
                raise IntegrityError(f"run '{run_id}' no encontrado")
            cur.execute("SELECT evento FROM eventos WHERE run_id = %s ORDER BY idx", (run_id,))
            log = [AuditEvent.model_validate_json(f[0]) for f in cur.fetchall()]
        seal: str = sello[0]
        return log, seal

    def cerrar(self) -> None:
        self._conn.close()


# === Notion como almacén (mirror / piloto) ================================
_NOTION_CHUNK = 1900  # < 2000: límite por segmento rich_text de Notion


def _trocear(texto: str, n: int = _NOTION_CHUNK) -> list[str]:
    return [texto[i:i + n] for i in range(0, len(texto), n)] or [""]


def _rich_text(texto: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": c}} for c in _trocear(texto)]


def _titulo(texto: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": texto}}]


def _leer_rich_text(prop: dict[str, Any]) -> str:
    segs = prop.get("rich_text", [])
    return "".join(s.get("plain_text") or s["text"]["content"] for s in segs)


class NotionEventStore:
    """EventStore sobre una base de datos de Notion (mismo contrato, drop-in).

    AVISO honesto: Notion es **mutable** y **no-WORM**. La tamper-evidence SÍ se
    mantiene —el sello se firma con una clave del runtime que NO se almacena en
    Notion, así que cualquier edición se detecta al recargar con `verify_chain`—,
    pero Notion no ofrece las garantías de inmutabilidad/disponibilidad de un WORM.
    Apto para pilotos, mirror de revisión y entornos no regulados; para expediente
    regulado, mantén Postgres/WORM como almacén autoritativo (§6/§7).

    La base debe tener estas propiedades: 'run' (title), 'idx' (number),
    'evento' (rich_text), 'hash' (rich_text). El evento se serializa a JSON y se
    trocea en segmentos de <2000 caracteres; el sello va en una fila con idx = -1.
    """

    def __init__(self, database_id: str, client: Any | None = None) -> None:
        if client is None:
            from notion_client import Client  # dependencia opcional [notion]
            client = Client(auth=os.environ["NOTION_TOKEN"])
        self._client: Any = client
        self._db = database_id

    def _filas(self, run_id: str) -> list[dict[str, Any]]:
        filas: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "database_id": self._db,
                "filter": {"property": "run", "title": {"equals": run_id}},
            }
            if cursor is not None:
                kwargs["start_cursor"] = cursor
            resp = self._client.databases.query(**kwargs)
            filas.extend(resp["results"])
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return filas

    def _crear_fila(self, run_id: str, idx: int, evento: str, etiqueta: str) -> None:
        self._client.pages.create(
            parent={"database_id": self._db},
            properties={
                "run": {"title": _titulo(run_id)},
                "idx": {"number": idx},
                "evento": {"rich_text": _rich_text(evento)},
                "hash": {"rich_text": _rich_text(etiqueta)},
            },
        )

    def guardar(self, run_id: str, log: list[AuditEvent], seal: str) -> None:
        if self._filas(run_id):
            raise IntegrityError(f"run '{run_id}' ya existe: el log es append-only")
        for i, e in enumerate(log):
            self._crear_fila(run_id, i, e.model_dump_json(), e.event_hash)
        self._crear_fila(run_id, -1, seal, "SELLO")

    def cargar(self, run_id: str) -> tuple[list[AuditEvent], str]:
        filas = self._filas(run_id)
        if not filas:
            raise IntegrityError(f"run '{run_id}' no encontrado")
        seal: str | None = None
        pares: list[tuple[int, str]] = []
        for f in filas:
            props = f["properties"]
            idx = int(props["idx"]["number"])
            texto = _leer_rich_text(props["evento"])
            if idx == -1:
                seal = texto
            else:
                pares.append((idx, texto))
        if seal is None:
            raise IntegrityError(f"run '{run_id}': falta el sello")
        pares.sort()
        log = [AuditEvent.model_validate_json(t) for _, t in pares]
        return log, seal
