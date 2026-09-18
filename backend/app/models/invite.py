from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPKMixin


class Invite(UUIDPKMixin, CreatedAtMixin, Base):
    """An admin-issued, single-use invitation for someone to become a
    RESOLVER or ADMIN by setting their own password (DECISIONS.md D52) -
    never a path to USER, which stays self-registration-only (D23).

    Only `token_hash` (a SHA-256 digest) is ever persisted - the raw token
    exists only in the one API response returned to the inviting admin and
    in the activation link they share; it is never stored, logged, or
    recoverable from the database."""

    __tablename__ = "invites"

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    role_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    team_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=True
    )
    invited_by_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    role: Mapped["Role"] = relationship()
    team: Mapped[Optional["Team"]] = relationship()
    invited_by: Mapped["User"] = relationship()
