from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPKMixin


class Role(UUIDPKMixin, CreatedAtMixin, Base):
    """USER / RESOLVER / ADMIN as database rows, not scattered string literals.
    Seeded once as reference data by an Alembic migration (see DECISIONS.md D16) —
    this is required reference data, not demo data, and belongs in every environment."""

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
