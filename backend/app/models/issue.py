from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.models.enums import AIAnalysisStatus, IssuePriority, IssueStatus


class Issue(UUIDPKMixin, TimestampMixin, Base):
    """The central business entity. `status` (business lifecycle) and
    `ai_analysis_status` (AI pipeline state) are intentionally separate columns that
    are never conflated — see DECISIONS.md D2. category/sub_category/priority/
    current_team/current_resolver all start NULL at creation and are filled in by
    the (not-yet-implemented) RoutingService in a later phase; the AI never sets
    them directly (DECISIONS.md D4).

    current_team_id/current_resolver_id are a denormalized read-optimization over
    `issue_assignments`, which remains the append-only source of truth for
    assignment history (DECISIONS.md D7)."""

    __tablename__ = "issues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "sub_category_id"],
            ["sub_categories.category_id", "sub_categories.id"],
            name="fk_issues_category_sub_category",
        ),
        Index("ix_issues_current_team_status", "current_team_id", "status"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[IssueStatus] = mapped_column(
        Enum(
            IssueStatus,
            name="issue_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=IssueStatus.OPEN,
        index=True,
    )
    ai_analysis_status: Mapped[AIAnalysisStatus] = mapped_column(
        Enum(
            AIAnalysisStatus,
            name="ai_analysis_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=AIAnalysisStatus.PENDING,
        index=True,
    )
    priority: Mapped[Optional[IssuePriority]] = mapped_column(
        Enum(
            IssuePriority,
            name="issue_priority",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
        index=True,
    )

    category_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    sub_category_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    current_team_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    current_resolver_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])
    category: Mapped[Optional["Category"]] = relationship(foreign_keys=[category_id])
    sub_category: Mapped[Optional["SubCategory"]] = relationship(
        foreign_keys=[category_id, sub_category_id], overlaps="category"
    )
    current_team: Mapped[Optional["Team"]] = relationship(foreign_keys=[current_team_id])
    current_resolver: Mapped[Optional["User"]] = relationship(foreign_keys=[current_resolver_id])

    comments: Mapped[list["IssueComment"]] = relationship(
        back_populates="issue", order_by="IssueComment.created_at", cascade="all, delete-orphan"
    )
    status_history: Mapped[list["IssueStatusHistory"]] = relationship(
        back_populates="issue", order_by="IssueStatusHistory.created_at", cascade="all, delete-orphan"
    )
    assignments: Mapped[list["IssueAssignment"]] = relationship(
        back_populates="issue", order_by="IssueAssignment.created_at", cascade="all, delete-orphan"
    )
    sla_record: Mapped[Optional["SLARecord"]] = relationship(
        back_populates="issue", uselist=False, cascade="all, delete-orphan"
    )
