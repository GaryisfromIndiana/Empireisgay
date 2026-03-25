"""Entity resolution — 3-stage fuzzy matching to prevent duplicates.

Stage 1: Exact match (case-insensitive)
Stage 2: Normalized match (strip punctuation, common prefixes/suffixes)
Stage 3: Token overlap similarity
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ResolutionMatch:
    """A potential match from entity resolution."""
    existing_id: str
    existing_name: str
    match_stage: int  # 1=exact, 2=normalized, 3=fuzzy
    similarity: float = 1.0
    action: str = "merge"  # merge, skip, new


@dataclass
class ResolutionResult:
    """Result of entity resolution."""
    input_name: str
    resolved: bool = False
    match: ResolutionMatch | None = None
    action: str = "create"  # create, merge, skip


# Common name variations to normalize
STRIP_PREFIXES = ["the ", "a ", "an "]
STRIP_SUFFIXES = [" inc", " inc.", " corp", " corp.", " ltd", " ltd.", " llc", " ai", " labs"]
EQUIVALENT_TERMS = {
    "gpt4": "gpt-4",
    "gpt 4": "gpt-4",
    "gpt-4o": "gpt-4o",
    "gpt4o": "gpt-4o",
    "claude3": "claude 3",
    "claude-3": "claude 3",
    "llama3": "llama 3",
    "llama-3": "llama 3",
    "openai": "openai",
    "open ai": "openai",
    "hf": "hugging face",
    "huggingface": "hugging face",
    "deepmind": "google deepmind",
    "google deepmind": "google deepmind",
}


def normalize_name(name: str) -> str:
    """Normalize an entity name for comparison."""
    n = name.lower().strip()

    # Strip common prefixes/suffixes
    for prefix in STRIP_PREFIXES:
        if n.startswith(prefix):
            n = n[len(prefix):]
    for suffix in STRIP_SUFFIXES:
        if n.endswith(suffix):
            n = n[:-len(suffix)]

    # Apply known equivalents
    if n in EQUIVALENT_TERMS:
        n = EQUIVALENT_TERMS[n]

    # Remove extra whitespace
    n = re.sub(r"\s+", " ", n).strip()

    return n


def tokenize(name: str) -> set[str]:
    """Tokenize a name into words for overlap comparison."""
    # Remove punctuation except hyphens
    cleaned = re.sub(r"[^\w\s-]", "", name.lower())
    return set(cleaned.split())


def token_similarity(name_a: str, name_b: str) -> float:
    """Compute token overlap similarity between two names."""
    tokens_a = tokenize(name_a)
    tokens_b = tokenize(name_b)

    if not tokens_a or not tokens_b:
        return 0.0

    overlap = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)

    return overlap / union if union > 0 else 0.0


class EntityResolver:
    """3-stage entity resolution to prevent knowledge graph duplicates.

    Stage 1: Exact match (case-insensitive)
    Stage 2: Normalized match (strip noise, apply equivalents)
    Stage 3: Token overlap fuzzy match (configurable threshold)
    """

    def __init__(self, empire_id: str = "", fuzzy_threshold: float = 0.6):
        self.empire_id = empire_id
        self.fuzzy_threshold = fuzzy_threshold
        self._name_cache: dict[str, list[dict]] | None = None

    def resolve(self, name: str, entity_type: str = "") -> ResolutionResult:
        """Resolve an entity name against existing knowledge graph.

        Args:
            name: Entity name to resolve.
            entity_type: Optional type filter.

        Returns:
            ResolutionResult with match info.
        """
        existing = self._get_existing_entities(entity_type)
        result = ResolutionResult(input_name=name)

        if not existing:
            result.action = "create"
            return result

        # Stage 1: Exact match (case-insensitive)
        name_lower = name.lower().strip()
        for entity in existing:
            if entity["name"].lower().strip() == name_lower:
                result.resolved = True
                result.match = ResolutionMatch(
                    existing_id=entity["id"],
                    existing_name=entity["name"],
                    match_stage=1,
                    similarity=1.0,
                )
                result.action = "merge"
                return result

        # Stage 2: Normalized match
        name_normalized = normalize_name(name)
        for entity in existing:
            entity_normalized = normalize_name(entity["name"])
            if name_normalized == entity_normalized:
                result.resolved = True
                result.match = ResolutionMatch(
                    existing_id=entity["id"],
                    existing_name=entity["name"],
                    match_stage=2,
                    similarity=0.95,
                )
                result.action = "merge"
                return result

        # Stage 3: Token overlap fuzzy match
        best_sim = 0.0
        best_entity = None
        for entity in existing:
            sim = token_similarity(name, entity["name"])
            if sim > best_sim:
                best_sim = sim
                best_entity = entity

        if best_sim >= self.fuzzy_threshold and best_entity:
            result.resolved = True
            result.match = ResolutionMatch(
                existing_id=best_entity["id"],
                existing_name=best_entity["name"],
                match_stage=3,
                similarity=best_sim,
            )
            result.action = "merge"
            return result

        # No match — create new
        result.action = "create"
        return result

    def resolve_batch(self, names: list[str], entity_type: str = "") -> list[ResolutionResult]:
        """Resolve multiple entity names."""
        return [self.resolve(name, entity_type) for name in names]

    def resolve_and_get_id(self, name: str, entity_type: str = "") -> tuple[str, str]:
        """Resolve a name and return (entity_id, action).

        Returns:
            (entity_id, "merge"|"create"). If merge, entity_id is the existing ID.
            If create, entity_id is empty.
        """
        result = self.resolve(name, entity_type)
        if result.resolved and result.match:
            return result.match.existing_id, "merge"
        return "", "create"

    def _get_existing_entities(self, entity_type: str = "") -> list[dict]:
        """Get existing entities from the knowledge graph."""
        try:
            from db.engine import get_session
            from db.repositories.knowledge import KnowledgeRepository
            session = get_session()
            repo = KnowledgeRepository(session)

            entities = repo.get_by_empire(self.empire_id, entity_type=entity_type or None, limit=1000)
            return [{"id": e.id, "name": e.name, "type": e.entity_type} for e in entities]

        except Exception as e:
            logger.warning("Failed to load entities for resolution: %s", e)
            return []

    def find_duplicates(self) -> list[list[dict]]:
        """Find all potential duplicate groups in the knowledge graph."""
        existing = self._get_existing_entities()
        groups: dict[str, list[dict]] = {}

        for entity in existing:
            normalized = normalize_name(entity["name"])
            if normalized not in groups:
                groups[normalized] = []
            groups[normalized].append(entity)

        # Return groups with 2+ entities
        return [group for group in groups.values() if len(group) > 1]

    def merge_duplicates(self) -> int:
        """Find and merge all duplicate entities."""
        from core.knowledge.graph import KnowledgeGraph
        graph = KnowledgeGraph(self.empire_id)

        groups = self.find_duplicates()
        merged = 0

        for group in groups:
            names = [e["name"] for e in group]
            result = graph.merge_entities(names)
            if result:
                merged += len(group) - 1
                logger.info("Merged %d entities: %s", len(group), names)

        return merged
