"""Full-text and semantic search for the knowledge system."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""
    entity_id: str = ""
    name: str = ""
    entity_type: str = ""
    description: str = ""
    confidence: float = 0.0
    relevance_score: float = 0.0
    match_type: str = "text"  # text, semantic, hybrid
    snippet: str = ""


@dataclass
class SearchResponse:
    """Response from a search query."""
    query: str = ""
    results: list[SearchResult] = field(default_factory=list)
    total_found: int = 0
    search_time_ms: float = 0.0
    search_type: str = "text"


@dataclass
class FacetCount:
    """Count of results per facet value."""
    value: str
    count: int


@dataclass
class SearchFacets:
    """Faceted search results."""
    entity_types: list[FacetCount] = field(default_factory=list)
    confidence_ranges: list[FacetCount] = field(default_factory=list)


class KnowledgeSearchEngine:
    """Full-text and semantic search for the knowledge graph.

    Supports:
    - Full-text search using SQLite FTS5
    - Semantic search using embedding similarity
    - Hybrid search combining both
    - Faceted search with aggregations
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self._repo = None

    def _get_repo(self):
        """Get a fresh repository with its own session."""
        from db.engine import get_session
        from db.repositories.knowledge import KnowledgeRepository
        return KnowledgeRepository(get_session())

    def text_search(
        self,
        query: str,
        entity_type: str = "",
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> SearchResponse:
        """Full-text search using LIKE queries.

        Args:
            query: Search query.
            entity_type: Optional entity type filter.
            min_confidence: Minimum confidence threshold.
            limit: Maximum results.

        Returns:
            SearchResponse.
        """
        import time
        start = time.time()

        repo = self._get_repo()
        entities = repo.search_entities(query, self.empire_id, entity_type or None, limit)

        results = []
        for entity in entities:
            if entity.confidence < min_confidence:
                continue

            # Calculate relevance
            relevance = self._text_relevance(query, entity.name, entity.description)

            results.append(SearchResult(
                entity_id=entity.id,
                name=entity.name,
                entity_type=entity.entity_type,
                description=entity.description,
                confidence=entity.confidence,
                relevance_score=relevance,
                match_type="text",
                snippet=self._generate_snippet(entity.description, query),
            ))

        # Sort by relevance
        results.sort(key=lambda r: r.relevance_score, reverse=True)

        return SearchResponse(
            query=query,
            results=results[:limit],
            total_found=len(results),
            search_time_ms=(time.time() - start) * 1000,
            search_type="text",
        )

    def semantic_search(
        self,
        query: str,
        limit: int = 20,
        min_similarity: float = 0.5,
    ) -> SearchResponse:
        """Semantic search using embedding similarity.

        Args:
            query: Search query.
            limit: Maximum results.
            min_similarity: Minimum cosine similarity.

        Returns:
            SearchResponse.
        """
        import time
        start = time.time()

        # Get query embedding
        embedding = self._get_embedding(query)
        if not embedding:
            return self.text_search(query, limit=limit)  # Fallback to text search

        repo = self._get_repo()
        similar = repo.similarity_search(
            embedding=embedding,
            empire_id=self.empire_id,
            limit=limit,
            min_similarity=min_similarity,
        )

        results = [
            SearchResult(
                entity_id=item["entity"].id,
                name=item["entity"].name,
                entity_type=item["entity"].entity_type,
                description=item["entity"].description,
                confidence=item["entity"].confidence,
                relevance_score=item["similarity"],
                match_type="semantic",
                snippet=item["entity"].description[:200],
            )
            for item in similar
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_found=len(results),
            search_time_ms=(time.time() - start) * 1000,
            search_type="semantic",
        )

    def hybrid_search(
        self,
        query: str,
        entity_type: str = "",
        limit: int = 20,
        text_weight: float = 0.4,
        semantic_weight: float = 0.6,
    ) -> SearchResponse:
        """Hybrid search combining text and semantic search.

        Args:
            query: Search query.
            entity_type: Optional entity type filter.
            limit: Maximum results.
            text_weight: Weight for text search scores.
            semantic_weight: Weight for semantic search scores.

        Returns:
            SearchResponse with combined results.
        """
        import time
        start = time.time()

        # Run both searches
        text_results = self.text_search(query, entity_type, limit=limit * 2)
        semantic_results = self.semantic_search(query, limit=limit * 2)

        # Merge results
        entity_scores: dict[str, dict] = {}

        for r in text_results.results:
            entity_scores[r.entity_id] = {
                "result": r,
                "text_score": r.relevance_score,
                "semantic_score": 0.0,
            }

        for r in semantic_results.results:
            if r.entity_id in entity_scores:
                entity_scores[r.entity_id]["semantic_score"] = r.relevance_score
            else:
                entity_scores[r.entity_id] = {
                    "result": r,
                    "text_score": 0.0,
                    "semantic_score": r.relevance_score,
                }

        # Calculate combined scores
        results = []
        for entity_id, scores in entity_scores.items():
            combined = (
                scores["text_score"] * text_weight +
                scores["semantic_score"] * semantic_weight
            )
            result = scores["result"]
            result.relevance_score = combined
            result.match_type = "hybrid"
            results.append(result)

        results.sort(key=lambda r: r.relevance_score, reverse=True)

        return SearchResponse(
            query=query,
            results=results[:limit],
            total_found=len(results),
            search_time_ms=(time.time() - start) * 1000,
            search_type="hybrid",
        )

    def faceted_search(
        self,
        query: str,
        limit: int = 20,
    ) -> tuple[SearchResponse, SearchFacets]:
        """Search with faceted aggregations.

        Returns:
            Tuple of (SearchResponse, SearchFacets).
        """
        response = self.text_search(query, limit=limit * 2)

        # Build facets
        type_counts: dict[str, int] = {}
        confidence_ranges: dict[str, int] = {"0.0-0.3": 0, "0.3-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}

        for r in response.results:
            type_counts[r.entity_type] = type_counts.get(r.entity_type, 0) + 1

            if r.confidence < 0.3:
                confidence_ranges["0.0-0.3"] += 1
            elif r.confidence < 0.6:
                confidence_ranges["0.3-0.6"] += 1
            elif r.confidence < 0.8:
                confidence_ranges["0.6-0.8"] += 1
            else:
                confidence_ranges["0.8-1.0"] += 1

        facets = SearchFacets(
            entity_types=[FacetCount(v, c) for v, c in sorted(type_counts.items(), key=lambda x: -x[1])],
            confidence_ranges=[FacetCount(v, c) for v, c in confidence_ranges.items() if c > 0],
        )

        response.results = response.results[:limit]
        return response, facets

    def suggest(self, query: str, limit: int = 5) -> list[str]:
        """Get search suggestions based on partial query.

        Args:
            query: Partial query.
            limit: Maximum suggestions.

        Returns:
            List of suggestion strings.
        """
        repo = self._get_repo()
        entities = repo.search_entities(query, self.empire_id, limit=limit)
        return [e.name for e in entities]

    def find_related(self, entity_name: str, limit: int = 10) -> list[SearchResult]:
        """Find entities related to a given entity.

        Args:
            entity_name: Entity to find relations for.
            limit: Maximum results.

        Returns:
            List of related entity results.
        """
        repo = self._get_repo()
        entity = repo.get_by_name(entity_name, self.empire_id)

        if not entity:
            return []

        neighbors = repo.get_neighbors(entity.id, max_depth=2)

        return [
            SearchResult(
                entity_id=n["entity"].id,
                name=n["entity"].name,
                entity_type=n["entity"].entity_type,
                description=n["entity"].description,
                confidence=n["entity"].confidence,
                relevance_score=1.0 / n["depth"],
                match_type="relation",
            )
            for n in neighbors[:limit]
        ]

    def _text_relevance(self, query: str, name: str, description: str) -> float:
        """Calculate text relevance score."""
        query_lower = query.lower()
        name_lower = name.lower()
        desc_lower = description.lower() if description else ""

        score = 0.0

        # Exact name match
        if query_lower == name_lower:
            score += 1.0
        # Name contains query
        elif query_lower in name_lower:
            score += 0.8
        # Name starts with query
        elif name_lower.startswith(query_lower):
            score += 0.7

        # Query words in description
        query_words = set(query_lower.split())
        if desc_lower:
            desc_words = set(desc_lower.split())
            overlap = len(query_words & desc_words)
            if query_words:
                score += 0.3 * (overlap / len(query_words))

        return min(1.0, score)

    def _generate_snippet(self, text: str, query: str, max_length: int = 200) -> str:
        """Generate a relevant snippet from text around the query."""
        if not text:
            return ""

        query_lower = query.lower()
        text_lower = text.lower()

        idx = text_lower.find(query_lower)
        if idx == -1:
            return text[:max_length]

        start = max(0, idx - 50)
        end = min(len(text), idx + len(query) + 150)
        snippet = text[start:end]

        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."

        return snippet

    def _get_embedding(self, text: str) -> list[float] | None:
        """Get embedding vector for text."""
        try:
            from llm.openai import OpenAIClient
            client = OpenAIClient()
            return client.create_embedding(text)
        except Exception:
            return None
