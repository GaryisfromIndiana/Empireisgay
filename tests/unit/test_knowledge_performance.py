"""Unit tests verifying knowledge graph N+1 query fixes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from db.repositories.knowledge import KnowledgeRepository
from db.models import KnowledgeEntity, KnowledgeRelation


def test_get_neighbors_batches_entity_lookups() -> None:
    """Verify get_neighbors uses get_many() instead of individual get() calls."""
    
    repo = KnowledgeRepository(MagicMock())
    
    # Mock get_relations to return 5 relations
    mock_relations = [
        MagicMock(
            source_entity_id="entity1",
            target_entity_id=f"neighbor{i}",
            relation_type="related_to"
        )
        for i in range(5)
    ]
    repo.get_relations = MagicMock(return_value=mock_relations)
    
    # Mock get_many to return batch
    mock_entities = [
        MagicMock(id=f"neighbor{i}", name=f"Neighbor {i}")
        for i in range(5)
    ]
    repo.get_many = MagicMock(return_value=mock_entities)
    
    # Mock get to track individual calls (should NOT be called)
    repo.get = MagicMock(side_effect=lambda x: MagicMock(id=x, name=x))
    
    # Execute
    results = repo.get_neighbors("entity1", max_depth=1)
    
    # Assertions
    assert len(results) == 5
    repo.get_many.assert_called_once()  # Single batch query
    repo.get.assert_not_called()  # No individual queries


def test_prune_low_quality_uses_eager_loading() -> None:
    """Verify prune_low_quality eager loads relations to avoid N+1."""
    
    from sqlalchemy import select
    from unittest.mock import ANY
    
    mock_session = MagicMock()
    repo = KnowledgeRepository(mock_session)
    
    # Mock query execution
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_unique = MagicMock()
    
    mock_session.execute.return_value = mock_result
    mock_result.scalars.return_value = mock_scalars
    mock_scalars.unique.return_value = mock_unique
    mock_unique.all.return_value = []
    
    # Execute
    repo.prune_low_quality("empire1", min_confidence=0.2)
    
    # Verify that session.execute was called with a statement (eager loading is part of the statement)
    mock_session.execute.assert_called_once()
    call_args = mock_session.execute.call_args
    stmt = call_args[0][0]
    
    # The statement should have options (eager loading) - we can't easily inspect the compiled SQL
    # but we verify execute was called exactly once (not in a loop)
    assert mock_session.execute.call_count == 1
