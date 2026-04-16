from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest


@pytest.fixture
def sqlite_directive_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "sqlite-serialize.db"

    monkeypatch.setenv("EMPIRE_DB_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("EMPIRE_FLASK_DEBUG", "false")
    monkeypatch.setenv("EMPIRE_EMPIRE_ID", "empire-alpha")
    monkeypatch.setenv("EMPIRE_EMPIRE_NAME", "Test Empire")

    from config.settings import get_settings
    import db.engine as eng

    get_settings.cache_clear()
    eng._engine = None
    eng._session_factory = None
    eng._scoped_session = None

    from db.engine import init_db, session_scope
    from db.models import Empire
    from sqlalchemy import select

    init_db()
    with session_scope() as session:
        existing = session.execute(
            select(Empire).where(Empire.id == "empire-alpha")
        ).scalar_one_or_none()
        if existing is None:
            session.add(Empire(id="empire-alpha", name="Test Empire"))

    yield

    get_settings.cache_clear()
    eng._engine = None
    eng._session_factory = None
    eng._scoped_session = None


def test_sqlite_writes_serialize_for_directive_creation(sqlite_directive_env) -> None:
    import db.engine as eng
    from core.directives.manager import DirectiveManager
    from db.engine import session_scope
    from db.models import Directive
    from sqlalchemy import select

    created: dict[str, str | None] = {"id": None}
    errors: list[Exception] = []

    with eng._sqlite_write_lock:
        worker = threading.Thread(
            target=lambda: _create_directive(created, errors),
            daemon=True,
        )
        worker.start()
        time.sleep(0.5)
        assert created["id"] is None, "directive creation should not finish while sqlite write lock is held"
        assert not errors

    worker.join(timeout=5)
    assert not worker.is_alive(), "directive creation should complete after lock release"
    assert not errors
    assert created["id"] is not None

    with session_scope() as session:
        directive = session.execute(
            select(Directive).where(Directive.id == created["id"])
        ).scalar_one_or_none()
        assert directive is not None
        assert directive.title == "Serialized local directive"


def _create_directive(created: dict[str, str | None], errors: list[Exception]) -> None:
    try:
        from core.directives.manager import DirectiveManager

        result = DirectiveManager("empire-alpha").create_directive(
            title="Serialized local directive",
            description="Ensure SQLite writes serialize instead of raising database is locked.",
            priority=4,
            source="human",
        )
        created["id"] = result["id"]
    except Exception as e:  # pragma: no cover - assertion target
        errors.append(e)
