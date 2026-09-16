from typing import Optional
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, ForeignKeyConstraint, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPKMixin
from app.models.enums import AIAnalysisResultStatus, IssuePriority


class AIAnalysisResult(UUIDPKMixin, CreatedAtMixin, Base):
    """Append-only record of every AI classification attempt for an issue,
    including manual reanalysis (DECISIONS.md D13). Deliberately deferred
    from Phase 2 (D19) to land with AI classification itself, here in
    Phase 5.

    `raw_*` fields preserve exactly what the AI said, even when validation
    rejected it - required for D5's "never fabricate a result" and so an
    admin can see why an attempt failed. `matched_*` fields are populated
    only when that raw value was successfully validated against real
    database configuration (DECISIONS.md D17-style composite FK for the
    matched category/sub_category pair, same integrity guarantee as
    `issues` and `routing_rules`)."""

    __tablename__ = "ai_analysis_results"
    __table_args__ = (
        UniqueConstraint("issue_id", "attempt_number", name="uq_ai_analysis_results_issue_attempt"),
        ForeignKeyConstraint(
            ["matched_category_id", "matched_sub_category_id"],
            ["sub_categories.category_id", "sub_categories.id"],
            name="fk_ai_analysis_results_matched_category_sub_category",
        ),
    )

    issue_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AIAnalysisResultStatus] = mapped_column(
        Enum(
            AIAnalysisResultStatus,
            name="ai_analysis_result_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    raw_category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_sub_category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_priority: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    matched_category_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    matched_sub_category_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    matched_priority: Mapped[Optional[IssuePriority]] = mapped_column(
        Enum(
            IssuePriority,
            name="issue_priority",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    issue: Mapped["Issue"] = relationship()
    matched_category: Mapped[Optional["Category"]] = relationship(foreign_keys=[matched_category_id])
    matched_sub_category: Mapped[Optional["SubCategory"]] = relationship(
        foreign_keys=[matched_category_id, matched_sub_category_id], overlaps="matched_category"
    )
