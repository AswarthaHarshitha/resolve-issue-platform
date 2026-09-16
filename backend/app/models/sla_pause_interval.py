from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin


class SLAPauseInterval(UUIDPKMixin, TimestampMixin, Base):
    """One WAITING_FOR_USER pause window for an SLA record. Exists because a single
    pair of columns on sla_records can't represent multiple, independently
    auditable pause windows over an issue's lifetime (DECISIONS.md D11, D19).

    resumed_at is NULL while the pause is still open; at most one open interval can
    exist per sla_record at a time. Both invariants — no pause ending before it
    starts, and no two intervals for the same SLA record overlapping (which also
    subsumes "at most one open interval," since an open interval's range is treated
    as extending to infinity) — are enforced by the database itself rather than
    application code, via a CHECK constraint and a GiST exclusion constraint. The
    exclusion constraint requires the `btree_gist` extension, enabled in the initial
    migration."""

    __tablename__ = "sla_pause_intervals"
    __table_args__ = (
        CheckConstraint(
            "resumed_at IS NULL OR resumed_at >= paused_at",
            name="ck_sla_pause_intervals_valid_range",
        ),
        ExcludeConstraint(
            ("sla_record_id", "="),
            (
                text("tstzrange(paused_at, COALESCE(resumed_at, 'infinity'), '[]')"),
                "&&",
            ),
            using="gist",
            name="ex_sla_pause_intervals_no_overlap",
        ),
    )

    sla_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sla_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paused_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    sla_record: Mapped["SLARecord"] = relationship(back_populates="pause_intervals")
