"""Native integration tests for memory compression behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from core.memory.compression import CompressionResult, MemoryCluster, MemoryCompressor
from core.memory.manager import MemoryManager
from db.engine import session_scope
from db.models import MemoryEntry

pytestmark = pytest.mark.integration


def test_memory_compressor_initializes() -> None:
    compressor = MemoryCompressor("empire-alpha")
    assert compressor.empire_id == "empire-alpha"
    assert compressor.min_cluster_size == 3


def test_compression_dataclasses_have_stable_defaults() -> None:
    result = CompressionResult()
    cluster = MemoryCluster(cluster_key="topic:test")
    assert result.clusters_found == 0
    assert result.compression_ratio == 0.0
    assert cluster.cluster_key == "topic:test"
    assert cluster.memories == []


def test_find_clusters_detects_seeded_old_memories() -> None:
    mm = MemoryManager("empire-alpha")
    tag = f"compression-seed-{uuid.uuid4()}"
    seeded_ids: list[str] = []

    for i in range(3):
        created = mm.store(
            content=f"Seeded compression memory {i} for {tag}",
            memory_type="episodic",
            title=f"Compression Seed {i}",
            category="compression_test",
            importance=0.79,
            tags=[tag],
            source_type="integration_test",
        )
        seeded_ids.append(created["id"])

    old_ts = datetime.now(timezone.utc) - timedelta(days=2)
    with session_scope() as session:
        for mem_id in seeded_ids:
            entry = session.get(MemoryEntry, mem_id)
            assert entry is not None
            entry.created_at = old_ts
            entry.updated_at = old_ts

    compressor = MemoryCompressor("empire-alpha")
    clusters = compressor.find_clusters()
    assert any(cluster.cluster_key == f"episodic:compression_test:{tag}" for cluster in clusters)


def test_run_compression_updates_result_with_mocked_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    compressor = MemoryCompressor("empire-alpha")
    fake_cluster = MemoryCluster(
        cluster_key="episodic:compression_test:mock",
        memories=[{"id": "1"}, {"id": "2"}, {"id": "3"}],
        total_words=120,
        memory_type="episodic",
        category="compression_test",
    )

    monkeypatch.setattr(compressor, "find_clusters", lambda: [fake_cluster])
    monkeypatch.setattr(
        compressor,
        "compress_cluster",
        lambda _cluster: {"summary_words": 30, "cost": 0.01},
    )

    result = compressor.run_compression()
    assert result.clusters_found == 1
    assert result.clusters_compressed == 1
    assert result.memories_consumed == 3
    assert result.tokens_before == 120
    assert result.tokens_after == 30
