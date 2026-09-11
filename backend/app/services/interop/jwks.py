"""RSA keypair generation + JWKS export for SMART Backend Services (P6/P24).

Bragi acts as the OAuth client when connecting outbound to a partner FHIR
server, so partners need Bragi's PUBLIC key (registered as a JWKS, or given
out of band) to verify the client-assertion JWTs Bragi signs with its
PRIVATE key. The private key itself is stored the same way any other
connector secret is (InteropSecret, encrypted at rest) — see
auth_providers.SmartBackendServicesAuthProvider.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_keypair() -> tuple[str, str]:
    """Returns (private_key_pem, public_jwk) for a fresh 2048-bit RSA key."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")

    public_numbers = private_key.public_key().public_numbers()

    def _b64url_uint(value: int) -> str:
        length = (value.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode("ascii")

    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS384",
        "n": _b64url_uint(public_numbers.n),
        "e": _b64url_uint(public_numbers.e),
    }
    return private_pem, jwk
