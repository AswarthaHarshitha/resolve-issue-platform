from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin


class RoutingRule(UUIDPKMixin, TimestampMixin, Base):
    """Deterministic category(/sub_category) -> team mapping, configured in the
    database rather than as Python if/else (see PROJECT_CONTEXT.md, DECISIONS.md D4).

    sub_category_id is nullable: a rule with sub_category_id=NULL is a category-level
    catch-all; a rule with it set applies to that specific sub-category only. The two
    partial unique indexes below prevent duplicate rules in either case — a plain
    UNIQUE(category_id, sub_category_id) would NOT catch duplicate catch-all rules,
    since SQL treats NULLs as distinct from each other.
    """

    __tablename__ = "routing_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "sub_category_id"],
            ["sub_categories.category_id", "sub_categories.id"],
            name="fk_routing_rules_category_sub_category",
        ),
        Index(
            "uq_routing_rules_category_only",
            "category_id",
            unique=True,
            postgresql_where="sub_category_id IS NULL",
        ),
        Index(
            "uq_routing_rules_category_sub_category",
            "category_id",
            "sub_category_id",
            unique=True,
            postgresql_where="sub_category_id IS NOT NULL",
        ),
    )

    category_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    sub_category_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    team_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    category: Mapped["Category"] = relationship(foreign_keys=[category_id])
    sub_category: Mapped[Optional["SubCategory"]] = relationship(
        foreign_keys=[category_id, sub_category_id], overlaps="category"
    )
    team: Mapped["Team"] = relationship()
