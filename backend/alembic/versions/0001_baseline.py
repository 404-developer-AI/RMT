"""baseline — empty schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-22

Establishes the migration history. Real tables are added in later
revisions as features (audit log, migration plans, credential metadata)
are implemented.
"""
from __future__ import annotations

from collections.abc import Sequence


revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
