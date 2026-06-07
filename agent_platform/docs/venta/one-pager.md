# Agentes que pasan una auditoría

**Automatiza workflows regulados con IA que produce evidencia, no solo output.**

---

## El problema

Las organizaciones reguladas (banca, seguros, sector público, legal) ya saben que
la IA puede hacer el trabajo. Lo que las frena no es la capacidad del modelo: es
que **compliance y legal no pueden firmar el despliegue de una caja negra**. Un
LLM que "decide" no es auditable, puede inventar cifras y puede ser manipulado por
un documento entrante. Resultado: la IA se queda en pilotos que nunca llegan a
producción.

## La solución

Una plataforma de *digital workers* donde la estocasticidad del modelo se confina
a la planificación y **todo lo que tiene efecto es tipado, auditable y —donde el
tipo de efecto lo permite— reproducible**. Cada ejecución deja un **expediente
hash-encadenado, sellado e inmutable**: qué se hizo, con qué datos, qué cifras, y
qué humano lo firmó.

## Por qué es diferente (no es marketing, está en el código)

- **El LLM nunca calcula ni decide montos.** Produce un plan tipado que ejecuta
  código determinista → elimina la clase de error "el modelo se inventó la cifra".
- **Inyección contenida por diseño.** Un dato externo no confiable (un contrato,
  un email, una oferta) no puede disparar un efecto sin gate humano firmado —
  aunque traiga instrucciones embebidas.
- **Chain-of-Work verificable.** Log tamper-evident: editar un registro se detecta
  al recargar. Distinción honesta *reproduce ≠ verifica*: lo automático se
  re-ejecuta idéntico; lo subjetivo queda atestiguado con la firma humana.

## Caso de uso faro: licitaciones públicas (LCSP)

Redacción y evaluación de licitaciones con expediente defendible ante un recurso:
validación automática del pliego, puntuación económica reproducible, juicio de
valor asistido por IA (con la mesa firmando), y propuesta de adjudicación que
**nunca se dispara sin firma**. El mismo núcleo sirve para conciliación bancaria,
procesamiento de siniestros o revisión de contratos.

## Lo que NO prometemos

No decimos "IA determinista" ni "cero errores" — eso es overclaim y te quema en un
*due diligence*. Prometemos **ejecución verificable y auditable, con control humano
en lo irreversible**. Ser explícitos sobre el límite es lo que gana al comprador
regulado.

## Llamada a la acción

15 minutos de demo: te enseñamos un agente evaluando un caso real y, en directo,
**detectando una manipulación del expediente**. Ese es el momento en el que tu
director de riesgos se inclina hacia delante.
