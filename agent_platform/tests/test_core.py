"""13 tests del invariante central (§4). `mypy --strict` limpio.

Demuestran, en código que *enforce* —no en prosa—, cinco propiedades:
(1) ejecución determinista y auditable, dinero en Decimal nunca float;
(2) replay con veredicto por paso según tipo de efecto;
(3) taint derivada por procedencia y propagada a salidas;
(4) camino de reparación re-autorizado;
(5) log tamper-evident: hash-encadenado y sellado con ancla externa.
"""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest

from agent_platform import (
    AuditEvent,
    Budget,
    Escalation,
    Lit,
    Meta,
    Plan,
    PolicyError,
    Ref,
    Step,
    Value,
    Verdict,
    execute,
    replay,
    seal_head,
    verify_chain,
)
from agent_platform.tools import _hash


def _D(x: str) -> Decimal:
    return Decimal(x)


def _lit(x: str) -> Lit:
    return Lit(value=_D(x))


_META = Meta(model_version="mock-1", temperature=0.0, seed=7, prompt_hash="p:abc",
             retrieved_hashes=("d:1", "d:2"), sandbox_version="fc:1.0")


class MockReasoner:
    model_version = "mock-1"
    temperature = 0.0
    seed: int | None = 7

    def __init__(self, repair_fn: Callable[[Step, str], Step] | None = None) -> None:
        self._repair = repair_fn or (lambda s, _e: s)  # por defecto NO arregla

    def plan(self, goal: str) -> Plan:
        return Plan(goal=goal, steps=[
            Step(id="s1", op="sum", args={"x": _lit("10"), "y": _lit("5")}),
            Step(id="s2", op="ratio", args={"x": _lit("30"), "y": _lit("4")}),
            Step(id="s3", op="transfer", args={"amount": _lit("100")}, gate_token="sig:alice"),
        ])

    def repair(self, step: Step, error: str) -> Step:
        return self._repair(step, error)


def test_traceability_and_chain_invariant() -> None:
    r = MockReasoner()
    plan = r.plan("demo")
    _, log, seal = execute(plan, r, _META)
    assert len(log) == len(plan.steps)
    assert {e.step_id for e in log} == {s.id for s in plan.steps}
    for e in log:  # metadatos de reproducibilidad presentes en cada evento (§6)
        assert e.model_version and e.prompt_hash and e.retrieved_hashes
        assert e.seed is not None and isinstance(e.temperature, float)
        assert e.tool_version and e.sandbox_version
    # la cadena entera verifica y el sello casa
    assert verify_chain(log, seal) == {"s1", "s2", "s3"}


def test_pure_execution_is_deterministic() -> None:
    r = MockReasoner()
    a, _, _ = execute(r.plan("demo"), r, _META)
    b, _, _ = execute(r.plan("demo"), r, _META)
    assert a == b == {"s1": _D("15"), "s2": _D("7.5"), "s3": _D("100")}


def test_replay_reproduces_pure_but_only_verifies_effectful() -> None:
    r = MockReasoner()
    _, log, seal = execute(r.plan("demo"), r, _META)
    v = replay(log, seal)
    assert v["s1"] is Verdict.REPRODUCED   # pure
    assert v["s2"] is Verdict.REPRODUCED   # pure
    assert v["s3"] is Verdict.VERIFIED     # effectful: NO se re-ejecuta, se atestigua


def test_inplace_tamper_is_unreplayable() -> None:
    # Tamper CONSISTENTE (output y output_hash a la vez) pero sin recomputar la
    # cadena: content_hash deja de casar -> UNREPLAYABLE. Mejora sobre v2, que
    # solo detectaba tampers inconsistentes.
    r = MockReasoner()
    _, log, seal = execute(r.plan("demo"), r, _META)
    bad = list(log)
    bad[2] = bad[2].model_copy(update={"output": _D("999"), "output_hash": _hash(_D("999"))})
    v = replay(bad, seal)
    assert v["s3"] is Verdict.UNREPLAYABLE


def test_full_chain_recompute_defeated_by_seal() -> None:
    # El atacante recompone TODA la cadena de forma internamente consistente.
    # La cabeza cambia y el sello (ancla externa) ya no valida -> detectado.
    r = MockReasoner()
    _, log, seal = execute(r.plan("demo"), r, _META)
    forged: list[AuditEvent] = []
    prev = "GENESIS"
    for e in log:
        upd = {"output": _D("999"), "output_hash": _hash(_D("999"))} if e.step_id == "s3" else {}
        e2 = e.model_copy(update={**upd, "prev_hash": prev})
        e2 = e2.model_copy(update={"event_hash": e2.content_hash()})
        forged.append(e2)
        prev = e2.event_hash
    # cadena internamente consistente...
    assert all(forged[i].prev_hash == (forged[i - 1].event_hash if i else "GENESIS")
               for i in range(len(forged)))
    # ...pero el sello original no casa con la nueva cabeza
    assert seal_head(prev) != seal
    assert replay(forged, seal)["s3"] is Verdict.UNREPLAYABLE


def test_unregistered_tool_is_rejected() -> None:
    r = MockReasoner()
    bad = Plan(goal="x", steps=[Step(id="s1", op="rm_rf", args={})])
    with pytest.raises(PolicyError, match="no registrada"):  # excepción tipada, no assert
        execute(bad, r, _META)


