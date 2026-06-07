"""Sello de la cadena de auditoría (ancla externa).

En prod esto es una FIRMA asimétrica o un write a WORM: el atacante no puede
re-sellar. Aquí un HMAC con clave retenida modela ese ancla. El hash-chain
obliga a recomputar toda la cadena para un tamper consistente; el sello sobre
la cabeza detecta esa recomputación porque la cabeza cambia.
"""
from __future__ import annotations

import hashlib
import hmac

_SIGNING_KEY = b"anchor-key-not-available-to-tamperer"


def seal_head(head_hash: str) -> str:
    return hmac.new(_SIGNING_KEY, head_hash.encode(), hashlib.sha256).hexdigest()[:16]
