from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin


class SLARecord(UUIDPKMixin, TimestampMixin, Base):
    """The SLA instance for one issue (one-to-one via the unique issue_id). Deadlines
    are computed once, at creation, from the applicable sla_rule's durations, and
    stored as fixed timestamps rather than recomputed later.

    `accumulated_pause_seconds` is a maintained cache — always re-derivable by
    summing completed rows in `sla_pause_intervals` for this record, which is the
    source of truth (see DECISIONS.md D19). It exists purely so an at-risk/breach
    check doesn't need to aggregate the pause table on every read."""

    __tablename__ = "sla_records"

    issue_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("issues.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    sla_rule_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sla_rules.id", ondelete="RESTRICT"), nullable=False
    )

    sla_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_response_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolution_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    first_response_met_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_met_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    accumulated_pause_seconds: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    issue: Mapped["Issue"] = relationship(back_populates="sla_record")
    sla_rule: Mapped["SLARule"] = relationship()
    pause_intervals: Mapped[list["SLAPauseInterval"]] = relationship(
        back_populates="sla_record",
        order_by="SLAPauseInterval.paused_at",
        cascade="all, delete-orphan",
    )
