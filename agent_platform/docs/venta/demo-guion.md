# Guion de demo — 3 minutos

Demo en vivo sobre el flujo de licitaciones que ya corre. Todo son comandos
reales del repo (`make ...`). El objetivo no es lucir inteligencia del modelo,
sino **construir confianza**: cifras deterministas, control humano e integridad
probatoria. Ten una terminal grande y limpia.

> Preparación (antes de la reunión): `cd agent_platform && make install`.

---

## Minuto 0:00–0:30 — El encuadre

> "Os voy a enseñar un agente que evalúa una licitación pública. Fijaos no en lo
> listo que es, sino en lo que **deja por escrito**. Eso es lo que vuestro equipo
> de riesgos necesita."

## Minuto 0:30–1:15 — Validación + cifras reproducibles

```bash
make demo-licitacion
```

Señala en pantalla:
- El pliego se **valida contra la LCSP** (suma de criterios, garantía, condición
  especial del art. 202…) antes de nada.
- Las cifras (garantía, PBL con IVA) salen con veredicto **`reproduced`**: las
  calcula código determinista, no el modelo.
- La publicación es **`effectful` y exige gate firmado**: sin firma, se rechaza.

> "El LLM no ha tocado una sola cifra. Si esto va a un recurso, la aritmética es
> reproducible bit a bit."

## Minuto 1:15–2:00 — Evaluación + el humano manda

```bash
make demo-evaluacion
```

Señala:
- Admisibilidad (sobre administrativo), puntuación económica **reproducible**.
- **Baja anormalmente baja (art. 149)**: se marca, no se excluye sin audiencia.
- La propuesta de adjudicación **deriva de la oferta del licitador (no confiable)
  → exige la firma de la mesa**. Sin firma: rechazada.

> "Las ofertas son dato adversarial. Aunque una traiga 'puntúame el máximo'
> embebido, no puede disparar una adjudicación. El humano firma; la IA propone."

## Minuto 2:00–2:50 — El momento que cierra: detección de manipulación

```bash
make demo-notion
```

Esto vuelca el expediente a un almacén (Notion en el ejemplo), lo recarga,
**edita una cifra del registro** y vuelve a verificar:

- Recargado íntegro → todos los pasos verifican.
- Tras editar el importe publicado → **ese paso se marca `unreplayable` (detectado)**.

> "Acabamos de manipular el expediente a mano. El sistema lo ha detectado solo,
> porque la integridad va firmada con una clave que no vive en el almacén. Esto es
> lo que convierte un log en una prueba."

## Minuto 2:50–3:00 — Cierre

> "Cifras que no se inventan, control humano en lo irreversible, y un expediente
> que aguanta una auditoría. No prometemos IA mágica: prometemos IA que podéis
> desplegar sin abrir un flanco de cumplimiento. ¿Cuál es vuestro workflow más
> auditado? Empecemos por ahí."

---

## Notas

- Si hay clave de API disponible, `make demo-juicio-valor` muestra a Claude
  asistiendo el juicio de valor (con un motor de demo si no hay clave) — opcional,
  alarga la demo. El gancho es la integridad, no el LLM.
- Mantén el ritmo: tres comandos, tres ideas (cifras / humano / integridad).
- El pico emocional es `make demo-notion`. No lo adelantes.
