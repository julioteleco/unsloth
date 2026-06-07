"""Demo de persistencia del Chain-of-Work: publicar -> guardar -> recargar -> re-verificar.

Simula el ciclo real: se publica un pliego (acto auditado), el expediente se
vuelca a un almacén durable y, tras un "reinicio", se recarga y se re-verifica
la cadena y el sello. Corre con:  make demo-persistencia
"""
from __future__ import annotations

from decimal import Decimal

from agent_platform import SqliteEventStore, Verdict, replay, verify_chain
from agent_platform.tenders import (
    Criterio,
    PliegoSpec,
    Procedimiento,
    TipoContrato,
    TipoCriterio,
    publicar,
)


def _spec() -> PliegoSpec:
    return PliegoSpec(
        objeto="Servicio de conservación de viales", cpv="45233141",
        tipo=TipoContrato.SERVICIOS, procedimiento=Procedimiento.ABIERTO,
        valor_estimado=Decimal("400000"), presupuesto_base=Decimal("200000"),
        plazo_ejecucion_meses=36, plazo_presentacion_dias=30,
        criterios=[
            Criterio(nombre="Precio", tipo=TipoCriterio.FORMULA, peso=Decimal("70")),
            Criterio(nombre="Calidad", tipo=TipoCriterio.JUICIO_VALOR, peso=Decimal("30")),
        ],
        condiciones_especiales=["Cláusula medioambiental (art. 202)"],
    )


def main() -> None:
    res = publicar(_spec(), gate_token="firma:organo-contratacion")
    print(f"Pliego publicado. Eventos en el expediente: {len(res.log)}")

    # Volcado durable (en prod: PostgresEventStore con un DSN real).
    store = SqliteEventStore(":memory:")
    store.guardar("LIC-2026-001", res.log, res.seal)
    print("Expediente guardado en el almacén durable.")

    # ... reinicio del sistema ...
    log, seal = store.cargar("LIC-2026-001")
    print(f"\nExpediente recargado: {len(log)} eventos.")
    intactos = verify_chain(log, seal)
    print(f"Pasos con evidencia íntegra: {sorted(intactos)}")
    print("Veredictos de replay tras recargar:")
    for step_id, v in replay(log, seal).items():
        marca = "✓" if v is not Verdict.UNREPLAYABLE else "✗"
        print(f"  {marca} {step_id}: {v.value}")


if __name__ == "__main__":
    main()
