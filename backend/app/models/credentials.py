"""Encrypted-at-rest registrar credentials."""

from __future__ import annotations

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RegistrarCredential(Base, TimestampMixin):
    """API credentials for a single registrar account.

    Encrypted columns hold Fernet tokens (urlsafe-base64 ASCII), produced by
    :class:`app.security.encryption.CredentialCipher`. The plaintext is never
    stored or returned by the API — operators see only ``masked_hint`` and
    ``updated_at`` and rotate by clicking "Update" in the settings page.
    """

    __tablename__ = "registrar_credentials"
    __table_args__ = (
        UniqueConstraint("provider", "label", name="uq_registrar_credentials_provider_label"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    api_base: Mapped[str] = mapped_column(String(256), nullable=False)

    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_secret: Mapped[str | None] = mapped_column(Text, nullable=True)

    masked_hint: Mapped[str] = mapped_column(String(32), nullable=False)
