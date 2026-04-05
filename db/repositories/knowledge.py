"""Knowledge-specific repository with graph traversal and similarity search."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, func, and_, or_, desc, asc, text

from db.models import KnowledgeEntity, KnowledgeRelation
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class KnowledgeRepository(BaseRepository[KnowledgeEntity]):
    """Repository for knowledge graph entities and relations."""

    model_class = KnowledgeEntity

    # ── Entity queries ─────────────────────────────────────────────────

    def get_by_empire(
        self,
        empire_id: str,
        entity_type: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 100,
    ) -> list[KnowledgeEntity]:
        """Get entities for an empire."""
        stmt = (
            select(KnowledgeEntity)
            .where(and_(
                KnowledgeEntity.empire_id == empire_id,
                KnowledgeEntity.confidence >= min_confidence,
            ))
        )
        if entity_type:
            stmt = stmt.where(KnowledgeEntity.entity_type == entity_type)
        stmt = stmt.order_by(desc(KnowledgeEntity.importance_score)).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def search_entities(
        self,
        query: str,
        empire_id: str,
        entity_type: str | None = None,
        limit: int = 20,
    ) -> list[KnowledgeEntity]:
        """Search entities by name or description (LIKE query)."""
        pattern = f"%{query}%"
        stmt = (
            select(KnowledgeEntity)
            .where(and_(
                KnowledgeEntity.empire_id == empire_id,
                or_(
                    KnowledgeEntity.name.ilike(pattern),
                    KnowledgeEntity.description.ilike(pattern),
                ),
            ))
        )
        if entity_type:
            stmt = stmt.where(KnowledgeEntity.entity_type == entity_type)
        stmt = stmt.order_by(desc(KnowledgeEntity.importance_score)).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def get_by_name(self, name: str, empire_id: str) -> KnowledgeEntity | None:
        """Get entity by exact name."""
        return self.find_one({"name": name, "empire_id": empire_id})

    def get_entity_types(self, empire_id: str) -> list[str]:
        """Get all unique entity types for an empire."""
        return self.distinct_values("entity_type", {"empire_id": empire_id})

    def get_most_connected(self, empire_id: str, limit: int = 20) -> list[dict]:
        """Get entities with the most connections."""
        # Count outgoing relations
        stmt_out = (
            select(
                KnowledgeRelation.source_entity_id.label("entity_id"),
                func.count(KnowledgeRelation.id).label("count"),
            )
            .join(KnowledgeEntity, KnowledgeEntity.id == KnowledgeRelation.source_entity_id)
            .where(KnowledgeEntity.empire_id == empire_id)
            .group_by(KnowledgeRelation.source_entity_id)
        )
        outgoing = {row[0]: row[1] for row in self.session.execute(stmt_out).all()}

        # Count incoming relations
        stmt_in = (
            select(
                KnowledgeRelation.target_entity_id.label("entity_id"),
                func.count(KnowledgeRelation.id).label("count"),
            )
            .join(KnowledgeEntity, KnowledgeEntity.id == KnowledgeRelation.target_entity_id)
            .where(KnowledgeEntity.empire_id == empire_id)
            .group_by(KnowledgeRelation.target_entity_id)
        )
        incoming = {row[0]: row[1] for row in self.session.execute(stmt_in).all()}

        # Merge counts
        all_ids = set(outgoing.keys()) | set(incoming.keys())
        connections = [
            {"entity_id": eid, "total": outgoing.get(eid, 0) + incoming.get(eid, 0)}
            for eid in all_ids
        ]
        connections.sort(key=lambda x: x["total"], reverse=True)
        top_ids = [c["entity_id"] for c in connections[:limit]]

        entities = self.get_many(top_ids)
        entity_map = {e.id: e for e in entities}

        return [
            {
                "entity": entity_map.get(c["entity_id"]),
                "connection_count": c["total"],
                "outgoing": outgoing.get(c["entity_id"], 0),
                "incoming": incoming.get(c["entity_id"], 0),
            }
            for c in connections[:limit]
            if c["entity_id"] in entity_map
        ]

    def update_importance(self, entity_id: str, importance: float) -> None:
        """Update entity importance score."""
        self.update(entity_id, importance_score=min(1.0, max(0.0, importance)))

    def increment_access(self, entity_id: str) -> None:
        """Increment access count for an entity."""
        entity = self.get(entity_id)
        if entity:
            entity.access_count += 1
            self.session.flush()

    def decay_confidence(self, empire_id: str, days_old: int = 90, rate: float = 0.05) -> int:
        """Reduce confidence of old entities that haven't been accessed recently.

        Args:
            empire_id: Empire ID.
            days_old: Entities older than this many days.
            rate: Amount to reduce confidence by.

        Returns:
            Number of entities decayed.
        """
        threshold = datetime.now(timezone.utc) - timedelta(days=days_old)
        stmt = (
            select(KnowledgeEntity)
            .where(and_(
                KnowledgeEntity.empire_id == empire_id,
                KnowledgeEntity.updated_at < threshold,
                KnowledgeEntity.confidence > 0.1,
            ))
        )
        entities = list(self.session.execute(stmt).scalars().all())
        for entity in entities:
            entity.confidence = max(0.1, entity.confidence - rate)
        self.session.flush()
        return len(entities)

    def prune_low_quality(self, empire_id: str, min_confidence: float = 0.2, min_connections: int = 0) -> int:
        """Remove low-quality entities.

        Args:
            empire_id: Empire ID.
            min_confidence: Remove entities below this confidence.
            min_connections: Only remove if fewer connections than this.

        Returns:
            Number of entities removed.
        """
        from sqlalchemy.orm import joinedload

        # Eager load relations to avoid N+1 queries
        stmt = (
            select(KnowledgeEntity)
            .where(and_(
                KnowledgeEntity.empire_id == empire_id,
                KnowledgeEntity.confidence < min_confidence,
            ))
            .options(
                joinedload(KnowledgeEntity.outgoing_relations),
                joinedload(KnowledgeEntity.incoming_relations),
            )
        )
        entities = list(self.session.execute(stmt).scalars().unique().all())

        removed = 0
        for entity in entities:
            conn_count = len(entity.outgoing_relations or []) + len(entity.incoming_relations or [])
            if conn_count <= min_connections:
                self.session.delete(entity)
                removed += 1

        self.session.flush()
        return removed

    # ── Relation queries ───────────────────────────────────────────────

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 1.0,
        confidence: float = 0.8,
        metadata: dict | None = None,
    ) -> KnowledgeRelation:
        """Add a relation between two entities."""
        relation = KnowledgeRelation(
            source_entity_id=source_id,
            target_entity_id=target_id,
            relation_type=relation_type,
            weight=weight,
            confidence=confidence,
            metadata_json=metadata or {},
        )
        self.session.add(relation)
        self.session.flush()
        return relation

    def get_relations(
        self,
        entity_id: str,
        direction: str = "both",
        relation_type: str | None = None,
    ) -> list[KnowledgeRelation]:
        """Get relations for an entity.

        Args:
            entity_id: Entity ID.
            direction: 'outgoing', 'incoming', or 'both'.
            relation_type: Optional relation type filter.
        """
        conditions = []

        if direction in ("outgoing", "both"):
            cond = KnowledgeRelation.source_entity_id == entity_id
            if relation_type:
                cond = and_(cond, KnowledgeRelation.relation_type == relation_type)
            conditions.append(cond)

        if direction in ("incoming", "both"):
            cond = KnowledgeRelation.target_entity_id == entity_id
            if relation_type:
                cond = and_(cond, KnowledgeRelation.relation_type == relation_type)
            conditions.append(cond)

        stmt = select(KnowledgeRelation).where(or_(*conditions))
        return list(self.session.execute(stmt).scalars().all())

    def get_neighbors(
        self,
        entity_id: str,
        max_depth: int = 1,
        relation_types: list[str] | None = None,
    ) -> list[dict]:
        """Get neighboring entities up to max_depth.

        Args:
            entity_id: Starting entity ID.
            max_depth: Maximum traversal depth.
            relation_types: Optional filter for relation types.

        Returns:
            List of {entity, relation, depth} dicts.
        """
        visited = {entity_id}
        results = []
        current_ids = [entity_id]

        # Resolve the starting entity's empire_id to scope traversal
        # and prevent cross-tenant data leaks
        _empire_id: str | None = None
        try:
            start_entity = self.session.get(KnowledgeEntity, entity_id)
            if start_entity:
                _empire_id = start_entity.empire_id
        except Exception:
            pass

        for depth in range(1, max_depth + 1):
            next_ids = []
            neighbor_ids_to_fetch = []

            for eid in current_ids:
                relations = self.get_relations(eid, direction="both", relation_type=None)

                for rel in relations:
                    if relation_types and rel.relation_type not in relation_types:
                        continue

                    neighbor_id = (
                        rel.target_entity_id
                        if rel.source_entity_id == eid
                        else rel.source_entity_id
                    )

                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        next_ids.append(neighbor_id)
                        neighbor_ids_to_fetch.append((neighbor_id, rel, depth))

            # Batch fetch all neighbors at this depth to avoid N+1 queries
            if neighbor_ids_to_fetch:
                neighbor_ids = [nid for nid, _, _ in neighbor_ids_to_fetch]
                neighbors = self.get_many(neighbor_ids)
                neighbors_by_id = {n.id: n for n in neighbors}

                for neighbor_id, rel, depth_val in neighbor_ids_to_fetch:
                    neighbor = neighbors_by_id.get(neighbor_id)
                    if neighbor:
                        # Filter out entities from other empires
                        if isinstance(_empire_id, str) and getattr(neighbor, "empire_id", None) != _empire_id:
                            continue
                        results.append({
                            "entity": neighbor,
                            "relation": rel,
                            "depth": depth_val,
                        })

            current_ids = next_ids
            if not current_ids:
                break

        return results

    def get_relation_types(self, empire_id: str) -> list[str]:
        """Get all unique relation types for an empire."""
        stmt = (
            select(KnowledgeRelation.relation_type)
            .join(KnowledgeEntity, KnowledgeEntity.id == KnowledgeRelation.source_entity_id)
            .where(KnowledgeEntity.empire_id == empire_id)
            .distinct()
        )
        return [row[0] for row in self.session.execute(stmt).all()]

    def find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
    ) -> list[dict] | None:
        """Find shortest path between two entities (BFS).

        Returns:
            List of {entity_id, relation} dicts forming the path, or None if no path.
        """
        if source_id == target_id:
            return []

        visited = {source_id}
        queue = [(source_id, [])]

        while queue:
            current_id, path = queue.pop(0)

            if len(path) >= max_depth:
                continue

            relations = self.get_relations(current_id, direction="both")
            for rel in relations:
                neighbor_id = (
                    rel.target_entity_id
                    if rel.source_entity_id == current_id
                    else rel.source_entity_id
                )

                if neighbor_id == target_id:
                    return path + [{"entity_id": neighbor_id, "relation": rel}]

                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append((
                        neighbor_id,
                        path + [{"entity_id": neighbor_id, "relation": rel}],
                    ))

        return None

    # ── Graph stats ────────────────────────────────────────────────────

    def get_graph_stats(self, empire_id: str) -> dict:
        """Get knowledge graph statistics."""
        entity_count = self.count({"empire_id": empire_id})

        relation_count_stmt = (
            select(func.count(KnowledgeRelation.id))
            .join(KnowledgeEntity, KnowledgeEntity.id == KnowledgeRelation.source_entity_id)
            .where(KnowledgeEntity.empire_id == empire_id)
        )
        relation_count = self.session.execute(relation_count_stmt).scalar() or 0

        type_counts_stmt = (
            select(
                KnowledgeEntity.entity_type,
                func.count(KnowledgeEntity.id),
            )
            .where(KnowledgeEntity.empire_id == empire_id)
            .group_by(KnowledgeEntity.entity_type)
        )
        type_counts = {
            row[0]: row[1]
            for row in self.session.execute(type_counts_stmt).all()
        }

        avg_confidence = self.avg_column("confidence", {"empire_id": empire_id})

        return {
            "entity_count": entity_count,
            "relation_count": relation_count,
            "entity_types": type_counts,
            "avg_confidence": avg_confidence,
            "avg_connections": relation_count * 2 / entity_count if entity_count > 0 else 0,
        }

    def similarity_search(
        self,
        embedding: list[float],
        empire_id: str,
        limit: int = 10,
        min_similarity: float = 0.5,
    ) -> list[dict]:
        """Find entities similar to a given embedding using cosine similarity.

        Args:
            embedding: Query embedding vector.
            empire_id: Empire ID.
            limit: Maximum results.
            min_similarity: Minimum cosine similarity threshold.

        Returns:
            List of {entity, similarity} dicts.
        """
        # embedding_json is deferred at the ORM level; undefer for this query.
        # Cap at 2000 to prevent full-table loads with 25KB-per-row vectors.
        from sqlalchemy.orm import undefer
        stmt = (
            select(KnowledgeEntity)
            .options(undefer(KnowledgeEntity.embedding_json))
            .where(and_(
                KnowledgeEntity.empire_id == empire_id,
                KnowledgeEntity.embedding_json.is_not(None),
            ))
            .limit(2000)
        )
        entities = list(self.session.execute(stmt).scalars().all())

        results = []
        for entity in entities:
            if not entity.embedding_json:
                continue
            sim = self._cosine_similarity(embedding, entity.embedding_json)
            if sim >= min_similarity:
                results.append({"entity": entity, "similarity": sim})

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
