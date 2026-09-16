from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin


class Team(UUIDPKMixin, TimestampMixin, Base):
    """Resolver/operational team. Never hard-deleted once referenced elsewhere —
    see DECISIONS.md D15 (RESTRICT + is_active instead of cascading deletes)."""

    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
