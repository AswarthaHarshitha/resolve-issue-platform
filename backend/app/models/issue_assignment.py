from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPKMixin


class IssueAssignment(UUIDPKMixin, CreatedAtMixin, Base):
    """Append-only assignment history (DECISIONS.md D7) — never updated or
    overwritten. `issues.current_team_id`/`current_resolver_id` are a denormalized
    pointer to the latest row here, kept only for fast reads."""

    __tablename__ = "issue_assignments"

    issue_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    resolver_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    # Nullable: an AI-routed initial assignment has no human actor.
    assigned_by_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    issue: Mapped["Issue"] = relationship(back_populates="assignments")
    team: Mapped["Team"] = relationship()
    resolver: Mapped[Optional["User"]] = relationship(foreign_keys=[resolver_id])
    assigned_by: Mapped[Optional["User"]] = relationship(foreign_keys=[assigned_by_id])