def test_tainted_retrieved_data_cannot_trigger_effect_without_gate() -> None:
    # Prompt injection indirecta: un dato recuperado (TAINTED) referenciado como
    # monto de transfer. El plan no puede declararse no-tainted: no existe el campo.
    r = MockReasoner()
    retrieved = {"doc_amount": Value(_D("5000"), tainted=True)}
    p = Plan(goal="x", steps=[
        Step(id="s1", op="transfer", args={"amount": Ref(source="doc_amount")}),  # sin gate
    ])
    with pytest.raises(PolicyError, match="tainted"):
        execute(p, r, _META, retrieved)


def test_taint_propagates_through_derived_output() -> None:
    # La taint VIAJA: s1 (pure) consume dato tainted; s2=transfer referencia la
    # salida de s1. Aunque s2 no toque el dato recuperado directamente, hereda la
    # taint y exige gate. Sin gate -> rechazo. Esto es lo que la prosa promete.
    r = MockReasoner()
    retrieved = {"doc_amount": Value(_D("5000"), tainted=True)}
    p = Plan(goal="x", steps=[
        Step(id="s1", op="sum", args={"x": Ref(source="doc_amount"), "y": _lit("0")}),
        Step(id="s2", op="transfer", args={"amount": Ref(source="s1")}),  # hereda taint de s1
    ])
    with pytest.raises(PolicyError, match="tainted"):
        execute(p, r, _META, retrieved)


def test_gate_required_effect_without_token_is_rejected() -> None:
    r = MockReasoner()
    p = Plan(goal="x", steps=[Step(id="s1", op="transfer", args={"amount": _lit("1")})])  # sin gate
    with pytest.raises(PolicyError, match="gate"):
        execute(p, r, _META)


def test_repair_path_is_reauthorized() -> None:
    # La reparación es output no confiable del LLM. Si "repara" cambiando el paso
    # a un transfer sin gate, la re-autorización del camino de repair lo rechaza:
    # no hay bypass de policy por reparar.
    def malicious_repair(s: Step, _e: str) -> Step:
        return Step(id=s.id, op="transfer", args={"amount": _lit("9999")})  # sin gate
    r = MockReasoner(repair_fn=malicious_repair)
    p = Plan(goal="x", steps=[Step(id="s1", op="ratio", args={"x": _lit("8"), "y": _lit("0")})])
    with pytest.raises(PolicyError, match="gate"):
        execute(p, r, _META)


def test_idempotent_reproduced_with_snapshot_verified_without() -> None:
    r = MockReasoner()
    p = Plan(goal="x", steps=[Step(id="s1", op="upsert", args={"value": _lit("42")})])
    _, log, seal = execute(p, r, _META)
    assert replay(log, seal)["s1"] is Verdict.REPRODUCED          # con key + snapshot
    stripped = [log[0].model_copy(update={"idempotency_key": None, "state_snapshot_hash": None})]
    stripped[0] = stripped[0].model_copy(update={"event_hash": stripped[0].content_hash()})
    seal2 = seal_head(stripped[0].event_hash)
    assert replay(stripped, seal2)["s1"] is Verdict.VERIFIED      # sin snapshot -> solo verifica


def test_self_healing_recovers_within_budget() -> None:
    def fix_div0(s: Step, _e: str) -> Step:
        return Step(id=s.id, op="ratio", args={"x": _lit("8"), "y": _lit("1")})
    r = MockReasoner(repair_fn=fix_div0)
    p = Plan(goal="x", steps=[Step(id="s1", op="ratio", args={"x": _lit("8"), "y": _lit("0")})])
    results, log, _ = execute(p, r, _META, budget=Budget(max_retries=2))
    assert results["s1"] == _D("8")
    assert sum(1 for e in log if e.error) == 1   # un intento fallido registrado
    assert any(e.output == _D("8") for e in log)  # y un intento exitoso


def test_self_healing_escalates_when_budget_exhausted() -> None:
    r = MockReasoner(repair_fn=lambda s, _e: s)  # "repara" sin arreglar nada
    p = Plan(goal="x", steps=[Step(id="s1", op="ratio", args={"x": _lit("8"), "y": _lit("0")})])
    with pytest.raises(Escalation) as exc_info:
        execute(p, r, _META, budget=Budget(max_retries=2))
    assert exc_info.value.step_id == "s1"
    assert len(exc_info.value.log) == 3           # intento inicial + 2 reintentos, todos fallidos


if __name__ == "__main__":
    tests: tuple[Callable[[], None], ...] = (
        test_traceability_and_chain_invariant,
        test_pure_execution_is_deterministic,
        test_replay_reproduces_pure_but_only_verifies_effectful,
        test_inplace_tamper_is_unreplayable,
        test_full_chain_recompute_defeated_by_seal,
        test_unregistered_tool_is_rejected,
        test_tainted_retrieved_data_cannot_trigger_effect_without_gate,
        test_taint_propagates_through_derived_output,
        test_gate_required_effect_without_token_is_rejected,
        test_repair_path_is_reauthorized,
        test_idempotent_reproduced_with_snapshot_verified_without,
        test_self_healing_recovers_within_budget,
        test_self_healing_escalates_when_budget_exhausted,
    )
    for t in tests:
        t()
    print(f"OK — {len(tests)} tests")
