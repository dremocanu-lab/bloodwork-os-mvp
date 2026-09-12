"""At-rest encryption for InteropSecret.ciphertext.

Uses Fernet (AES-128-CBC + HMAC, from the `cryptography` package — already
an installed dependency of `python-jose[cryptography]`; pinned directly in
requirements.txt now that interop depends on it too) keyed by
INTEROP_SECRET_ENCRYPTION_KEY. This is deliberately NOT a full KMS —
key rotation is a single shared key today, not a versioned per-secret DEK —
but it is real symmetric encryption, not obfuscation, and secret plaintext
never touches the database, logs, or any API response.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.services.interop.flags import INTEROP_SECRET_ENCRYPTION_KEY


class InteropSecretConfigError(RuntimeError):
    """Raised when a secret operation is attempted without a configured
    encryption key. Fails closed — never falls back to storing plaintext."""


def _fernet() -> Fernet:
    if not INTEROP_SECRET_ENCRYPTION_KEY:
        raise InteropSecretConfigError(
            "INTEROP_SECRET_ENCRYPTION_KEY is not set. A secret-backed auth "
            "type cannot be configured until it is — this fails closed "
            "rather than storing secret material unencrypted."
        )
    # Fernet requires a 32-byte urlsafe-base64 key. Derive one deterministically
    # from whatever string is configured so operators can set a normal secret
    # string (as they do for SECRET_KEY) rather than needing to pre-generate
    # a Fernet-specific key.
    derived = hashlib.sha256(INTEROP_SECRET_ENCRYPTION_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise InteropSecretConfigError(
            "Stored secret could not be decrypted with the configured "
            "INTEROP_SECRET_ENCRYPTION_KEY — the key changed, or the "
            "ciphertext is corrupt."
        ) from exc
