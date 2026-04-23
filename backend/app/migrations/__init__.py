"""Migration engine — lifecycle, registry, diff. Engine code lands per-feature."""

from app.migrations.registry import (
    MIGRATION_TYPES,
    MigrationType,
    get_migration_type,
    known_providers,
    list_migration_types,
    register_migration_type,
)

__all__ = [
    "MIGRATION_TYPES",
    "MigrationType",
    "get_migration_type",
    "known_providers",
    "list_migration_types",
    "register_migration_type",
]
