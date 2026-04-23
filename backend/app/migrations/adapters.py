"""Load configured adapter instances for a migration-type key.

The API layer calls :func:`load_adapters` when a wizard action needs to
touch a registrar. The helper pulls the right credential rows out of
``registrar_credentials``, decrypts them, instantiates the adapter
classes, and returns a ``(source, destination)`` tuple ready to use.

There is one credential per (provider, label) — if the operator has more
than one label for a provider (e.g. two GoDaddy accounts) the API accepts
an explicit ``*_label`` hint and otherwise falls back to the first one.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.migrations.registry import MigrationType, get_migration_type
from app.models import RegistrarCredential
from app.registrars import RegistrarAdapter, get_adapter_class
from app.security.encryption import EncryptionError, get_cipher


@dataclass(frozen=True)
class AdapterPair:
    """Source + destination adapter ready to drive one migration."""

    source: RegistrarAdapter
    destination: RegistrarAdapter
    migration_type: MigrationType


async def _load_credential(
    session: AsyncSession,
    provider: str,
    *,
    label: str | None,
) -> RegistrarCredential:
    stmt = select(RegistrarCredential).where(RegistrarCredential.provider == provider)
    if label is not None:
        stmt = stmt.where(RegistrarCredential.label == label)
    stmt = stmt.order_by(RegistrarCredential.id)
    result = await session.execute(stmt)
    row = result.scalars().first()
    if row is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                f"No credential configured for provider {provider!r}"
                + (f" with label {label!r}" if label else "")
                + ". Add one in Settings first."
            ),
        )
    return row


def _instantiate(row: RegistrarCredential, *, mock: bool) -> RegistrarAdapter:
    adapter_cls = get_adapter_class(row.provider)
    if adapter_cls is None:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Adapter for provider {row.provider!r} is not installed.",
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
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Stored credential could not be decrypted — APP_SECRET may have rotated."
            ),
        ) from exc
    return adapter_cls(
        api_key=api_key,
        api_secret=api_secret,
        api_base=row.api_base,
        mock=mock,
    )


async def load_adapters(
    session: AsyncSession,
    *,
    migration_type: str,
    source_label: str | None = None,
    destination_label: str | None = None,
    mock: bool = False,
) -> AdapterPair:
    """Return instantiated adapters for the given migration-type key."""
    try:
        mig_type = get_migration_type(migration_type)
    except KeyError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown migration type: {migration_type!r}",
        ) from exc

    source_row = await _load_credential(session, mig_type.source_provider, label=source_label)
    dest_row = await _load_credential(
        session, mig_type.destination_provider, label=destination_label
    )

    source = _instantiate(source_row, mock=mock)
    destination = _instantiate(dest_row, mock=mock)
    return AdapterPair(source=source, destination=destination, migration_type=mig_type)
