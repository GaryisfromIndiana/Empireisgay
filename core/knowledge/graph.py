"""Knowledge graph — entity-relation graph with traversal and querying."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class GraphNode:
    """A node in the knowledge graph."""
    entity_id: str
    name: str
    entity_type: str
    description: str = ""
    attributes: dict = field(default_factory=dict)
    confidence: float = 0.8
    importance: float = 0.5
    depth: int = 0  # Depth from query source


@dataclass
class GraphEdge:
    """An edge in the knowledge graph."""
    source_id: str
    target_id: str
    relation_type: str
    weight: float = 1.0
    confidence: float = 0.8


@dataclass
class SubGraph:
    """A subgraph extracted from the knowledge graph."""
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    center_entity_id: str = ""

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)


@dataclass
class GraphTraversal:
    """Result of a graph traversal."""
    visited_nodes: list[GraphNode] = field(default_factory=list)
    visited_edges: list[GraphEdge] = field(default_factory=list)
    max_depth_reached: int = 0
    path: list[str] = field(default_factory=list)


@dataclass
class GraphStats:
    """Statistics about the knowledge graph."""
    entity_count: int = 0
    relation_count: int = 0
    entity_types: dict[str, int] = field(default_factory=dict)
    relation_types: dict[str, int] = field(default_factory=dict)
    avg_connections: float = 0.0
    avg_confidence: float = 0.0
    most_connected: list[dict] = field(default_factory=list)
    clusters: int = 0


@dataclass
class Cluster:
    """A cluster of related entities."""
    cluster_id: int
    entities: list[str] = field(default_factory=list)
    center_entity: str = ""
    size: int = 0
    cohesion: float = 0.0


class KnowledgeGraph:
    """Entity-relation knowledge graph with traversal, search, and analysis.

    Built on top of the database repositories but provides an in-memory
    graph interface for fast traversal and analysis operations.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self._repo = None

    def _get_repo(self):
        """Get a fresh repository with its own session."""
        from db.engine import get_session
        from db.repositories.knowledge import KnowledgeRepository
        return KnowledgeRepository(get_session())

    def add_entity(
        self,
        name: str,
        entity_type: str,
        description: str = "",
        attributes: dict | None = None,
        confidence: float = 0.8,
        source_task_id: str = "",
        tags: list[str] | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
    ) -> dict:
        """Add an entity to the knowledge graph with optional temporal bounds.

        Args:
            name: Entity name.
            entity_type: Type (person, concept, technology, etc.).
            description: Entity description.
            attributes: Additional attributes.
            confidence: Confidence score.
            source_task_id: Source task.
            tags: Tags for search.
            valid_from: When this entity became relevant (ISO datetime).
            valid_to: When this entity stopped being relevant.

        Returns:
            Created entity as dict.
        """
        from datetime import datetime, timezone

        repo = self._get_repo()

        # Enrich attributes with temporal data
        enriched_attrs = dict(attributes or {})
        if valid_from:
            enriched_attrs["valid_from"] = valid_from
        if valid_to:
            enriched_attrs["valid_to"] = valid_to
        enriched_attrs["last_seen"] = datetime.now(timezone.utc).isoformat()

        # Check for existing entity with same name
        existing = repo.get_by_name(name, self.empire_id)
        if existing:
            # Update existing entity — merge attributes, bump confidence
            merged_attrs = dict(existing.attributes_json or {})
            merged_attrs.update(enriched_attrs)
            merged_attrs["update_count"] = merged_attrs.get("update_count", 0) + 1

            update_fields = {"attributes_json": merged_attrs, "updated_at": datetime.now(timezone.utc)}
            if confidence > existing.confidence:
                update_fields["confidence"] = confidence
            if description and len(description) > len(existing.description or ""):
                update_fields["description"] = description

            repo.update(existing.id, **update_fields)
            repo.commit()
            return {"id": existing.id, "name": name, "action": "updated"}

        entity = repo.create(
            empire_id=self.empire_id,
            entity_type=entity_type,
            name=name,
            description=description,
            attributes_json=enriched_attrs,
            confidence=confidence,
            source_task_id=source_task_id or None,
            tags_json=tags or [],
        )
        repo.commit()
        return {"id": entity.id, "name": name, "type": entity_type, "action": "created"}

    def add_relation(
        self,
        source_name: str,
        target_name: str,
        relation_type: str,
        weight: float = 1.0,
        confidence: float = 0.8,
        metadata: dict | None = None,
    ) -> dict | None:
        """Add a relation between two entities (by name).

        Args:
            source_name: Source entity name.
            target_name: Target entity name.
            relation_type: Type of relation.
            weight: Relation weight.
            confidence: Confidence score.
            metadata: Additional metadata.

        Returns:
            Created relation info or None.
        """
        repo = self._get_repo()

        source = repo.get_by_name(source_name, self.empire_id)
        target = repo.get_by_name(target_name, self.empire_id)

        if not source or not target:
            logger.warning("Cannot create relation: source=%s target=%s", source_name, target_name)
            return None

        relation = repo.add_relation(
            source_id=source.id,
            target_id=target.id,
            relation_type=relation_type,
            weight=weight,
            confidence=confidence,
            metadata=metadata,
        )
        repo.commit()
        return {
            "id": relation.id,
            "source": source_name,
            "target": target_name,
            "type": relation_type,
        }

    def find_entities(
        self,
        query: str = "",
        entity_type: str = "",
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> list[GraphNode]:
        """Find entities matching a query."""
        repo = self._get_repo()

        if query:
            entities = repo.search_entities(query, self.empire_id, entity_type or None, limit)
        else:
            entities = repo.get_by_empire(self.empire_id, entity_type or None, min_confidence, limit)

        return [
            GraphNode(
                entity_id=e.id,
                name=e.name,
                entity_type=e.entity_type,
                description=e.description,
                attributes=e.attributes_json or {},
                confidence=e.confidence,
                importance=e.importance_score,
            )
            for e in entities
        ]

    def get_neighbors(
        self,
        entity_name: str,
        max_depth: int = 1,
        relation_types: list[str] | None = None,
    ) -> list[GraphNode]:
        """Get neighboring entities up to max_depth."""
        repo = self._get_repo()
        entity = repo.get_by_name(entity_name, self.empire_id)
        if not entity:
            return []

        neighbors_data = repo.get_neighbors(entity.id, max_depth, relation_types)
        return [
            GraphNode(
                entity_id=n["entity"].id,
                name=n["entity"].name,
                entity_type=n["entity"].entity_type,
                description=n["entity"].description,
                confidence=n["entity"].confidence,
                importance=n["entity"].importance_score,
                depth=n["depth"],
            )
            for n in neighbors_data
        ]

    def find_path(
        self,
        source_name: str,
        target_name: str,
        max_depth: int = 5,
    ) -> list[dict] | None:
        """Find shortest path between two entities."""
        repo = self._get_repo()

        source = repo.get_by_name(source_name, self.empire_id)
        target = repo.get_by_name(target_name, self.empire_id)

        if not source or not target:
            return None

        return repo.find_path(source.id, target.id, max_depth)

    def get_subgraph(
        self,
        center_name: str,
        depth: int = 2,
    ) -> SubGraph:
        """Extract a subgraph centered on an entity."""
        neighbors = self.get_neighbors(center_name, max_depth=depth)

        repo = self._get_repo()
        center = repo.get_by_name(center_name, self.empire_id)

        nodes = []
        if center:
            nodes.append(GraphNode(
                entity_id=center.id,
                name=center.name,
                entity_type=center.entity_type,
                description=center.description,
                confidence=center.confidence,
                importance=center.importance_score,
                depth=0,
            ))
        nodes.extend(neighbors)

        # Get edges between all nodes
        node_ids = {n.entity_id for n in nodes}
        edges = []
        for node in nodes:
            relations = repo.get_relations(node.entity_id, direction="outgoing")
            for rel in relations:
                if rel.target_entity_id in node_ids:
                    edges.append(GraphEdge(
                        source_id=rel.source_entity_id,
                        target_id=rel.target_entity_id,
                        relation_type=rel.relation_type,
                        weight=rel.weight,
                        confidence=rel.confidence,
                    ))

        return SubGraph(
            nodes=nodes,
            edges=edges,
            center_entity_id=center.id if center else "",
        )

    def get_central_entities(self, limit: int = 10) -> list[GraphNode]:
        """Get the most connected/important entities."""
        repo = self._get_repo()
        most_connected = repo.get_most_connected(self.empire_id, limit)

        return [
            GraphNode(
                entity_id=mc["entity"].id,
                name=mc["entity"].name,
                entity_type=mc["entity"].entity_type,
                description=mc["entity"].description,
                confidence=mc["entity"].confidence,
                importance=mc["entity"].importance_score,
            )
            for mc in most_connected
            if mc["entity"]
        ]

    def compute_pagerank(self, damping: float = 0.85, iterations: int = 20) -> dict[str, float]:
        """Compute PageRank-style importance scores for all entities.

        Args:
            damping: Damping factor (0-1).
            iterations: Number of iterations.

        Returns:
            Dict of entity_id → importance score.
        """
        repo = self._get_repo()
        entities = repo.get_by_empire(self.empire_id, limit=10000)

        if not entities:
            return {}

        # Build adjacency lists
        entity_ids = [e.id for e in entities]
        n = len(entity_ids)
        scores = {eid: 1.0 / n for eid in entity_ids}
        outgoing: dict[str, list[str]] = defaultdict(list)

        for entity in entities:
            for rel in (entity.outgoing_relations or []):
                outgoing[entity.id].append(rel.target_entity_id)

        # Iterate
        for _ in range(iterations):
            new_scores: dict[str, float] = {}
            for eid in entity_ids:
                rank = (1.0 - damping) / n
                for source_id in entity_ids:
                    if eid in outgoing.get(source_id, []):
                        out_count = len(outgoing[source_id])
                        if out_count > 0:
                            rank += damping * scores[source_id] / out_count
                new_scores[eid] = rank
            scores = new_scores

        # Update importance scores in DB
        for eid, score in scores.items():
            repo.update_importance(eid, min(1.0, score * n))  # Normalize

        repo.commit()
        return scores

    def merge_entities(self, entity_names: list[str]) -> dict | None:
        """Merge duplicate entities into one.

        Keeps the entity with highest confidence and merges attributes.
        """
        if len(entity_names) < 2:
            return None

        repo = self._get_repo()
        entities = [repo.get_by_name(name, self.empire_id) for name in entity_names]
        entities = [e for e in entities if e is not None]

        if len(entities) < 2:
            return None

        # Keep the one with highest confidence
        primary = max(entities, key=lambda e: e.confidence)
        others = [e for e in entities if e.id != primary.id]

        # Merge attributes
        merged_attrs = dict(primary.attributes_json or {})
        for other in others:
            for k, v in (other.attributes_json or {}).items():
                if k not in merged_attrs:
                    merged_attrs[k] = v

        repo.update(primary.id, attributes_json=merged_attrs)

        # Transfer relations from others to primary
        for other in others:
            for rel in (other.outgoing_relations or []):
                if rel.target_entity_id != primary.id:
                    repo.add_relation(
                        source_id=primary.id,
                        target_id=rel.target_entity_id,
                        relation_type=rel.relation_type,
                        weight=rel.weight,
                    )
            for rel in (other.incoming_relations or []):
                if rel.source_entity_id != primary.id:
                    repo.add_relation(
                        source_id=rel.source_entity_id,
                        target_id=primary.id,
                        relation_type=rel.relation_type,
                        weight=rel.weight,
                    )
            repo.delete(other.id)

        repo.commit()
        return {
            "primary": primary.id,
            "merged": [o.id for o in others],
            "name": primary.name,
        }

    def prune(self, min_confidence: float = 0.2, min_connections: int = 0) -> int:
        """Remove low-quality entities."""
        repo = self._get_repo()
        count = repo.prune_low_quality(self.empire_id, min_confidence, min_connections)
        repo.commit()
        return count

    def get_stats(self) -> GraphStats:
        """Get knowledge graph statistics."""
        repo = self._get_repo()
        raw = repo.get_graph_stats(self.empire_id)

        return GraphStats(
            entity_count=raw.get("entity_count", 0),
            relation_count=raw.get("relation_count", 0),
            entity_types=raw.get("entity_types", {}),
            avg_connections=raw.get("avg_connections", 0),
            avg_confidence=raw.get("avg_confidence", 0),
        )

    def export_graph(self) -> dict:
        """Export the graph for sharing or visualization."""
        repo = self._get_repo()
        entities = repo.get_by_empire(self.empire_id, limit=10000)

        nodes = []
        edges = []

        for entity in entities:
            nodes.append({
                "id": entity.id,
                "name": entity.name,
                "type": entity.entity_type,
                "description": entity.description,
                "confidence": entity.confidence,
                "importance": entity.importance_score,
            })
            for rel in (entity.outgoing_relations or []):
                edges.append({
                    "source": rel.source_entity_id,
                    "target": rel.target_entity_id,
                    "type": rel.relation_type,
                    "weight": rel.weight,
                })

        return {"nodes": nodes, "edges": edges, "empire_id": self.empire_id}

    def import_graph(self, data: dict) -> dict:
        """Import a graph from exported data."""
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        imported_nodes = 0
        imported_edges = 0

        for node in nodes:
            self.add_entity(
                name=node["name"],
                entity_type=node.get("type", "imported"),
                description=node.get("description", ""),
                confidence=node.get("confidence", 0.7) * 0.9,  # Slight discount
                tags=["imported"],
            )
            imported_nodes += 1

        for edge in edges:
            # Need to resolve names from IDs in source graph
            source_node = next((n for n in nodes if n["id"] == edge["source"]), None)
            target_node = next((n for n in nodes if n["id"] == edge["target"]), None)
            if source_node and target_node:
                self.add_relation(
                    source_name=source_node["name"],
                    target_name=target_node["name"],
                    relation_type=edge.get("type", "related_to"),
                    weight=edge.get("weight", 1.0),
                )
                imported_edges += 1

        return {"nodes_imported": imported_nodes, "edges_imported": imported_edges}
