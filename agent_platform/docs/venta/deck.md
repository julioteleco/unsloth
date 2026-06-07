# Deck de venta — 5 slides

Guion de presentación. Cada slide: titular grande + 2-3 ideas. Notas del ponente
en cursiva. Duración objetivo: 7-8 minutos antes de la demo.

---

## Slide 1 — Gancho

# Agentes que pasan una auditoría

IA para workflows regulados que produce **evidencia**, no solo output.

> *Apertura: "Todo el mundo os vende agentes autónomos. Nosotros os vendemos lo
> contrario: un agente que vuestro equipo de compliance va a aprobar."*

---

## Slide 2 — El problema (que el comprador siente)

# No es "¿puede la IA?". Es "¿lo firma legal?"

- La IA ya puede hacer el trabajo en banca, seguros, sector público, legal.
- El bloqueo real: **una caja negra no es auditable** → compliance lo veta.
- Tres miedos concretos: inventa cifras · la manipula un documento · no puedo
  justificar la decisión dentro de 2 años.

> *"¿Cuántos pilotos de IA tenéis parados porque riesgos no os deja pasar a
> producción?" — dejar que respondan.*

---

## Slide 3 — La solución (y la frase que la distingue)

# La estocasticidad se queda arriba; lo de abajo es verificable

- El LLM **planifica**; no calcula ni decide montos → adiós a la cifra inventada.
- Dato externo *tainted* → **no dispara efectos sin gate humano firmado**.
- Cada ejecución = **expediente hash-encadenado, sellado, inmutable**.
- La distinción honesta: **reproduce ≠ verifica**. Lo automático se re-ejecuta
  idéntico; lo subjetivo queda atestiguado con firma.

> *Aquí se gana al comprador técnico: "No prometemos IA determinista. Eso es
> mentira y lo sabéis. Prometemos ejecución verificable."*

---

## Slide 4 — El momento "ajá" (demo en vivo)

# Manipula el expediente. Mira cómo lo detectamos.

1. El agente evalúa unas ofertas → expediente.
2. Editamos a mano una cifra del registro.
3. "Verificar" → **paso marcado como NO fiable.**

> *No enseñes al agente "siendo listo". Enseña la prueba de manipulación. Ese es
> el slide que cierra. (En directo con `make demo-notion`.)*

---

## Slide 5 — Caso faro + siguiente paso

# Digital worker para licitaciones públicas (LCSP)

- Redacción y evaluación con **expediente defendible ante un recurso**.
- Mismo núcleo → conciliación bancaria, siniestros, revisión de contratos.
- Modelo: empezamos por **un worker vertical** que un cliente pague; el núcleo es
  reutilizable.

**Siguiente paso:** un piloto de 4-6 semanas sobre vuestro workflow más auditado.

> *Cierre: "Os proponemos un worker, un workflow, medible. Si no pasa vuestra
> auditoría interna, no pagáis."*
