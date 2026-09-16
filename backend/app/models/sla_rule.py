from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.models.enums import IssuePriority


class SLARule(UUIDPKMixin, TimestampMixin, Base):
    """Deterministic (category, priority) -> SLA duration. Durations are stored as
    minutes, not fixed deadlines — the actual deadline is computed once, at
    sla_records creation time, from `now() + duration`. The AI never calculates or
    supplies these durations (see DECISIONS.md D6)."""

    __tablename__ = "sla_rules"
    __table_args__ = (
        UniqueConstraint("category_id", "priority", name="uq_sla_rules_category_priority"),
    )

    category_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    priority: Mapped[IssuePriority] = mapped_column(
        Enum(
            IssuePriority,
            name="issue_priority",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    first_response_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    category: Mapped["Category"] = relationship()
