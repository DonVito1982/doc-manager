"""Database models initialisation and session management.

Provides :func:`init_db` to bootstrap the SQLAlchemy engine and create all
tables, and :func:`get_db` to obtain a per-request session within a Flask
application context.
"""

from __future__ import annotations

from flask import Flask, g
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# ---------------------------------------------------------------------------
# Session configuration
# ---------------------------------------------------------------------------

_session_factory: sessionmaker | None = None

# Default SQLite database; relative path resolves against the working directory.
DEFAULT_DB_URL = "sqlite:///project.db"


def get_db() -> Session:
    """Return the current SQLAlchemy session for the active Flask request.

    Creates a new session bound to the engine configured by :func:`init_db`
    and caches it on ``flask.g`` so that the same session is reused across
    a single request lifetime.

    Returns:
        An active SQLAlchemy :class:`Session`.

    Raises:
        RuntimeError: If :func:`init_db` has not been called yet.
    """
    if _session_factory is None:
        raise RuntimeError("init_db() must be called before get_db()")
    if "db_session" not in g:
        g.db_session = _session_factory()
    return g.db_session


def init_db(app: Flask, db_url: str | None = None) -> None:
    """Initialise the SQLAlchemy engine and create all tables.

    Configures a SQLite engine (or the provided *db_url*), creates all
    tables via :meth:`Base.metadata.create_all`, and stores the session
    factory in ``app.extensions["db_session_factory"]``.  A teardown
    handler is registered to close sessions at the end of each request.

    Args:
        app: The Flask application instance to configure.
        db_url: Optional database URL override (defaults to
            ``sqlite:///project.db``).

    Raises:
        RuntimeError: If the engine cannot be created.
    """
    global _session_factory

    url = db_url or DEFAULT_DB_URL
    try:
        engine = create_engine(url)
    except Exception as exc:
        raise RuntimeError(f"Failed to create database engine: {exc}") from exc

    Base.metadata.create_all(bind=engine)
    _session_factory = sessionmaker(bind=engine)
    app.extensions["db_session_factory"] = _session_factory

    @app.teardown_appcontext
    def _close_db(exception: BaseException | None = None) -> None:  # noqa: ARG001
        db_session = g.pop("db_session", None)
        if db_session is not None:
            db_session.close()


# ---------------------------------------------------------------------------
# Import models so Base.metadata is fully populated before create_all()
# ---------------------------------------------------------------------------

from documentos.models.activity_log import ActivityLog  # noqa: E402, F401
from documentos.models.comment import Comment  # noqa: E402, F401
from documentos.models.document import Document  # noqa: E402, F401
from documentos.models.invitation import Invitation  # noqa: E402, F401
from documentos.models.user import User  # noqa: E402, F401
