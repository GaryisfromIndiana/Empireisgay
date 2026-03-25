"""Knowledge graph queries — structured traversal to answer complex questions.

"What do we know about Anthropic?" traverses the graph and returns:
company → products → models → benchmarks → competitors → funding
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeAnswer:
    """Structured answer from a knowledge graph query."""
    query: str = ""
    entity_name: str = ""
    entity_type: str = ""
    description: str = ""
    attributes: dict = field(default_factory=dict)
    relations: list[dict] = field(default_factory=list)
    related_entities: list[dict] = field(default_factory=list)
    facts_from_memory: list[dict] = field(default_factory=list)
    quality_score: float = 0.0
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_prompt(self) -> str:
        """Format as text for LLM prompt injection."""
        parts = [f"## What Empire knows about: {self.entity_name}"]
        parts.append(f"Type: {self.entity_type}")
        if self.description:
            parts.append(f"Description: {self.description}")

        if self.attributes:
            parts.append("\n### Attributes")
            for k, v in self.attributes.items():
                if k.startswith("_") or k in ("quality_score", "last_seen", "update_count"):
                    continue
                parts.append(f"- {k}: {v}")

        if self.relations:
            parts.append("\n### Relationships")
            for r in self.relations[:10]:
                parts.append(f"- {r.get('label', r.get('type', ''))}: {r.get('target', '')}")

        if self.facts_from_memory:
            parts.append("\n### Recent facts")
            for f in self.facts_from_memory[:5]:
                parts.append(f"- {f.get('content', '')[:200]}")

        return "\n".join(parts)


class KnowledgeQuerier:
    """Answers structured questions from the knowledge graph + memory.

    Combines graph traversal with memory recall to build comprehensive
    answers about any topic Empire has knowledge of.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id

    def ask(self, question: str, depth: int = 2) -> KnowledgeAnswer:
        """Ask the knowledge graph a question.

        Args:
            question: Natural language question (e.g., "What do we know about Anthropic?")
            depth: How deep to traverse relations.

        Returns:
            KnowledgeAnswer with structured data.
        """
        # Extract the subject from the question
        subject = self._extract_subject(question)
        if not subject:
            subject = question

        answer = KnowledgeAnswer(query=question)

        # Find the entity in the graph
        from core.knowledge.graph import KnowledgeGraph
        graph = KnowledgeGraph(self.empire_id)

        entities = graph.find_entities(query=subject, limit=3)
        if not entities:
            # No graph entity — fall back to memory
            answer.facts_from_memory = self._get_memory_facts(question)
            return answer

        # Use the best match
        primary = entities[0]
        answer.entity_name = primary.name
        answer.entity_type = primary.entity_type
        answer.description = primary.description
        answer.attributes = primary.attributes
        answer.confidence = primary.confidence

        # Get quality score if available
        quality = primary.attributes.get("quality_score", {})
        if isinstance(quality, dict):
            answer.quality_score = quality.get("overall", 0)

        # Traverse relations
        neighbors = graph.get_neighbors(primary.name, max_depth=depth)
        relations = []
        related = []

        for neighbor in neighbors:
            related.append({
                "name": neighbor.name,
                "type": neighbor.entity_type,
                "description": neighbor.description[:150],
                "depth": neighbor.depth,
                "confidence": neighbor.confidence,
            })

        # Get direct relations with labels
        try:
            from db.engine import get_session
            from db.repositories.knowledge import KnowledgeRepository
            session = get_session()
            repo = KnowledgeRepository(session)

            entity_db = repo.get_by_name(primary.name, self.empire_id)
            if entity_db:
                for rel in repo.get_relations(entity_db.id, direction="outgoing"):
                    target = repo.get(rel.target_entity_id)
                    meta = rel.metadata_json or {}
                    relations.append({
                        "type": rel.relation_type,
                        "label": meta.get("forward_label", rel.relation_type),
                        "target": target.name if target else rel.target_entity_id,
                        "target_type": target.entity_type if target else "",
                        "confidence": rel.confidence,
                        "weight": rel.weight,
                    })

                for rel in repo.get_relations(entity_db.id, direction="incoming"):
                    source = repo.get(rel.source_entity_id)
                    meta = rel.metadata_json or {}
                    relations.append({
                        "type": meta.get("inverse_label", rel.relation_type),
                        "label": meta.get("inverse_label", rel.relation_type),
                        "target": source.name if source else rel.source_entity_id,
                        "target_type": source.entity_type if source else "",
                        "confidence": rel.confidence,
                        "weight": rel.weight,
                    })
        except Exception as e:
            logger.debug("Relation lookup failed: %s", e)

        answer.relations = relations
        answer.related_entities = related

        # Also get relevant memories
        answer.facts_from_memory = self._get_memory_facts(primary.name)

        # Collect sources
        sources = set()
        attrs = primary.attributes or {}
        for key in ["source", "source_url", "url", "website"]:
            if attrs.get(key):
                sources.add(str(attrs[key]))
        answer.sources = list(sources)

        return answer

    def ask_structured(self, entity_name: str) -> dict:
        """Get a fully structured knowledge profile for an entity.

        Returns a dict organized by relationship categories.
        """
        answer = self.ask(entity_name, depth=2)

        # Organize by relation type
        by_relation: dict[str, list[dict]] = {}
        for rel in answer.relations:
            rtype = rel.get("label", rel.get("type", "related"))
            if rtype not in by_relation:
                by_relation[rtype] = []
            by_relation[rtype].append(rel)

        return {
            "entity": {
                "name": answer.entity_name,
                "type": answer.entity_type,
                "description": answer.description,
                "confidence": answer.confidence,
                "quality_score": answer.quality_score,
            },
            "attributes": {k: v for k, v in (answer.attributes or {}).items()
                          if not k.startswith("_") and k not in ("quality_score", "last_seen", "update_count")},
            "relationships": by_relation,
            "related_entities": answer.related_entities[:15],
            "facts": [f.get("content", "")[:300] for f in answer.facts_from_memory[:5]],
            "sources": answer.sources,
        }

    def compare(self, entity_a: str, entity_b: str) -> dict:
        """Compare two entities side by side."""
        answer_a = self.ask(entity_a, depth=1)
        answer_b = self.ask(entity_b, depth=1)

        # Find shared relations
        a_related = {r.get("target", "").lower() for r in answer_a.relations}
        b_related = {r.get("target", "").lower() for r in answer_b.relations}
        shared = a_related & b_related

        return {
            "entity_a": {
                "name": answer_a.entity_name,
                "type": answer_a.entity_type,
                "description": answer_a.description,
                "relation_count": len(answer_a.relations),
                "quality": answer_a.quality_score,
            },
            "entity_b": {
                "name": answer_b.entity_name,
                "type": answer_b.entity_type,
                "description": answer_b.description,
                "relation_count": len(answer_b.relations),
                "quality": answer_b.quality_score,
            },
            "shared_connections": list(shared),
            "shared_count": len(shared),
        }

    def _extract_subject(self, question: str) -> str:
        """Extract the subject entity from a question."""
        q = question.lower().strip().rstrip("?")

        # Strip common question prefixes
        prefixes = [
            "what do we know about ",
            "what does empire know about ",
            "tell me about ",
            "what is ",
            "who is ",
            "describe ",
            "explain ",
            "info on ",
            "information about ",
        ]
        for prefix in prefixes:
            if q.startswith(prefix):
                return q[len(prefix):].strip()

        return q

    def _get_memory_facts(self, query: str) -> list[dict]:
        """Get relevant facts from memory."""
        try:
            from core.memory.manager import MemoryManager
            mm = MemoryManager(self.empire_id)
            return mm.recall(query=query, memory_types=["semantic"], limit=5)
        except Exception:
            return []
