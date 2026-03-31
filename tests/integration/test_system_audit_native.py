"""Native integration smoke tests for core Empire subsystems."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from config.settings import MODEL_CATALOG, get_settings
from core.memory.manager import MemoryManager
from core.routing.pricing import PricingEngine
from core.search.web import WebSearcher
from db.engine import DatabaseManager, check_connection, get_session
from db.repositories.knowledge import KnowledgeRepository
from db.repositories.lieutenant import LieutenantRepository
from db.repositories.task import TaskRepository

pytestmark = pytest.mark.integration


def test_settings_and_model_catalog_load() -> None:
    settings = get_settings()
    assert settings.empire_name
    assert settings.db_url
    assert len(MODEL_CATALOG) >= 5
    assert all(model.model_id for model in MODEL_CATALOG.values())


def test_database_manager_health_and_stats() -> None:
    assert check_connection()

    manager = DatabaseManager()
    stats = manager.get_stats()
    assert "tables" in stats
    assert isinstance(stats["tables"], list)
    assert len(stats["tables"]) >= 1


def test_repositories_return_expected_shapes() -> None:
    session = get_session()
    try:
        lieutenant_repo = LieutenantRepository(session)
        task_repo = TaskRepository(session)
        knowledge_repo = KnowledgeRepository(session)

        lieutenants = lieutenant_repo.get_by_empire("empire-alpha")
        recent_tasks = task_repo.get_recent(limit=5)
        graph_stats: dict[str, Any] = knowledge_repo.get_graph_stats("empire-alpha")

        assert isinstance(lieutenants, list)
        assert isinstance(recent_tasks, list)
        assert "entity_count" in graph_stats
    finally:
        session.close()


def test_core_runtime_smoke_paths() -> None:
    web_searcher = WebSearcher("empire-alpha")
    assert web_searcher.empire_id == "empire-alpha"

    memory_manager = MemoryManager("empire-alpha")
    memory_stats = memory_manager.get_stats()
    assert memory_stats.total_count >= 0

    pricing = PricingEngine()
    cost = pricing.calculate_cost("claude-sonnet-4", tokens_input=1000, tokens_output=500)
    assert cost > 0


def test_memory_store_and_recall_roundtrip() -> None:
    mm = MemoryManager("empire-alpha")
    marker = f"integration-memory-roundtrip-{uuid.uuid4()}"
    stored = mm.store(
        content=f"Roundtrip content marker: {marker}",
        memory_type="episodic",
        title="Integration roundtrip test",
        category="integration_test",
        importance=0.79,
        tags=["integration", "roundtrip"],
        source_type="integration_test",
    )
    assert "id" in stored

    recalled = mm.recall(
        query=marker,
        memory_types=["episodic"],
        limit=10,
        refresh_on_access=False,
    )
    assert any(marker in entry.get("content", "") for entry in recalled)
