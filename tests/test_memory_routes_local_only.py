from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def memory_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "memory-routes.db"

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
    from db.models import Empire, MemoryEntry
    from sqlalchemy import select
    from web.app import create_app

    init_db()
    with session_scope() as session:
        existing = session.execute(
            select(Empire).where(Empire.id == "empire-alpha")
        ).scalar_one_or_none()
        if existing is None:
            session.add(Empire(id="empire-alpha", name="Test Empire"))
        session.add(
            MemoryEntry(
                empire_id="empire-alpha",
                memory_type="semantic",
                category="research",
                title="Feed: Test entry",
                content="Stored feed body",
            )
        )

    app = create_app({"TESTING": True, "DEBUG": True})
    yield app

    get_settings.cache_clear()
    eng._engine = None
    eng._session_factory = None
    eng._scoped_session = None


def test_memory_routes_do_not_refresh_access_counts(
    memory_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from db.models import MemoryEntry

    def fail_refresh(self):
        raise AssertionError("memory UI routes should not mutate memories during read")

    monkeypatch.setattr(MemoryEntry, "refresh", fail_refresh)

    client = memory_app.test_client()

    overview = client.get("/memory/")
    search = client.get("/memory/search?q=Test")
    by_type = client.get("/memory/by-type/semantic")

    assert overview.status_code == 200
    assert "Memory" in overview.get_data(as_text=True)
    assert search.status_code == 200
    assert by_type.status_code == 200


def test_memory_overview_renders_without_internal_error(memory_app) -> None:
    client = memory_app.test_client()
    response = client.get("/memory/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Internal server error" not in body
