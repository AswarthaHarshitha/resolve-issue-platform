from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin


class User(UUIDPKMixin, TimestampMixin, Base):
    """Password hashing and JWT issuance are Phase 3 concerns; Phase 2 only models
    the column. Users are never hard-deleted (see DECISIONS.md D15) — `is_active`
    is the supported way to deactivate an account without breaking history that
    references this row (owned issues, comments, status changes, assignments)."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    role_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Nullable: only resolvers are expected to have a team. That constraint is
    # enforced in the Phase 3 service layer, not the database — see DECISIONS.md D18.
    team_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    role: Mapped["Role"] = relationship()
    team: Mapped[Optional["Team"]] = relationship()
