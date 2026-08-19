"""Unit tests for database models and initialisation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import inspect, text

from documentos.models import Base, get_db, init_db
from documentos.models.activity_log import ActivityLog
from documentos.models.comment import Comment
from documentos.models.document import Document
from documentos.models.invitation import Invitation
from documentos.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_app(tmp_path: Path, db_filename: str = "test.db") -> Flask:
    """Create and return a Flask app with a temporary SQLite database."""
    app = Flask(__name__)
    db_url = f"sqlite:///{tmp_path / db_filename}"
    init_db(app, db_url=db_url)
    return app


def _make_user(db_session, username="alice", email="alice@example.com") -> User:
    """Create and persist a minimal User."""
    user = User(username=username, email=email)
    user.set_password("secret123")
    db_session.add(user)
    db_session.commit()
    return user


def _make_document(db_session, path="guide/index.md", title="User Guide") -> Document:
    """Create and persist a minimal Document."""
    doc = Document(path=path, title=title)
    db_session.add(doc)
    db_session.commit()
    return doc


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


def test_models_importable() -> None:
    """All model classes and the Base are importable."""
    assert Base is not None
    assert User is not None
    assert Document is not None
    assert Comment is not None
    assert Invitation is not None
    assert ActivityLog is not None


# ---------------------------------------------------------------------------
# init_db / get_db
# ---------------------------------------------------------------------------


class TestInitDb:
    """Tests for :func:`init_db` and :func:`get_db`."""

    def test_init_db_creates_tables(self, tmp_path: Path) -> None:
        """init_db should create all tables in the SQLite database."""
        app = _create_app(tmp_path)
        with app.app_context():
            engine = get_db().get_bind()
            inspector = inspect(engine)
            table_names = sorted(inspector.get_table_names())
            assert table_names == [
                "activity_logs",
                "comments",
                "documents",
                "invitations",
                "users",
            ]

    def test_init_db_stores_factory_on_app_extensions(self, tmp_path: Path) -> None:
        """The session factory is stored in app.extensions."""
        app = Flask(__name__)
        db_url = f"sqlite:///{tmp_path / 'project.db'}"
        init_db(app, db_url=db_url)
        assert "db_session_factory" in app.extensions

    def test_get_db_returns_session(self, tmp_path: Path) -> None:
        """get_db() returns a working session within app context."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            result = session.execute(text("SELECT 1")).scalar()
            assert result == 1

    def test_get_db_reuses_session_within_request(self, tmp_path: Path) -> None:
        """Multiple calls to get_db() in the same request return the same session."""
        app = _create_app(tmp_path)
        with app.app_context():
            s1 = get_db()
            s2 = get_db()
            assert s1 is s2

    def test_get_db_without_init_raises(self) -> None:
        """Calling get_db() before init_db() raises RuntimeError."""
        import documentos.models as models_mod

        old_factory = models_mod._session_factory
        models_mod._session_factory = None
        try:
            with pytest.raises(RuntimeError, match="init_db"):
                models_mod.get_db()
        finally:
            models_mod._session_factory = old_factory

    def test_init_db_with_default_url(self, tmp_path: Path, monkeypatch) -> None:
        """init_db defaults to sqlite:///project.db."""
        app = Flask(__name__)
        monkeypatch.chdir(tmp_path)
        init_db(app)
        with app.app_context():
            result = get_db().execute(text("SELECT 1")).scalar()
        assert result == 1


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------


