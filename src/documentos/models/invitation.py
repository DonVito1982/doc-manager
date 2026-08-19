"""Invitation model for user registration via email tokens."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from documentos.models import Base

if TYPE_CHECKING:
    from documentos.models.user import User


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INVITATION_EXPIRY_DAYS = 7


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class Invitation(Base):
    """An email invitation sent by an admin to onboard a new user.

    Each invitation has a unique token and expires after
    :data:`INVITATION_EXPIRY_DAYS` days (default 7)."""

    __tablename__ = "invitations"

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(120), nullable=False)
    token: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    is_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.utcnow() + timedelta(days=INVITATION_EXPIRY_DAYS),
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    inviter: Mapped["User"] = relationship(
        "User",
        back_populates="invitations_sent",
        foreign_keys=[created_by],
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Invitation id={self.id} email={self.email!r} used={self.is_used}>"
