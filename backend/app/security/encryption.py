"""Fernet-based symmetric encryption for registrar credentials.

The Fernet key is derived from the operator-supplied ``APP_SECRET`` via
HKDF-SHA256. Deriving (rather than asking operators to paste a 44-char
url-safe-base64 key) keeps the install flow uniform: install.sh generates a
32-char alphanumeric secret the same way it generates the Postgres password,
and this module turns it into a valid Fernet key.

Rotating ``APP_SECRET`` invalidates every stored credential — the settings
page makes operators re-enter API keys on rotation. This module never
re-derives a key for a different secret silently; callers get an
``EncryptionError`` on decrypt failures and decide how to surface it.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import get_settings

# Static HKDF info string. Bumping the suffix is a deliberate key-domain
# rotation and would invalidate every stored ciphertext — do not change
# casually.
_HKDF_INFO = b"rmt-registrar-credentials-v1"
_HKDF_SALT = b"rmt-fernet-kdf-salt-v1"


class EncryptionError(RuntimeError):
    """Raised when encryption or decryption fails for any reason."""


def _derive_fernet_key(app_secret: str) -> bytes:
    """Derive a 44-byte url-safe-base64-encoded Fernet key from the secret.

    HKDF gives us a 32-byte uniformly-random key from any input entropy;
    Fernet then expects that 32-byte key url-safe-base64-encoded.
    """
    if not app_secret:
        raise EncryptionError(
            "APP_SECRET is not set. Set it in .env (install.sh generates one "
            "automatically on fresh installs)."
        )
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    ).derive(app_secret.encode("utf-8"))
    return base64.urlsafe_b64encode(derived)


class CredentialCipher:
    """Encrypts and decrypts short secret strings.

    Stateless apart from the cached Fernet instance. Construct once per
    process via :func:`get_cipher` and reuse.
    """

    def __init__(self, app_secret: str) -> None:
        self._fernet = Fernet(_derive_fernet_key(app_secret))

    def encrypt(self, plaintext: str) -> str:
        """Return the urlsafe-base64 Fernet token for ``plaintext``."""
        if not isinstance(plaintext, str):
            raise EncryptionError("encrypt() expects a str")
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("ascii")

    def decrypt(self, token: str) -> str:
        """Reverse :meth:`encrypt`. Raises :class:`EncryptionError` on bad input."""
        if not isinstance(token, str):
            raise EncryptionError("decrypt() expects a str")
        try:
            plaintext = self._fernet.decrypt(token.encode("ascii"))
        except InvalidToken as exc:
            raise EncryptionError(
                "Decryption failed — token is corrupt or APP_SECRET has rotated."
            ) from exc
        return plaintext.decode("utf-8")


def mask_hint(secret: str) -> str:
    """UI-safe trailing fingerprint: last 4 chars of the plaintext.

    Returned by the API so the operator can confirm which key is configured
    without ever exposing the secret. Short secrets fall back to a placeholder.
    """
    if not secret or len(secret) < 8:
        return "••••"
    return f"••••{secret[-4:]}"


_cipher: CredentialCipher | None = None


def get_cipher() -> CredentialCipher:
    """Process-wide singleton. Constructed lazily on first use."""
    global _cipher
    if _cipher is None:
        _cipher = CredentialCipher(get_settings().app_secret.get_secret_value())
    return _cipher


def reset_cipher_cache() -> None:
    """Drop the cached cipher. Used by tests that vary APP_SECRET."""
    global _cipher
    _cipher = None