class TestUserModel:
    """Tests for the User model."""

    def test_create_user_with_minimal_fields(self, tmp_path: Path) -> None:
        """A User can be created with username and email only."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = User(username="bob", email="bob@example.com")
            session.add(user)
            session.commit()

            fetched = session.get(User, user.id)
            assert fetched is not None
            assert fetched.username == "bob"
            assert fetched.email == "bob@example.com"
            assert fetched.role == "reader"  # default

    def test_user_role_defaults_to_reader(self, tmp_path: Path) -> None:
        """New users default to the 'reader' role."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = User(username="guest", email="guest@example.com")
            session.add(user)
            session.commit()
            assert user.role == "reader"

    def test_user_is_active_defaults_to_true(self, tmp_path: Path) -> None:
        """New users are active by default."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = User(username="active", email="active@example.com")
            session.add(user)
            session.commit()
            assert user.is_active is True

    def test_username_must_be_unique(self, tmp_path: Path) -> None:
        """Two users cannot share the same username."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            session.add(User(username="dup", email="a@example.com"))
            session.commit()
            session.add(User(username="dup", email="b@example.com"))
            with pytest.raises(Exception):  # IntegrityError
                session.commit()

    def test_email_must_be_unique(self, tmp_path: Path) -> None:
        """Two users cannot share the same email."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            session.add(User(username="a", email="dup@example.com"))
            session.commit()
            session.add(User(username="b", email="dup@example.com"))
            with pytest.raises(Exception):
                session.commit()

    def test_google_id_must_be_unique(self, tmp_path: Path) -> None:
        """Two users cannot share the same Google OAuth ID."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            session.add(User(username="a", email="a@example.com", google_id="g123"))
            session.commit()
            session.add(User(username="b", email="b@example.com", google_id="g123"))
            with pytest.raises(Exception):
                session.commit()

    def test_google_id_can_be_null(self, tmp_path: Path) -> None:
        """Multiple users can have google_id=None (no conflict)."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            session.add(User(username="a", email="a@example.com"))
            session.add(User(username="b", email="b@example.com"))
            session.commit()
            assert session.query(User).count() == 2

    def test_created_at_is_set_automatically(self, tmp_path: Path) -> None:
        """created_at is populated on creation."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = User(username="ts", email="ts@example.com")
            session.add(user)
            session.commit()
            assert user.created_at is not None
            assert isinstance(user.created_at, datetime)

    def test_invited_by_fk(self, tmp_path: Path) -> None:
        """A user can reference the inviter via FK."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            inviter = _make_user(session, username="admin", email="admin@example.com")
            invitee = User(
                username="newbie",
                email="newbie@example.com",
                invited_by=inviter.id,
            )
            session.add(invitee)
            session.commit()
            assert invitee.invited_by == inviter.id

    # ----- Password utilities -----

    def test_set_and_check_password(self, tmp_path: Path) -> None:
        """set_password / check_password round-trip works."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            assert user.check_password("secret123") is True
            assert user.check_password("wrong") is False

    def test_check_password_when_no_password_set(self, tmp_path: Path) -> None:
        """check_password returns False when password_hash is None."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = User(username="nopwd", email="nopwd@example.com")
            session.add(user)
            session.commit()
            assert user.password_hash is None
            assert user.check_password("anything") is False

    def test_has_password(self, tmp_path: Path) -> None:
        """has_password returns True only when a password is set."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            assert user.has_password() is True

            user2 = User(username="nohash", email="nohash@example.com")
            session.add(user2)
            session.commit()
            assert user2.has_password() is False

    def test_password_hash_is_not_plaintext(self, tmp_path: Path) -> None:
        """The stored password_hash is not the raw password."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            assert user.password_hash != "secret123"
            assert user.password_hash is not None

    # ----- Flask-Login interface -----

    def test_get_id_returns_string(self, tmp_path: Path) -> None:
        """get_id() returns the user's id as a str."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            assert user.get_id() == str(user.id)

    def test_is_authenticated(self, tmp_path: Path) -> None:
        """All User instances report as authenticated."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            assert user.is_authenticated is True

    def test_is_active_matches_column(self, tmp_path: Path) -> None:
        """is_active property reflects the column value."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            assert user.is_active is True
            user.is_active = False
            session.commit()
            assert user.is_active is False

    def test_is_anonymous(self, tmp_path: Path) -> None:
        """User instances are never anonymous."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            assert user.is_anonymous is False

    # ----- Misc -----

    def test_user_repr(self, tmp_path: Path) -> None:
        """repr includes id and username."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            r = repr(user)
            assert str(user.id) in r
            assert "alice" in r


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------


