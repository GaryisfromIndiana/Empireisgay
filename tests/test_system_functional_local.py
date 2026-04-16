from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def functional_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "functional-local.db"

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

    from core.memory.manager import MemoryManager
    from db.engine import init_db, session_scope
    from db.models import Empire, KnowledgeEntity, Lieutenant
    from sqlalchemy import select
    from web.app import create_app

    init_db()
    with session_scope() as session:
        existing = session.execute(
            select(Empire).where(Empire.id == "empire-alpha")
        ).scalar_one_or_none()
        if existing is None:
            session.add(Empire(id="empire-alpha", name="Test Empire"))
        if session.execute(select(Lieutenant).where(Lieutenant.id == "lt-1")).scalar_one_or_none() is None:
            session.add(
                Lieutenant(
                    id="lt-1",
                    empire_id="empire-alpha",
                    name="Research Lead",
                    domain="research",
                    status="active",
                )
            )
        session.add(
            KnowledgeEntity(
                id="ent-1",
                empire_id="empire-alpha",
                entity_type="company",
                name="Anthropic",
                description="AI company",
                confidence=0.9,
                importance_score=0.8,
            )
        )

    mm = MemoryManager("empire-alpha")
    mm.store(
        content="Research synthesis on model routing and system health.",
        memory_type="semantic",
        title="Model Routing Research",
        category="research",
        tags=["research", "routing"],
    )

    app = create_app({"TESTING": True, "DEBUG": True})
    yield app

    get_settings.cache_clear()
    eng._engine = None
    eng._session_factory = None
    eng._scoped_session = None


def test_local_functional_surfaces_render_and_status_command_works(
    functional_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.scheduler import health as health_module
    import llm.router as router_module

    class FakeHealthChecker:
        def __init__(self, empire_id: str):
            self.empire_id = empire_id

        def run_all_checks(self) -> dict:
            return {"overall_status": "healthy", "checks": []}

    def fail_execute(*args, **kwargs):
        raise AssertionError("status path should not require LLM router")

    monkeypatch.setattr(health_module, "HealthChecker", FakeHealthChecker)
    monkeypatch.setattr(router_module.ModelRouter, "execute", fail_execute)

    client = functional_app.test_client()

    for path in ("/", "/memory/", "/knowledge/", "/god/", "/lieutenants/", "/warrooms/", "/scheduler/", "/api/health"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Internal server error" not in response.get_data(as_text=True), path

    command = client.post("/god/command", json={"command": "report full system health status"})
    data = command.get_json()
    assert command.status_code == 200
    assert data["action"] == "STATUS"
    assert data["status"] == "completed"
    assert data["health"]["overall_status"] == "healthy"
