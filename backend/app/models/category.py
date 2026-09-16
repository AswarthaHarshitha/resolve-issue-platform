from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin


class Category(UUIDPKMixin, TimestampMixin, Base):
    """Configurable issue category. Never hard-deleted while referenced — deactivate
    via is_active instead (DECISIONS.md D15)."""

    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    sub_categories: Mapped[list["SubCategory"]] = relationship(
        back_populates="category", order_by="SubCategory.name"
    )
