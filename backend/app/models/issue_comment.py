from uuid import UUID

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPKMixin


class IssueComment(UUIDPKMixin, CreatedAtMixin, Base):
    """Immutable once posted (no updated_at) — a real conversation log, not an
    editable document. Cascade-deletes with its issue (DECISIONS.md D15's
    owned-child rule); an issue's comments have no meaning without the issue."""

    __tablename__ = "issue_comments"

    issue_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    issue: Mapped["Issue"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship()
