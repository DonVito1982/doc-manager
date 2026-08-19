"""Comment model with single-level threading (parent/replies)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from documentos.models import Base

if TYPE_CHECKING:
    from documentos.models.document import Document
    from documentos.models.user import User


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class Comment(Base):
    """A comment attached to a document, supporting single-level threading
    via ``parent_id`` → ``replies``."""

    __tablename__ = "comments"

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("comments.id"), nullable=True
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    user: Mapped["User"] = relationship(
        "User", back_populates="comments", lazy="select"
    )
    document: Mapped["Document"] = relationship(
        "Document", back_populates="comments", lazy="select"
    )
    parent: Mapped["Comment | None"] = relationship(
        "Comment", remote_side="Comment.id", back_populates="replies", lazy="select"
    )
    replies: Mapped[list["Comment"]] = relationship(
        "Comment", back_populates="parent", lazy="select"
    )

    def __repr__(self) -> str:
        return (
            f"<Comment id={self.id} user_id={self.user_id} "
            f"document_id={self.document_id}>"
        )
