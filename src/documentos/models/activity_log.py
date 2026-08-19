"""Activity log model for auditing user actions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from documentos.models import Base

if TYPE_CHECKING:
    from documentos.models.user import User


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class ActivityLog(Base):
    """A chronologically-ordered record of a user action within the system.

    The ``details`` column stores optional JSON-encoded metadata about the
    action (e.g. target document id, old/new values)."""

    __tablename__ = "activity_logs"

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    user: Mapped["User | None"] = relationship(
        "User", back_populates="activity_logs", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<ActivityLog id={self.id} action={self.action!r}>"
