from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin


class SubCategory(UUIDPKMixin, TimestampMixin, Base):
    """Belongs to exactly one category; cannot exist independently (category_id NOT
    NULL + ON DELETE RESTRICT). The (category_id, id) unique constraint below exists
    solely so `issues` and `routing_rules` can hold a composite FK back to this table,
    which makes an invalid category/sub_category pairing impossible to store at the
    database level (see DECISIONS.md D17)."""

    __tablename__ = "sub_categories"
    __table_args__ = (
        UniqueConstraint("category_id", "name", name="uq_sub_categories_category_name"),
        UniqueConstraint("category_id", "id", name="uq_sub_categories_category_id_id"),
    )

    category_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    category: Mapped["Category"] = relationship(back_populates="sub_categories")
