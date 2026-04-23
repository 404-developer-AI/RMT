"""v1 foundation tables: registrar_credentials, migration_plans, domain_snapshots, audit_events

Revision ID: 0002_v1_foundation_tables
Revises: 0001_baseline
Create Date: 2026-04-23
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_v1_foundation_tables"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "registrar_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("api_base", sa.String(length=256), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("encrypted_api_secret", sa.Text(), nullable=True),
        sa.Column("masked_hint", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "label", name="uq_registrar_credentials_provider_label"),
    )
    op.create_index(
        "ix_registrar_credentials_provider",
        "registrar_credentials",
        ["provider"],
    )

    op.create_table(
        "migration_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("migration_type", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("diff", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provisioning_job_id", sa.String(length=128), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("correlation_id", name="uq_migration_plans_correlation_id"),
    )
    op.create_index("ix_migration_plans_correlation_id", "migration_plans", ["correlation_id"])
    op.create_index("ix_migration_plans_domain", "migration_plans", ["domain"])
    op.create_index("ix_migration_plans_migration_type", "migration_plans", ["migration_type"])
    op.create_index("ix_migration_plans_state", "migration_plans", ["state"])

    op.create_table(
        "domain_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("migration_plan_id", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["migration_plan_id"],
            ["migration_plans.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_domain_snapshots_migration_plan_id", "domain_snapshots", ["migration_plan_id"])
    op.create_index("ix_domain_snapshots_correlation_id", "domain_snapshots", ["correlation_id"])
    op.create_index("ix_domain_snapshots_domain", "domain_snapshots", ["domain"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("registrar", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_audit_events_ts", "audit_events", ["ts"])
    op.create_index("ix_audit_events_correlation_id", "audit_events", ["correlation_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_registrar", "audit_events", ["registrar"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_registrar", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_correlation_id", table_name="audit_events")
    op.drop_index("ix_audit_events_ts", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_domain_snapshots_domain", table_name="domain_snapshots")
    op.drop_index("ix_domain_snapshots_correlation_id", table_name="domain_snapshots")
    op.drop_index("ix_domain_snapshots_migration_plan_id", table_name="domain_snapshots")
    op.drop_table("domain_snapshots")

    op.drop_index("ix_migration_plans_state", table_name="migration_plans")
    op.drop_index("ix_migration_plans_migration_type", table_name="migration_plans")
    op.drop_index("ix_migration_plans_domain", table_name="migration_plans")
    op.drop_index("ix_migration_plans_correlation_id", table_name="migration_plans")
    op.drop_table("migration_plans")

    op.drop_index("ix_registrar_credentials_provider", table_name="registrar_credentials")
    op.drop_table("registrar_credentials")
