"""Knowledge system — graph, schemas, quality, resolution, queries."""

from core.knowledge.graph import KnowledgeGraph, GraphNode, GraphEdge, SubGraph, GraphStats
from core.knowledge.entities import EntityExtractor, ExtractionResult
from core.knowledge.bridge import KnowledgeBridge, SyncResult
from core.knowledge.maintenance import KnowledgeMaintainer, KnowledgeReport, KnowledgeGap
from core.knowledge.schemas import EntitySchema, ENTITY_SCHEMAS, get_schema, validate_entity
from core.knowledge.quality import EntityQualityScorer, EntityQualityScore
from core.knowledge.resolution import EntityResolver, ResolutionResult
from core.knowledge.query import KnowledgeQuerier, KnowledgeAnswer

__all__ = [
    "KnowledgeGraph", "GraphNode", "GraphEdge", "SubGraph", "GraphStats",
    "EntityExtractor", "ExtractionResult",
    "KnowledgeBridge", "SyncResult",
    "KnowledgeMaintainer", "KnowledgeReport", "KnowledgeGap",
    "EntitySchema", "ENTITY_SCHEMAS", "get_schema", "validate_entity",
    "EntityQualityScorer", "EntityQualityScore",
    "EntityResolver", "ResolutionResult",
    "KnowledgeQuerier", "KnowledgeAnswer",
]
