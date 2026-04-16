from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def god_panel_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "god-panel-local.db"

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


def test_status_command_does_not_require_llm(
    god_panel_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm.router as router_module
    from core.scheduler import health as health_module

    class FakeHealthChecker:
        def __init__(self, empire_id: str):
            self.empire_id = empire_id

        def run_all_checks(self) -> dict:
            return {"overall_status": "healthy", "checks": []}

    def fail_execute(*args, **kwargs):
        raise AssertionError("deterministic status commands should not call the LLM router")

    monkeypatch.setattr(router_module.ModelRouter, "execute", fail_execute)
    monkeypatch.setattr(health_module, "HealthChecker", FakeHealthChecker)

    client = god_panel_app.test_client()
    response = client.post("/god/command", json={"command": "report full system health status"})
    data = response.get_json()

    assert response.status_code == 200
    assert data["action"] == "STATUS"
    assert data["status"] == "completed"
    assert data["health"]["overall_status"] == "healthy"
