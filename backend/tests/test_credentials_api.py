"""Tests for /api/credentials CRUD + /test endpoints."""

from __future__ import annotations

from httpx import AsyncClient


async def _create(
    client: AsyncClient,
    *,
    provider: str = "godaddy",
    label: str = "primary",
    api_key: str = "plaintext-api-key-1234",
    api_secret: str | None = "plaintext-api-secret-abcd",
    api_base: str = "https://api.example.invalid",
) -> dict[str, object]:
    resp = await client.post(
        "/api/credentials",
        json={
            "provider": provider,
            "label": label,
            "api_base": api_base,
            "api_key": api_key,
            "api_secret": api_secret,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_returns_masked_shape_only(
    client: AsyncClient, clean_credentials: None
) -> None:
    body = await _create(client)
    assert body["provider"] == "godaddy"
    assert body["label"] == "primary"
    assert body["masked_hint"] == "••••1234"
    assert body["has_api_secret"] is True
    # Plaintext must never leak into the response shape.
    assert "api_key" not in body
    assert "api_secret" not in body
    assert "encrypted_api_key" not in body


async def test_create_without_secret_reports_has_api_secret_false(
    client: AsyncClient, clean_credentials: None
) -> None:
    body = await _create(client, api_secret=None)
    assert body["has_api_secret"] is False


async def test_list_returns_all(client: AsyncClient, clean_credentials: None) -> None:
    await _create(client, provider="godaddy", label="one")
    await _create(client, provider="combell", label="two")
    resp = await client.get("/api/credentials")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    providers = {c["provider"] for c in body}
    assert providers == {"godaddy", "combell"}


async def test_unknown_provider_rejected(
    client: AsyncClient, clean_credentials: None
) -> None:
    resp = await client.post(
        "/api/credentials",
        json={
            "provider": "not-a-registered-provider",
            "label": "nope",
            "api_base": "https://x",
            "api_key": "irrelevant-key-value",
        },
    )
    assert resp.status_code == 400
    assert "Unknown provider" in resp.json()["detail"]


async def test_duplicate_provider_label_rejected(
    client: AsyncClient, clean_credentials: None
) -> None:
    await _create(client, provider="godaddy", label="shared")
    resp = await client.post(
        "/api/credentials",
        json={
            "provider": "godaddy",
            "label": "shared",
            "api_base": "https://x",
            "api_key": "irrelevant-key-value",
        },
    )
    assert resp.status_code == 409


async def test_update_rotates_masked_hint(
    client: AsyncClient, clean_credentials: None
) -> None:
    body = await _create(client, api_key="original-key-wxyz")
    assert body["masked_hint"] == "••••wxyz"
    resp = await client.put(
        f"/api/credentials/{body['id']}",
        json={"api_key": "rotated-key-5678"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["masked_hint"] == "••••5678"


async def test_update_without_api_key_keeps_hint(
    client: AsyncClient, clean_credentials: None
) -> None:
    body = await _create(client, api_key="keep-me-quiet-0000")
    resp = await client.put(
        f"/api/credentials/{body['id']}",
        json={"label": "renamed"},
    )
    assert resp.status_code == 200
    assert resp.json()["masked_hint"] == "••••0000"
    assert resp.json()["label"] == "renamed"


async def test_update_with_no_fields_is_rejected(
    client: AsyncClient, clean_credentials: None
) -> None:
    body = await _create(client)
    resp = await client.put(f"/api/credentials/{body['id']}", json={})
    assert resp.status_code == 400


async def test_delete_removes_row(client: AsyncClient, clean_credentials: None) -> None:
    body = await _create(client)
    resp = await client.delete(f"/api/credentials/{body['id']}")
    assert resp.status_code == 204
    resp = await client.get(f"/api/credentials/{body['id']}")
    assert resp.status_code == 404


async def test_test_connection_returns_uniform_shape_on_failure(
    client: AsyncClient, clean_credentials: None
) -> None:
    """A registrar unreachable from the test environment returns 200 + ok=False.

    The endpoint must never propagate a raw exception — the settings page
    relies on the uniform ``{ok, error}`` shape to render any failure.
    """
    body = await _create(client, provider="godaddy")
    resp = await client.post(f"/api/credentials/{body['id']}/test")
    assert resp.status_code == 200
    result = resp.json()
    assert result["ok"] is False
    assert result["error"]  # a human-readable message, not None
