"""Sello de la cadena de auditoría (ancla externa) — pluggable.

La cabeza del hash-chain se sella con un ancla externa para que un atacante no
pueda re-sellar tras recomputar la cadena. Dos anclas, mismo contrato (`Sealer`):

- `HmacSealer` (default, cero dependencias): ancla SIMÉTRICA. Modela una clave
  retenida o un WORM; el verificador necesita la MISMA clave que el firmante.
- `Ed25519Sealer` (opcional, `[crypto]`): ancla ASIMÉTRICA. El verificador solo
  necesita la clave PÚBLICA, así que un atacante con acceso total de lectura
  (clave pública + todos los datos) **no puede falsificar un sello**. Es la
  "firma asimétrica" que la arquitectura (§6) pide para reproducibilidad fuerte.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, Protocol


class Sealer(Protocol):
    def firmar(self, head: str) -> str: ...
    def verificar(self, head: str, seal: str) -> bool: ...


# === Ancla simétrica (HMAC) — default ====================================
_SIGNING_KEY = b"anchor-key-not-available-to-tamperer"


class HmacSealer:
    """Ancla simétrica. El verificador necesita la misma clave que el firmante."""

    def __init__(self, key: bytes = _SIGNING_KEY) -> None:
        self._key = key

    def firmar(self, head: str) -> str:
        return hmac.new(self._key, head.encode(), hashlib.sha256).hexdigest()[:16]

    def verificar(self, head: str, seal: str) -> bool:
        return hmac.compare_digest(self.firmar(head), seal)


_DEFAULT_SEALER: Sealer = HmacSealer()


def seal_head(head_hash: str) -> str:
    """Sello por defecto (HMAC). Se mantiene por compatibilidad; para producción
    regulada usa `Ed25519Sealer` y pásalo a `execute`/`verify_chain`/`replay`."""
    return _DEFAULT_SEALER.firmar(head_hash)


# === Ancla asimétrica (Ed25519) — opcional [crypto] ======================
class Ed25519Sealer:
    """Ancla asimétrica (firma Ed25519).

    El firmante necesita la clave privada; el verificador, solo la pública. Por
    eso un atacante que recompute toda la cadena (clave pública + datos completos)
    sigue sin poder producir un sello válido: no tiene la privada.

    Construye sin argumentos para generar un par nuevo, con `private_key` para
    firmar, o con `Ed25519Sealer.solo_verificacion(clave_publica_bytes)` para un
    verificador que jamás toca la clave privada.
    """

    def __init__(self, private_key: Any = None, public_key: Any = None) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        if private_key is None and public_key is None:
            private_key = Ed25519PrivateKey.generate()
        self._priv: Any = private_key
        self._pub: Any = public_key if public_key is not None else private_key.public_key()

    @classmethod
    def solo_verificacion(cls, clave_publica_bytes: bytes) -> Ed25519Sealer:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        return cls(public_key=Ed25519PublicKey.from_public_bytes(clave_publica_bytes))

    def clave_publica_bytes(self) -> bytes:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        pub: bytes = self._pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return pub

    def firmar(self, head: str) -> str:
        if self._priv is None:
            raise ValueError("este Ed25519Sealer es solo de verificación: no tiene clave privada")
        firma: bytes = self._priv.sign(head.encode())
        return firma.hex()

    def verificar(self, head: str, seal: str) -> bool:
        from cryptography.exceptions import InvalidSignature
        try:
            self._pub.verify(bytes.fromhex(seal), head.encode())
        except (InvalidSignature, ValueError):
            return False
        return True
