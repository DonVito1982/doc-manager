"""User model with Flask-Login integration and bcrypt password handling."""

from __future__ import annotations

from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from documentos.models import Base

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class User(Base, UserMixin):
    """Represents a registered user of the document management system.

    Implements the Flask-Login ``UserMixin`` interface for session
    management and provides bcrypt-based password utilities.
    """

    __tablename__ = "users"

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    google_id: Mapped[str | None] = mapped_column(
        String(256), unique=True, nullable=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="reader")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    invited_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    reset_token: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reset_token_expires: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    comments: Mapped[list["Comment"]] = relationship(  # noqa: F821
        "Comment", back_populates="user", lazy="select"
    )
    activity_logs: Mapped[list["ActivityLog"]] = relationship(  # noqa: F821
        "ActivityLog", back_populates="user", lazy="select"
    )
    invitations_sent: Mapped[list["Invitation"]] = relationship(  # noqa: F821
        "Invitation",
        back_populates="inviter",
        foreign_keys="Invitation.created_by",
        lazy="select",
    )

    # ------------------------------------------------------------------
    # Password utilities (bcrypt via werkzeug.security)
    # ------------------------------------------------------------------

    def set_password(self, password: str) -> None:
        """Hash and store *password* using bcrypt."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Return ``True`` if *password* matches the stored hash."""
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)

    def has_password(self) -> bool:
        """Return ``True`` if the user has a password credential set."""
        return self.password_hash is not None

    # ------------------------------------------------------------------
    # Flask-Login integration
    # ------------------------------------------------------------------

    def get_id(self) -> str:
        """Return the user ID as a string (required by Flask-Login)."""
        return str(self.id)

    @property
    def is_authenticated(self) -> bool:  # noqa: D401
        """``True`` for all User instances (Flask-Login contract)."""
        return True

    @property
    def is_anonymous(self) -> bool:  # noqa: D401
        """``False`` for all User instances (Flask-Login contract)."""
        return False

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"
