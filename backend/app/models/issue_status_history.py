from typing import Optional
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPKMixin
from app.models.enums import IssueStatus, StatusChangeTrigger


class IssueStatusHistory(UUIDPKMixin, CreatedAtMixin, Base):
    """Append-only audit trail of the business-status state machine (DECISIONS.md
    D8). `previous_status` is NULL only for the row logging issue creation itself
    (trigger=SYSTEM_CREATE). `changed_by_id` is nullable because automated
    transitions (AI routing, a user's auto-resuming reply) have no human actor —
    `trigger` records why the change happened either way."""

    __tablename__ = "issue_status_history"

    issue_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    previous_status: Mapped[Optional[IssueStatus]] = mapped_column(
        Enum(
            IssueStatus,
            name="issue_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )
    new_status: Mapped[IssueStatus] = mapped_column(
        Enum(
            IssueStatus,
            name="issue_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    trigger: Mapped[StatusChangeTrigger] = mapped_column(
        Enum(
            StatusChangeTrigger,
            name="status_change_trigger",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    changed_by_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    issue: Mapped["Issue"] = relationship(back_populates="status_history")
    changed_by: Mapped[Optional["User"]] = relationship()
