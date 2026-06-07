"""Demo end-to-end del núcleo: planificar -> validar -> ejecutar -> auditar -> replay.

Corre con:  python examples/demo.py   (desde la carpeta agent_platform/, con
src/ en el PYTHONPATH, o tras `pip install -e .`).
"""
from __future__ import annotations

from decimal import Decimal

from agent_platform import (
    Lit,
    Meta,
    Plan,
    PolicyError,
    Ref,
    Step,
    Value,
    execute,
    replay,
    verify_chain,
)


class DemoReasoner:
    """Planner mockeado: en producción es un LLM detrás del model gateway."""
    model_version = "demo-1"
    temperature = 0.0
    seed: int | None = 7

    def plan(self, goal: str) -> Plan:
        return Plan(goal=goal, steps=[
            Step(id="s1", op="sum", args={"x": Lit(value=Decimal("10")), "y": Lit(value=Decimal("5"))}),
            Step(id="s2", op="ratio", args={"x": Lit(value=Decimal("30")), "y": Lit(value=Decimal("4"))}),
            Step(id="s3", op="transfer", args={"amount": Lit(value=Decimal("100"))},
                 gate_token="sig:alice"),
        ])

    def repair(self, step: Step, error: str) -> Step:
        return step


META = Meta(model_version="demo-1", temperature=0.0, seed=7, prompt_hash="p:demo",
            retrieved_hashes=("d:1",), sandbox_version="fc:1.0")


def main() -> None:
    reasoner = DemoReasoner()
    plan = reasoner.plan("liquidar factura")

    results, log, seal = execute(plan, reasoner, META)
    print("=== Resultados ===")
    for step_id, amount in results.items():
        print(f"  {step_id}: {amount}")

    print("\n=== Cadena de auditoría (Chain-of-Work) ===")
    intact = verify_chain(log, seal)
    for e in log:
        ok = "OK" if e.step_id in intact else "ROTA"
        print(f"  {e.step_id:>3} {e.op:>9} kind={e.kind.value:<10} out={e.output} [{ok}]")

    print("\n=== Veredicto de replay por paso ===")
    for step_id, verdict in replay(log, seal).items():
        print(f"  {step_id}: {verdict.value}")

    print("\n=== Prompt injection indirecta bloqueada por policy ===")
    retrieved = {"doc_amount": Value(Decimal("5000"), tainted=True)}
    injected = Plan(goal="x", steps=[
        Step(id="bad", op="transfer", args={"amount": Ref(source="doc_amount")}),  # sin gate
    ])
    try:
        execute(injected, reasoner, META, retrieved)
        print("  ERROR: no debió ejecutarse")
    except PolicyError as exc:
        print(f"  RECHAZADO: {exc}")


if __name__ == "__main__":
    main()
