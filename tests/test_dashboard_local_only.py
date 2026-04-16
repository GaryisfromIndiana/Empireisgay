from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def dashboard_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "dashboard.db"

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
    from web.app import create_app

    init_db()
    with session_scope() as session:
        existing = session.execute(
            select(Empire).where(Empire.id == "empire-alpha")
        ).scalar_one_or_none()
        if existing is None:
            session.add(Empire(id="empire-alpha", name="Test Empire"))

    app = create_app({"TESTING": True, "DEBUG": True})
    yield app

    get_settings.cache_clear()
    eng._engine = None
    eng._session_factory = None
    eng._scoped_session = None


def test_dashboard_does_not_use_live_feed_or_sweep_calls(
    dashboard_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.search.feeds as feeds
    import core.search.sweep as sweep

    def fail_fetch_latest(*args, **kwargs):
        raise AssertionError("dashboard should not fetch live feeds")

    def fail_recent_discoveries(*args, **kwargs):
        raise AssertionError("dashboard should not call live discovery helpers")

    monkeypatch.setattr(feeds.FeedReader, "fetch_latest", fail_fetch_latest)
    monkeypatch.setattr(sweep.IntelligenceSweep, "get_recent_discoveries", fail_recent_discoveries)

    client = dashboard_app.test_client()
    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Dashboard" in body


def test_dashboard_does_not_refresh_memory_access_on_read(
    dashboard_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from db.engine import session_scope
    from db.models import MemoryEntry

    with session_scope() as session:
        session.add(
            MemoryEntry(
                empire_id="empire-alpha",
                memory_type="semantic",
                category="research",
                title="research synthesis",
                content="research synthesis body",
            )
        )

    def fail_refresh(self):
        raise AssertionError("dashboard should not mutate memory entries during render")

    monkeypatch.setattr(MemoryEntry, "refresh", fail_refresh)

    client = dashboard_app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    assert "Dashboard" in response.get_data(as_text=True)
