"""Registrar-credential management — CRUD + test-connection.

Plaintext API keys are only accepted on write (POST/PUT) and are never
returned. Reads expose ``masked_hint`` (last-4 chars of the key) plus
``has_api_secret`` so the operator can confirm which credential is stored
without ever seeing the secret.

The Fernet cipher (:mod:`app.security.encryption`) handles encryption at
rest; this router simply calls it and persists the resulting token.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logging import get_logger
from app.migrations import known_providers
from app.models import RegistrarCredential
from app.registrars import get_adapter_class
from app.security.encryption import EncryptionError, get_cipher, mask_hint

logger = get_logger(__name__)
router = APIRouter(prefix="/credentials", tags=["credentials"])

# Hard cap on test_connection — operators expect the button to resolve in
# seconds, not minutes. Network failures bubble up as "unreachable".
_TEST_CONNECTION_TIMEOUT_SECONDS = 15.0


# --- schemas ----------------------------------------------------------------


class CredentialOut(BaseModel):
    """Safe read shape — never contains plaintext."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    label: str
    api_base: str
    masked_hint: str
    has_api_secret: bool
    created_at: datetime
    updated_at: datetime


class CredentialCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    api_base: str = Field(min_length=1, max_length=256)
    api_key: str = Field(min_length=1)
    api_secret: str | None = None


class CredentialUpdate(BaseModel):
    """All fields optional — only ``model_fields_set`` are applied.

    Re-sending ``api_key`` rotates the stored ciphertext and updates
    ``masked_hint``. Omitting it leaves the previous key intact. The
    secret follows the same rule. To clear a stored ``api_secret``, delete
    the credential and recreate — simpler than overloading the same field
    with "null means clear" semantics.
    """

    label: str | None = Field(default=None, min_length=1, max_length=128)
    api_base: str | None = Field(default=None, min_length=1, max_length=256)
    api_key: str | None = Field(default=None, min_length=1)
    api_secret: str | None = Field(default=None, min_length=1)


class TestConnectionResult(BaseModel):
    """Shape returned by POST /credentials/{id}/test."""

    ok: bool
    error: str | None = None


# --- helpers ----------------------------------------------------------------


def _to_out(row: RegistrarCredential) -> CredentialOut:
    return CredentialOut(
        id=row.id,
        provider=row.provider,
        label=row.label,
        api_base=row.api_base,
        masked_hint=row.masked_hint,
        has_api_secret=row.encrypted_api_secret is not None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _load(session: AsyncSession, credential_id: int) -> RegistrarCredential:
    row = await session.get(RegistrarCredential, credential_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Credential not found")
    return row


def _ensure_known_provider(provider: str) -> None:
    """Reject provider strings that no migration-type references.

    Keeps the table tidy and catches typos — an operator cannot accidentally
    save a key under ``godadd`` and then wonder why it never loads.
    """
    if provider not in known_providers():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown provider {provider!r}. "
                f"Known providers: {', '.join(sorted(known_providers()))}"
            ),
        )


# --- endpoints --------------------------------------------------------------


@router.get("", response_model=list[CredentialOut], summary="List credentials (masked)")
async def list_credentials(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CredentialOut]:
    result = await session.execute(
        select(RegistrarCredential).order_by(RegistrarCredential.id)
    )
    return [_to_out(row) for row in result.scalars()]


