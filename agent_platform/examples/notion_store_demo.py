"""Demo de NotionEventStore (offline, con un cliente de Notion falso).

Muestra el expediente volcado a una "base de Notion" y recargado para
re-verificar la cadena, y cómo una edición de una fila se detecta al recargar.
Usa un cliente falso para correr sin NOTION_TOKEN ni red; en producción:

    from agent_platform import NotionEventStore
    store = NotionEventStore(database_id="...")   # NOTION_TOKEN en el entorno

Corre con:  make demo-notion
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from agent_platform import NotionEventStore, Verdict, replay, verify_chain
from agent_platform.tenders import (
    Criterio,
    PliegoSpec,
    Procedimiento,
    TipoContrato,
    TipoCriterio,
    publicar,
)


# --- Cliente de Notion falso (imita el shape del SDK notion-client) -------
class _FakePages:
    def __init__(self, store: list[dict[str, Any]]) -> None:
        self._store = store

    def create(self, parent: object, properties: dict[str, Any]) -> dict[str, Any]:
        pagina = {"properties": properties}
        self._store.append(pagina)
        return pagina


class _FakeDatabases:
    def __init__(self, store: list[dict[str, Any]]) -> None:
        self._store = store

    def query(self, **kwargs: Any) -> dict[str, Any]:
        run = kwargs["filter"]["title"]["equals"]
        res = [p for p in self._store
               if p["properties"]["run"]["title"][0]["text"]["content"] == run]
        return {"results": res, "has_more": False, "next_cursor": None}


class _FakeNotion:
    def __init__(self) -> None:
        self._store: list[dict[str, Any]] = []
        self.pages = _FakePages(self._store)
        self.databases = _FakeDatabases(self._store)


def _spec() -> PliegoSpec:
    return PliegoSpec(
        objeto="Servicio de conservación de zonas verdes", cpv="77310000",
        tipo=TipoContrato.SERVICIOS, procedimiento=Procedimiento.ABIERTO,
        valor_estimado=Decimal("300000"), presupuesto_base=Decimal("150000"),
        plazo_ejecucion_meses=36, plazo_presentacion_dias=30,
        criterios=[
            Criterio(nombre="Precio", tipo=TipoCriterio.FORMULA, peso=Decimal("70")),
            Criterio(nombre="Calidad", tipo=TipoCriterio.JUICIO_VALOR, peso=Decimal("30")),
        ],
        condiciones_especiales=["Inserción laboral y cláusula medioambiental (art. 202)"],
    )


def main() -> None:
    res = publicar(_spec(), gate_token="firma:organo-contratacion-2026")
    fake = _FakeNotion()
    store = NotionEventStore("db-demo", client=fake)
    store.guardar("LIC-2026-VERDES", res.log, res.seal)
    print(f"Expediente volcado a Notion: {len(fake._store)} filas (eventos + sello).")

    log, seal = store.cargar("LIC-2026-VERDES")
    print("\n=== Recargado desde Notion (íntegro) ===")
    print(f"  cadena intacta: {sorted(verify_chain(log, seal))}")
    for k, v in replay(log, seal).items():
        print(f"  {k}: {v.value}")

    # Alguien edita una fila en Notion: el importe publicado 181500 -> 999999.
    for pagina in fake._store:
        seg = pagina["properties"]["evento"]["rich_text"][0]["text"]
        if '"output":"181500.00"' in seg["content"] and "publicar" in seg["content"]:
            seg["content"] = seg["content"].replace('"output":"181500.00"', '"output":"999999.00"')
    log2, seal2 = store.cargar("LIC-2026-VERDES")
    print("\n=== Tras editar la fila publicar_pliego en Notion ===")
    print(f"  cadena intacta: {sorted(verify_chain(log2, seal2))}")
    v = replay(log2, seal2)["publicar_pliego"]
    print(f"  publicar_pliego: {v.value}  "
          f"({'detectado' if v is Verdict.UNREPLAYABLE else 'NO detectado'})")


if __name__ == "__main__":
    main()
