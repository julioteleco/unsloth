"""Tests del ancla externa: HMAC (default) y Ed25519 (firma asimétrica).

La propiedad clave de Ed25519: el verificador solo necesita la clave PÚBLICA, así
que un atacante que recompute toda la cadena (con la pública y todos los datos)
sigue sin poder falsificar un sello — no tiene la privada.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agent_platform import (
    AuditEvent,
    Ed25519Sealer,
    HmacSealer,
    Lit,
    Meta,
    Plan,
    Step,
    Verdict,
    execute,
    replay,
    verify_chain,
)

# Ed25519Sealer importa cryptography de forma perezosa al instanciarse; si no
# está disponible, saltamos todo el módulo.
pytest.importorskip("cryptography")


class _Reasoner:
    model_version = "s-1"
    temperature = 0.0
    seed: int | None = 0

    def plan(self, goal: str) -> Plan:
        return Plan(goal=goal, steps=[])

    def repair(self, step: Step, error: str) -> Step:
        return step


_META = Meta(model_version="s-1", temperature=0.0, seed=0, prompt_hash="p",
             retrieved_hashes=(), sandbox_version="n/a")


def _lit(x: str) -> Lit:
    return Lit(value=Decimal(x))


def _plan() -> Plan:
    return Plan(goal="demo", steps=[
        Step(id="s1", op="sum", args={"x": _lit("10"), "y": _lit("5")}),
        Step(id="s2", op="transfer", args={"amount": _lit("100")}, gate_token="sig:alice"),
    ])


def test_hmac_sigue_siendo_el_default() -> None:
    # Sin sealer explícito: HMAC, comportamiento idéntico al anterior.
    _, log, seal = execute(_plan(), _Reasoner(), _META)
    assert verify_chain(log, seal) == {"s1", "s2"}
    assert replay(log, seal)["s1"] is Verdict.REPRODUCED


def test_ed25519_firma_y_verifica_con_solo_la_clave_publica() -> None:
    firmante = Ed25519Sealer()
    _, log, seal = execute(_plan(), _Reasoner(), _META, sealer=firmante)
    # El verificador NUNCA toca la clave privada: solo la pública.
    verificador = Ed25519Sealer.solo_verificacion(firmante.clave_publica_bytes())
    assert verify_chain(log, seal, verificador) == {"s1", "s2"}
    v = replay(log, seal, verificador)
    assert v["s1"] is Verdict.REPRODUCED
    assert v["s2"] is Verdict.VERIFIED


def test_ed25519_verificador_no_puede_firmar() -> None:
    verificador = Ed25519Sealer.solo_verificacion(Ed25519Sealer().clave_publica_bytes())
    with pytest.raises(ValueError, match="solo de verificaci"):
        verificador.firmar("cualquier-cabeza")


def test_ed25519_tamper_inplace_se_detecta() -> None:
    firmante = Ed25519Sealer()
    _, log, seal = execute(_plan(), _Reasoner(), _META, sealer=firmante)
    verificador = Ed25519Sealer.solo_verificacion(firmante.clave_publica_bytes())
    bad = list(log)
    bad[1] = bad[1].model_copy(update={"output": Decimal("999"),
                                       "output_hash": bad[1].output_hash})
    assert "s2" not in verify_chain(bad, seal, verificador)
    assert replay(bad, seal, verificador)["s2"] is Verdict.UNREPLAYABLE


def test_ed25519_falsificacion_imposible_sin_clave_privada() -> None:
    # El atacante recompone TODA la cadena de forma consistente y la re-firma con
    # SU PROPIA clave. El verificador solo tiene la pública legítima -> el sello
    # forjado no valida y nada es de fiar. Esto NO lo da el HMAC simétrico.
    firmante = Ed25519Sealer()
    _, log, _seal = execute(_plan(), _Reasoner(), _META, sealer=firmante)
    verificador = Ed25519Sealer.solo_verificacion(firmante.clave_publica_bytes())

    atacante = Ed25519Sealer()  # clave distinta, no la del firmante
    forged: list[AuditEvent] = []
    prev = "GENESIS"
    for e in log:
        upd = {"output": Decimal("999"), "output_hash": e.output_hash} if e.step_id == "s2" else {}
        e2 = e.model_copy(update={**upd, "prev_hash": prev})
        e2 = e2.model_copy(update={"event_hash": e2.content_hash()})
        forged.append(e2)
        prev = e2.event_hash
    sello_forjado = atacante.firmar(prev)  # cadena internamente consistente y re-firmada

    # ...pero el verificador legítimo lo rechaza: no es la clave correcta.
    assert verify_chain(forged, sello_forjado, verificador) == set()
    assert replay(forged, sello_forjado, verificador)["s2"] is Verdict.UNREPLAYABLE


def test_hmac_sealer_explicito_equivale_al_default() -> None:
    _, log, seal = execute(_plan(), _Reasoner(), _META, sealer=HmacSealer())
    assert verify_chain(log, seal) == {"s1", "s2"}  # default también HMAC