class TestDocumentModel:
    """Tests for the Document model."""

    def test_create_document(self, tmp_path: Path) -> None:
        """A Document can be created and persisted."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            doc = Document(path="intro.md", title="Introduction")
            session.add(doc)
            session.commit()

            fetched = session.get(Document, doc.id)
            assert fetched is not None
            assert fetched.path == "intro.md"
            assert fetched.title == "Introduction"
            assert fetched.created_at is not None

    def test_path_must_be_unique(self, tmp_path: Path) -> None:
        """Two documents cannot share the same path."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            session.add(Document(path="shared.md", title="A"))
            session.commit()
            session.add(Document(path="shared.md", title="B"))
            with pytest.raises(Exception):
                session.commit()

    def test_document_repr(self, tmp_path: Path) -> None:
        """repr includes id and path."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            doc = _make_document(session)
            r = repr(doc)
            assert str(doc.id) in r
            assert "guide/index.md" in r


# ---------------------------------------------------------------------------
# Comment model
# ---------------------------------------------------------------------------


class TestCommentModel:
    """Tests for the Comment model."""

    def test_create_comment(self, tmp_path: Path) -> None:
        """A Comment can be created referencing a user and document."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            doc = _make_document(session)
            comment = Comment(
                body="Great document!",
                user_id=user.id,
                document_id=doc.id,
            )
            session.add(comment)
            session.commit()

            assert comment.id is not None
            assert comment.body == "Great document!"
            assert comment.user_id == user.id
            assert comment.document_id == doc.id
            assert comment.created_at is not None
            assert comment.updated_at is None

    def test_comment_user_relationship(self, tmp_path: Path) -> None:
        """Comment.user navigates to the author."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            doc = _make_document(session)
            comment = Comment(body="test", user_id=user.id, document_id=doc.id)
            session.add(comment)
            session.commit()
            assert comment.user.id == user.id
            assert comment.user.username == "alice"

    def test_comment_document_relationship(self, tmp_path: Path) -> None:
        """Comment.document navigates to the parent document."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            doc = _make_document(session)
            comment = Comment(body="test", user_id=user.id, document_id=doc.id)
            session.add(comment)
            session.commit()
            assert comment.document.id == doc.id
            assert comment.document.title == "User Guide"

    def test_parent_reply_threading(self, tmp_path: Path) -> None:
        """Comments can have a parent/reply chain (single-level)."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            doc = _make_document(session)
            parent = Comment(body="parent", user_id=user.id, document_id=doc.id)
            session.add(parent)
            session.commit()
            reply = Comment(
                body="reply",
                user_id=user.id,
                document_id=doc.id,
                parent_id=parent.id,
            )
            session.add(reply)
            session.commit()

            # Navigate from reply to parent
            assert reply.parent is not None
            assert reply.parent.id == parent.id
            # Navigate from parent to replies
            assert len(parent.replies) == 1
            assert parent.replies[0].id == reply.id

    def test_top_level_comment_has_no_parent(self, tmp_path: Path) -> None:
        """A top-level comment has parent_id=None and no replies initially."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            doc = _make_document(session)
            comment = Comment(
                body="top level",
                user_id=user.id,
                document_id=doc.id,
            )
            session.add(comment)
            session.commit()
            assert comment.parent_id is None
            assert comment.parent is None
            assert comment.replies == []

    def test_comment_repr(self, tmp_path: Path) -> None:
        """repr includes id, user_id, and document_id."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            doc = _make_document(session)
            comment = Comment(body="x", user_id=user.id, document_id=doc.id)
            session.add(comment)
            session.commit()
            r = repr(comment)
            assert str(comment.id) in r


# ---------------------------------------------------------------------------
# Invitation model
# ---------------------------------------------------------------------------


class TestInvitationModel:
    """Tests for the Invitation model."""

    def test_create_invitation(self, tmp_path: Path) -> None:
        """An Invitation can be created with required fields."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            inv = Invitation(
                email="invitee@example.com",
                token="abc123",
                created_by=user.id,
            )
            session.add(inv)
            session.commit()
            assert inv.id is not None
            assert inv.email == "invitee@example.com"
            assert inv.token == "abc123"
            assert inv.created_by == user.id
            assert inv.is_used is False
            assert inv.used_at is None
            assert inv.created_at is not None

    def test_token_must_be_unique(self, tmp_path: Path) -> None:
        """Two invitations cannot share the same token."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            session.add(Invitation(email="a@x.com", token="shared", created_by=user.id))
            session.commit()
            session.add(Invitation(email="b@x.com", token="shared", created_by=user.id))
            with pytest.raises(Exception):
                session.commit()

    def test_expires_at_default_is_7_days(self, tmp_path: Path) -> None:
        """expires_at is set to 7 days from creation by default."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            before = datetime.utcnow()
            inv = Invitation(
                email="temp@example.com",
                token="tok1",
                created_by=user.id,
            )
            session.add(inv)
            session.commit()
            # Expiry should be ~7 days after creation
            delta = inv.expires_at - before
            assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)

    def test_inviter_relationship(self, tmp_path: Path) -> None:
        """inviter navigates to the User who created the invitation."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            inv = Invitation(
                email="x@example.com",
                token="tok_rel",
                created_by=user.id,
            )
            session.add(inv)
            session.commit()
            assert inv.inviter.id == user.id
            assert inv.inviter.username == "alice"

    def test_invitation_repr(self, tmp_path: Path) -> None:
        """repr includes id, email, and used status."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            inv = Invitation(
                email="test@example.com",
                token="repr_tok",
                created_by=user.id,
            )
            session.add(inv)
            session.commit()
            r = repr(inv)
            assert "test@example.com" in r


