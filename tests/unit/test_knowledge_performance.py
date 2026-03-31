"""Unit tests verifying knowledge graph N+1 query fixes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

from db.repositories.knowledge import KnowledgeRepository
from db.models import KnowledgeEntity, KnowledgeRelation


def test_get_neighbors_batches_entity_lookups() -> None:
    """Verify get_neighbors batch-fetches entities instead of N+1 individual gets."""

    mock_session = MagicMock()
    repo = KnowledgeRepository(mock_session)

    # Mock the starting entity lookup (self.get)
    start_entity = MagicMock(id="entity1", empire_id="empire1")
    repo.get = MagicMock(return_value=start_entity)

    # Mock get_relations to return 5 outgoing relations
    mock_relations = [
        MagicMock(
            source_entity_id="entity1",
            target_entity_id=f"neighbor{i}",
            relation_type="related_to",
        )
        for i in range(5)
    ]
    repo.get_relations = MagicMock(return_value=mock_relations)

    # Mock the batch session query that get_neighbors uses internally
    mock_neighbors = [
        MagicMock(id=f"neighbor{i}", name=f"Neighbor {i}", empire_id="empire1")
        for i in range(5)
    ]
    mock_session.execute.return_value.scalars.return_value.all.return_value = mock_neighbors

    results = repo.get_neighbors("entity1", max_depth=1)

    assert len(results) == 5
    # Should use one batch query via session.execute, not individual gets per neighbor
    mock_session.execute.assert_called_once()
    # get() is only called once for the starting entity, not for each neighbor
    repo.get.assert_called_once_with("entity1")


def test_prune_low_quality_uses_eager_loading() -> None:
    """Verify prune_low_quality uses a single query, not N+1."""

    mock_session = MagicMock()
    repo = KnowledgeRepository(mock_session)

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_unique = MagicMock()

    mock_session.execute.return_value = mock_result
    mock_result.scalars.return_value = mock_scalars
    mock_scalars.unique.return_value = mock_unique
    mock_unique.all.return_value = []

    repo.prune_low_quality("empire1", min_confidence=0.2)

    # Verify single query execution (not a loop of individual gets)
    assert mock_session.execute.call_count == 1
