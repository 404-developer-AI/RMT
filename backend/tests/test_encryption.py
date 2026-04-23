"""Tests for the Fernet credential cipher."""

from __future__ import annotations

import pytest

from app.security.encryption import (
    CredentialCipher,
    EncryptionError,
    mask_hint,
)

# A 32-char alphanumeric string mirrors what install.sh's gen_password() produces.
APP_SECRET_A = "abcdefghijklmnopqrstuvwxyz012345"
APP_SECRET_B = "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"


def test_round_trip() -> None:
    cipher = CredentialCipher(APP_SECRET_A)
    plaintext = "godaddy-api-key-fixture"
    token = cipher.encrypt(plaintext)
    assert token != plaintext
    assert cipher.decrypt(token) == plaintext


def test_two_encryptions_of_same_plaintext_differ() -> None:
    """Fernet uses a random IV — same plaintext encrypts to different tokens."""
    cipher = CredentialCipher(APP_SECRET_A)
    assert cipher.encrypt("same") != cipher.encrypt("same")


def test_decrypt_with_different_secret_fails() -> None:
    """Rotating APP_SECRET must invalidate previously stored ciphertexts."""
    token = CredentialCipher(APP_SECRET_A).encrypt("plaintext")
    with pytest.raises(EncryptionError, match="Decryption failed"):
        CredentialCipher(APP_SECRET_B).decrypt(token)


def test_empty_secret_rejected() -> None:
    with pytest.raises(EncryptionError, match="APP_SECRET is not set"):
        CredentialCipher("")


def test_decrypt_garbage_fails_cleanly() -> None:
    cipher = CredentialCipher(APP_SECRET_A)
    with pytest.raises(EncryptionError, match="Decryption failed"):
        cipher.decrypt("not-a-valid-fernet-token")


def test_encrypt_rejects_non_string() -> None:
    cipher = CredentialCipher(APP_SECRET_A)
    with pytest.raises(EncryptionError):
        cipher.encrypt(b"bytes")  # type: ignore[arg-type]


def test_mask_hint_short_secret() -> None:
    assert mask_hint("") == "••••"
    assert mask_hint("short") == "••••"


def test_mask_hint_normal_secret() -> None:
    assert mask_hint("sk_live_abcdef1234567890") == "••••7890"
