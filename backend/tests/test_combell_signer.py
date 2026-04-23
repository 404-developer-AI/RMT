"""Combell HMAC signer tests.

The vectors are computed from the spec rather than copied from a Combell
document — the test re-derives the expected HMAC under fixed timestamp and
nonce values, so any drift between the signer and the spec we encoded
fails noisily. Live cross-checks against Combell happen in the integration
suite once the adapter lands.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from dataclasses import FrozenInstanceError

import pytest

from app.registrars.combell.signer import (
    CombellSigner,
    SignedRequest,
    _content_hash,
    _percent_encode_uppercase,
)

# Deterministic 16-byte secret → base64 form is what an operator would paste.
SECRET_BYTES = bytes(range(16))
API_KEY = "fixture-apikey"
API_SECRET = base64.b64encode(SECRET_BYTES).decode("ascii")


def _expected_signature(string_to_sign: str) -> str:
    digest = hmac.new(
        SECRET_BYTES, string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def _signer() -> CombellSigner:
    return CombellSigner(api_key=API_KEY, api_secret=API_SECRET)


# --- Path encoding ---------------------------------------------------------


def test_path_encoding_uses_uppercase_hex() -> None:
    encoded = _percent_encode_uppercase("/v2/dns/example.com/records")
    assert encoded == "%2Fv2%2Fdns%2Fexample.com%2Frecords"
    assert not re.search(r"%[0-9a-f][0-9a-f]", encoded), "found lowercase escape"


def test_path_encoding_preserves_unreserved_chars() -> None:
    encoded = _percent_encode_uppercase("/v2/dns/sub-domain.example.com/records")
    # Letters, digits, '-', '.', '_', '~' are unreserved and must pass through.
    assert "sub-domain.example.com" in encoded
    assert "records" in encoded


def test_path_encoding_encodes_query_string_separators() -> None:
    encoded = _percent_encode_uppercase("/v2/domains?status=active&take=50")
    assert encoded == "%2Fv2%2Fdomains%3Fstatus%3Dactive%26take%3D50"


# --- Content hash ----------------------------------------------------------


def test_content_hash_empty_body_returns_empty() -> None:
    assert _content_hash(None) == ""
    assert _content_hash(b"") == ""


def test_content_hash_matches_md5_then_base64() -> None:
    body = b'{"name":"example.com"}'
    expected = base64.b64encode(
        hashlib.md5(body, usedforsecurity=False).digest()
    ).decode("ascii")
    assert _content_hash(body) == expected


# --- Construction ----------------------------------------------------------


def test_empty_api_key_rejected() -> None:
    with pytest.raises(ValueError, match="api_key"):
        CombellSigner(api_key="", api_secret=API_SECRET)


def test_empty_api_secret_rejected() -> None:
    with pytest.raises(ValueError, match="api_secret"):
        CombellSigner(api_key=API_KEY, api_secret="")


def test_invalid_base64_secret_rejected() -> None:
    with pytest.raises(ValueError, match="not valid base64"):
        CombellSigner(api_key=API_KEY, api_secret="not!valid!base64!@#")


# --- Sign() core behaviour ------------------------------------------------


def test_sign_get_no_body_matches_spec() -> None:
    result = _signer().sign(
        method="GET",
        path="/v2/domains",
        timestamp="1700000000",
        nonce="fixed-nonce-1234",
    )
    string_to_sign = (
        API_KEY + "get" + "%2Fv2%2Fdomains" + "1700000000" + "fixed-nonce-1234"
    )
    expected_sig = _expected_signature(string_to_sign)
    assert result.content == ""
    assert result.authorization == (
        f"hmac {API_KEY}:{expected_sig}:fixed-nonce-1234:1700000000"
    )


def test_sign_post_with_body_includes_md5_content() -> None:
    body = b'{"auth_code":"abc-123","registrant":{}}'
    result = _signer().sign(
        method="POST",
        path="/v2/domains/transfers",
        body=body,
        timestamp="1700000000",
        nonce="nonce-xyz",
    )
    expected_content = base64.b64encode(
        hashlib.md5(body, usedforsecurity=False).digest()
    ).decode("ascii")
    string_to_sign = (
        API_KEY
        + "post"
        + "%2Fv2%2Fdomains%2Ftransfers"
        + "1700000000"
        + "nonce-xyz"
        + expected_content
    )
    expected_sig = _expected_signature(string_to_sign)
    assert result.content == expected_content
    assert result.authorization == (
        f"hmac {API_KEY}:{expected_sig}:nonce-xyz:1700000000"
    )


def test_method_is_lowercased_in_signature_input() -> None:
    """Whether the caller passes 'GET' or 'get', the signature is the same."""
    a = _signer().sign("GET", "/v2/x", timestamp="1", nonce="n")
    b = _signer().sign("get", "/v2/x", timestamp="1", nonce="n")
    assert a.authorization == b.authorization


# --- Sensitivity: any input change ⇒ signature change ---------------------


def test_signature_changes_with_method() -> None:
    a = _signer().sign("GET", "/v2/domains", timestamp="1", nonce="n")
    b = _signer().sign("POST", "/v2/domains", timestamp="1", nonce="n")
    assert a.authorization != b.authorization


def test_signature_changes_with_path() -> None:
    a = _signer().sign("GET", "/v2/domains", timestamp="1", nonce="n")
    b = _signer().sign("GET", "/v2/dns/example.com/records", timestamp="1", nonce="n")
    assert a.authorization != b.authorization


def test_signature_changes_with_body() -> None:
    a = _signer().sign("POST", "/v2/x", body=b"a", timestamp="1", nonce="n")
    b = _signer().sign("POST", "/v2/x", body=b"b", timestamp="1", nonce="n")
    assert a.authorization != b.authorization


def test_signature_changes_with_timestamp() -> None:
    a = _signer().sign("GET", "/v2/x", timestamp="1", nonce="n")
    b = _signer().sign("GET", "/v2/x", timestamp="2", nonce="n")
    assert a.authorization != b.authorization


def test_signature_changes_with_nonce() -> None:
    a = _signer().sign("GET", "/v2/x", timestamp="1", nonce="n1")
    b = _signer().sign("GET", "/v2/x", timestamp="1", nonce="n2")
    assert a.authorization != b.authorization


# --- Defaults --------------------------------------------------------------


def test_default_timestamp_is_recent_unix() -> None:
    before = int(time.time())
    result = _signer().sign("GET", "/v2/x")
    after = int(time.time())
    assert before <= int(result.timestamp) <= after


def test_default_nonce_is_unique_per_call() -> None:
    nonces = {_signer().sign("GET", "/v2/x").nonce for _ in range(50)}
    assert len(nonces) == 50


# --- Header shape ----------------------------------------------------------


def test_authorization_header_format() -> None:
    result = _signer().sign("GET", "/v2/x", timestamp="1700000000", nonce="abc")
    assert result.authorization.startswith("hmac ")
    payload = result.authorization.removeprefix("hmac ")
    apikey, signature, nonce, ts = payload.split(":")
    assert apikey == API_KEY
    assert nonce == "abc"
    assert ts == "1700000000"
    # base64 of 32 raw bytes is 44 chars including '=' padding.
    assert len(signature) == 44
    assert signature.endswith("=")


def test_signed_request_is_frozen() -> None:
    sr = SignedRequest(authorization="hmac x:y:z:w", timestamp="1", nonce="n", content="")
    with pytest.raises(FrozenInstanceError):
        sr.timestamp = "2"  # type: ignore[misc]
