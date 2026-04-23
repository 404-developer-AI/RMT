"""Read-only metadata endpoints — providers and migration types.

The UI calls these on page load to populate the credentials dropdown and the
migration-type selector. The lists are derived from the in-process
:mod:`app.migrations.registry`, so adding a new migration type is the only
change required to surface a new provider in the UI.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.migrations import known_providers, list_migration_types
from app.registrars import registered_providers

router = APIRouter(tags=["metadata"])


class ProviderInfo(BaseModel):
    """One entry in GET /providers."""

    key: str
    adapter_installed: bool


class MigrationTypeInfo(BaseModel):
    """One entry in GET /migration-types."""

    key: str
    label: str
    source_provider: str
    destination_provider: str
    description: str
    auth_code_hints: dict[str, str]


@router.get(
    "/providers",
    response_model=list[ProviderInfo],
    summary="Providers referenced by a registered migration type",
)
async def list_providers() -> list[ProviderInfo]:
    installed = set(registered_providers())
    return [
        ProviderInfo(key=p, adapter_installed=p in installed)
        for p in known_providers()
    ]


@router.get(
    "/migration-types",
    response_model=list[MigrationTypeInfo],
    summary="Registered source→destination migration types",
)
async def list_types() -> list[MigrationTypeInfo]:
    return [
        MigrationTypeInfo(
            key=t.key,
            label=t.label,
            source_provider=t.source_provider,
            destination_provider=t.destination_provider,
            description=t.description,
            auth_code_hints=dict(t.auth_code_hints),
        )
        for t in list_migration_types()
    ]