@router.get(
    "/{credential_id}",
    response_model=CredentialOut,
    summary="Get one credential (masked)",
)
async def get_credential(
    credential_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CredentialOut:
    row = await _load(session, credential_id)
    return _to_out(row)


@router.post(
    "",
    response_model=CredentialOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new credential",
)
async def create_credential(
    payload: CredentialCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CredentialOut:
    _ensure_known_provider(payload.provider)
    cipher = get_cipher()

    row = RegistrarCredential(
        provider=payload.provider,
        label=payload.label,
        api_base=payload.api_base,
        encrypted_api_key=cipher.encrypt(payload.api_key),
        encrypted_api_secret=(
            cipher.encrypt(payload.api_secret) if payload.api_secret else None
        ),
        masked_hint=mask_hint(payload.api_key),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"A credential with provider={payload.provider!r} and "
                f"label={payload.label!r} already exists."
            ),
        ) from exc
    await session.refresh(row)
    logger.info(
        "credentials.created",
        credential_id=row.id,
        provider=row.provider,
        label=row.label,
    )
    return _to_out(row)


@router.put(
    "/{credential_id}",
    response_model=CredentialOut,
    summary="Update a credential (partial)",
)
async def update_credential(
    credential_id: Annotated[int, Path(ge=1)],
    payload: CredentialUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CredentialOut:
    row = await _load(session, credential_id)
    fields_set = payload.model_fields_set
    if not fields_set:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Update requires at least one field.",
        )

    if "label" in fields_set and payload.label is not None:
        row.label = payload.label
    if "api_base" in fields_set and payload.api_base is not None:
        row.api_base = payload.api_base

    cipher = get_cipher()
    if "api_key" in fields_set and payload.api_key is not None:
        row.encrypted_api_key = cipher.encrypt(payload.api_key)
        row.masked_hint = mask_hint(payload.api_key)
    if "api_secret" in fields_set and payload.api_secret is not None:
        row.encrypted_api_secret = cipher.encrypt(payload.api_secret)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Update conflicts with another credential's (provider, label) pair.",
        ) from exc
    await session.refresh(row)
    logger.info(
        "credentials.updated",
        credential_id=row.id,
        fields=sorted(fields_set),
    )
    return _to_out(row)


@router.delete(
    "/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a credential",
)
async def delete_credential(
    credential_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    row = await _load(session, credential_id)
    await session.delete(row)
    await session.commit()
    logger.info("credentials.deleted", credential_id=credential_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{credential_id}/test",
    response_model=TestConnectionResult,
    summary="Test that the stored credential can reach its registrar",
)
async def test_credential_connection(
    credential_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TestConnectionResult:
    row = await _load(session, credential_id)

    adapter_cls = get_adapter_class(row.provider)
    if adapter_cls is None:
        # Keep the {ok, error} shape uniform so the UI can render any failure
        # the same way — explicit 200 here, not 501, to match the endpoint
        # contract consumers already code against.
        return TestConnectionResult(
            ok=False,
            error=(
                f"No adapter is installed for provider {row.provider!r} yet. "
                "This endpoint will work once the concrete adapter ships."
            ),
        )

    try:
        cipher = get_cipher()
        api_key = cipher.decrypt(row.encrypted_api_key)
        api_secret = (
            cipher.decrypt(row.encrypted_api_secret)
            if row.encrypted_api_secret is not None
            else None
        )
    except EncryptionError as exc:
        logger.warning(
            "credentials.decrypt_failed",
            credential_id=credential_id,
            error=str(exc),
        )
        return TestConnectionResult(
            ok=False,
            error=(
                "Stored credential could not be decrypted. "
                "APP_SECRET may have rotated — re-enter the credential."
            ),
        )

    adapter = adapter_cls(
        api_key=api_key,
        api_secret=api_secret,
        api_base=row.api_base,
    )

    try:
        ok = await asyncio.wait_for(
            adapter.test_connection(),
            timeout=_TEST_CONNECTION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.info(
            "credentials.test_connection.timeout",
            credential_id=credential_id,
            provider=row.provider,
        )
        return TestConnectionResult(
            ok=False,
            error=(
                f"Timed out after {_TEST_CONNECTION_TIMEOUT_SECONDS:.0f}s. "
                "Check network and api_base."
            ),
        )
    except Exception as exc:  # adapter-implementation bug — surface the message
        logger.warning(
            "credentials.test_connection.error",
            credential_id=credential_id,
            provider=row.provider,
            error=str(exc),
        )
        return TestConnectionResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    logger.info(
        "credentials.test_connection",
        credential_id=credential_id,
        provider=row.provider,
        ok=ok,
    )
    return TestConnectionResult(ok=ok, error=None if ok else "Registrar rejected the credentials.")