# ---------------------------------------------------------------------------
# ActivityLog model
# ---------------------------------------------------------------------------


class TestActivityLogModel:
    """Tests for the ActivityLog model."""

    def test_create_activity_log(self, tmp_path: Path) -> None:
        """An ActivityLog can be created with action and user."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            log = ActivityLog(user_id=user.id, action="login")
            session.add(log)
            session.commit()
            assert log.id is not None
            assert log.action == "login"
            assert log.user_id == user.id
            assert log.details is None
            assert log.created_at is not None

    def test_activity_log_without_user(self, tmp_path: Path) -> None:
        """An ActivityLog can have user_id=None (anonymous action)."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            log = ActivityLog(user_id=None, action="page_view")
            session.add(log)
            session.commit()
            assert log.user_id is None
            assert log.user is None

    def test_activity_log_with_json_details(self, tmp_path: Path) -> None:
        """The details column can store JSON-encoded metadata."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            payload = json.dumps({"ip": "127.0.0.1", "browser": "Firefox"})
            log = ActivityLog(
                user_id=user.id,
                action="password_reset",
                details=payload,
            )
            session.add(log)
            session.commit()
            assert log.details == payload
            # Verify it round-trips as valid JSON
            parsed = json.loads(log.details)
            assert parsed["ip"] == "127.0.0.1"

    def test_activity_log_user_relationship(self, tmp_path: Path) -> None:
        """ActivityLog.user navigates to the associated User."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            log = ActivityLog(user_id=user.id, action="create_document")
            session.add(log)
            session.commit()
            assert log.user is not None
            assert log.user.username == "alice"

    def test_activity_log_repr(self, tmp_path: Path) -> None:
        """repr includes id and action."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            log = ActivityLog(user_id=user.id, action="logout")
            session.add(log)
            session.commit()
            r = repr(log)
            assert str(log.id) in r
            assert "logout" in r


# ---------------------------------------------------------------------------
# Integration: User / Document relationships
# ---------------------------------------------------------------------------


class TestUserCommentsRelationship:
    """Tests for the User.comments and Document.comments relationships."""

    def test_user_has_comments(self, tmp_path: Path) -> None:
        """user.comments contains all comments authored by the user."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            doc = _make_document(session)
            c1 = Comment(body="first", user_id=user.id, document_id=doc.id)
            c2 = Comment(body="second", user_id=user.id, document_id=doc.id)
            session.add_all([c1, c2])
            session.commit()
            assert len(user.comments) == 2

    def test_document_has_comments(self, tmp_path: Path) -> None:
        """document.comments contains all comments on the document."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            doc = _make_document(session)
            c1 = Comment(body="a", user_id=user.id, document_id=doc.id)
            c2 = Comment(body="b", user_id=user.id, document_id=doc.id)
            session.add_all([c1, c2])
            session.commit()
            assert len(doc.comments) == 2


# ---------------------------------------------------------------------------
# Integration: User → activity_logs relationship
# ---------------------------------------------------------------------------


class TestUserActivityLogsRelationship:
    """Tests for the User.activity_logs relationship."""

    def test_user_has_activity_logs(self, tmp_path: Path) -> None:
        """user.activity_logs contains all logs for the user."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            log1 = ActivityLog(user_id=user.id, action="login")
            log2 = ActivityLog(user_id=user.id, action="logout")
            session.add_all([log1, log2])
            session.commit()
            assert len(user.activity_logs) == 2


# ---------------------------------------------------------------------------
# Integration: User → invitations_sent relationship
# ---------------------------------------------------------------------------


class TestUserInvitationsRelationship:
    """Tests for the User.invitations_sent relationship."""

    def test_user_has_invitations_sent(self, tmp_path: Path) -> None:
        """user.invitations_sent contains invitations created by the user."""
        app = _create_app(tmp_path)
        with app.app_context():
            session = get_db()
            user = _make_user(session)
            inv1 = Invitation(email="a@x.com", token="t1", created_by=user.id)
            inv2 = Invitation(email="b@x.com", token="t2", created_by=user.id)
            session.add_all([inv1, inv2])
            session.commit()
            assert len(user.invitations_sent) == 2
