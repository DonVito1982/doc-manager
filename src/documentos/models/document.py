"""Document model representing a source file tracked by the system."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from documentos.models import Base

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class Document(Base):
    """Represents a content document discovered in the project ``content/``
    directory.  The ``path`` field stores the relative path inside ``content/``
    and must be unique across all documents."""

    __tablename__ = "documents"

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    comments: Mapped[list["Comment"]] = relationship(  # noqa: F821
        "Comment", back_populates="document", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} path={self.path!r}>"
