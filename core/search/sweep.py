"""Intelligence Sweep — proactive discovery of new AI developments.

Runs periodically to check specific sources for new information:
- HuggingFace: new models, trending repos
- GitHub: trending AI repositories
- arXiv: new papers in cs.AI, cs.CL, cs.LG
- RSS feeds: curated AI blogs and news
- Web search: targeted queries for AI developments

Novelty detection filters out what Empire already knows.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Discovery:
    """A single discovery from the sweep."""
    title: str = ""
    content: str = ""
    source: str = ""
    source_url: str = ""
    category: str = ""  # model_release, paper, framework, news, trend
    discovered_at: str = ""
    is_novel: bool = True
    importance: float = 0.5
    entity_type: str = ""
    valid_from: str = ""


@dataclass
class SweepResult:
    """Result of a full intelligence sweep."""
    sources_checked: int = 0
    total_found: int = 0
    novel_items: int = 0
    stored_memories: int = 0
    stored_entities: int = 0
    discoveries: list[Discovery] = field(default_factory=list)
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class IntelligenceSweep:
    """Proactively discovers new AI developments across multiple sources.

    Unlike passive search (user asks → Empire searches), the sweep
    actively checks known sources for new information and filters
    against what Empire already knows.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id

    def run_full_sweep(self) -> SweepResult:
        """Run a complete intelligence sweep across all sources.

        Returns:
            SweepResult with all discoveries.
        """
        start = time.time()
        result = SweepResult()

        # Run each source
        sweepers = [
            ("RSS Feeds", self._sweep_feeds),
            ("AI News", self._sweep_ai_news),
            ("HuggingFace", self._sweep_huggingface),
            ("GitHub Trending", self._sweep_github),
            ("arXiv Papers", self._sweep_arxiv),
        ]

        for source_name, sweeper_fn in sweepers:
            try:
                discoveries = sweeper_fn()
                result.sources_checked += 1
                result.total_found += len(discoveries)

                for disc in discoveries:
                    disc.discovered_at = datetime.now(timezone.utc).isoformat()

                    # Novelty check
                    disc.is_novel = self._is_novel(disc)
                    if disc.is_novel:
                        result.novel_items += 1
                        result.discoveries.append(disc)

                        # Store novel discoveries
                        stored = self._store_discovery(disc)
                        result.stored_memories += stored.get("memories", 0)
                        result.stored_entities += stored.get("entities", 0)

                logger.info("Sweep %s: %d found, %d novel", source_name, len(discoveries),
                           sum(1 for d in discoveries if d.is_novel))

            except Exception as e:
                result.errors.append(f"{source_name}: {e}")
                logger.warning("Sweep %s failed: %s", source_name, e)

        result.duration_seconds = time.time() - start
        logger.info(
            "Intelligence sweep complete: %d sources, %d found, %d novel, %d stored (%.1fs)",
            result.sources_checked, result.total_found, result.novel_items,
            result.stored_memories, result.duration_seconds,
        )

        return result

    def _sweep_feeds(self) -> list[Discovery]:
        """Sweep RSS feeds for new entries."""
        from core.search.feeds import FeedReader
        reader = FeedReader(self.empire_id)

        discoveries = []
        entries = reader.fetch_latest(max_total=20, max_per_feed=3)

        for entry in entries:
            discoveries.append(Discovery(
                title=entry.title,
                content=entry.summary[:1000],
                source=entry.source_feed,
                source_url=entry.url,
                category="news",
                importance=0.5,
                valid_from=entry.published,
            ))

        return discoveries

    def _sweep_ai_news(self) -> list[Discovery]:
        """Search for latest AI news across key topics."""
        from core.search.web import WebSearcher
        searcher = WebSearcher(self.empire_id)

        topics = [
            "new AI model release today",
            "AI agent breakthrough",
            "open source LLM new",
        ]

        discoveries = []
        for topic in topics:
            try:
                news = searcher.search_ai_news(topic, max_results=3)
                for r in news.results:
                    discoveries.append(Discovery(
                        title=r.title,
                        content=r.snippet,
                        source=r.source,
                        source_url=r.url,
                        category="news",
                        importance=0.55,
                        valid_from=r.published,
                    ))
            except Exception as e:
                logger.debug("News search failed for '%s': %s", topic, e)

        return discoveries

    def _sweep_huggingface(self) -> list[Discovery]:
        """Check HuggingFace for new trending models."""
        from core.search.web import WebSearcher
        searcher = WebSearcher(self.empire_id)

        discoveries = []
        try:
            results = searcher.search("site:huggingface.co new model trending", max_results=5)
            for r in results.results:
                discoveries.append(Discovery(
                    title=r.title,
                    content=r.snippet,
                    source="huggingface.co",
                    source_url=r.url,
                    category="model_release",
                    importance=0.6,
                    entity_type="ai_model",
                ))
        except Exception as e:
            logger.debug("HuggingFace sweep failed: %s", e)

        return discoveries

    def _sweep_github(self) -> list[Discovery]:
        """Check GitHub for trending AI repositories."""
        from core.search.web import WebSearcher
        searcher = WebSearcher(self.empire_id)

        discoveries = []
        try:
            results = searcher.search("site:github.com AI LLM agent trending stars", max_results=5)
            for r in results.results:
                discoveries.append(Discovery(
                    title=r.title,
                    content=r.snippet,
                    source="github.com",
                    source_url=r.url,
                    category="framework",
                    importance=0.55,
                    entity_type="framework",
                ))
        except Exception as e:
            logger.debug("GitHub sweep failed: %s", e)

        return discoveries

    def _sweep_arxiv(self) -> list[Discovery]:
        """Check arXiv for new AI papers."""
        from core.search.feeds import FeedReader
        reader = FeedReader(self.empire_id)

        discoveries = []
        # arXiv feeds are already in our feed list — just filter for them
        entries = reader.fetch_latest(categories=["research"], max_total=10, max_per_feed=5)

        for entry in entries:
            discoveries.append(Discovery(
                title=entry.title,
                content=entry.summary[:800],
                source="arxiv.org",
                source_url=entry.url,
                category="paper",
                importance=0.6,
                entity_type="paper",
                valid_from=entry.published,
            ))

        return discoveries

    def _is_novel(self, discovery: Discovery) -> bool:
        """Check if a discovery is novel (not already known).

        Uses both memory and knowledge graph to check.
        """
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)

        # Check if URL already stored
        if discovery.source_url:
            existing = mm.recall(query=discovery.source_url, memory_types=["semantic"], limit=1)
            if any(discovery.source_url in m.get("content", "") for m in existing):
                return False

        # Check if title already known
        if discovery.title:
            existing = mm.recall(query=discovery.title[:100], memory_types=["semantic"], limit=3)
            for mem in existing:
                title_words = set(discovery.title.lower().split())
                mem_words = set(mem.get("title", "").lower().split())
                if len(title_words) > 3:
                    overlap = len(title_words & mem_words) / len(title_words)
                    if overlap > 0.6:
                        return False

        # Check knowledge graph
        from core.knowledge.graph import KnowledgeGraph
        graph = KnowledgeGraph(self.empire_id)
        if discovery.title:
            entities = graph.find_entities(query=discovery.title[:60], limit=2)
            for entity in entities:
                if discovery.title.lower()[:30] in entity.name.lower():
                    return False

        return True

    def _store_discovery(self, discovery: Discovery) -> dict:
        """Store a novel discovery in memory and knowledge graph."""
        stored = {"memories": 0, "entities": 0}

        try:
            # Store in bi-temporal memory
            from core.memory.bitemporal import BiTemporalMemory
            bt = BiTemporalMemory(self.empire_id)
            bt.store_smart(
                content=f"{discovery.title}\n\nSource: {discovery.source}\n{discovery.content}",
                title=f"Discovery: {discovery.title[:80]}",
                category=f"sweep_{discovery.category}",
                valid_from=discovery.valid_from or None,
                importance=discovery.importance,
                confidence=0.7,
                source=discovery.source,
                source_url=discovery.source_url,
                tags=["sweep", discovery.category, discovery.source],
            )
            stored["memories"] = 1
        except Exception as e:
            logger.debug("Failed to store discovery in memory: %s", e)

        try:
            # Store in knowledge graph if entity type known
            if discovery.entity_type and discovery.title:
                from core.knowledge.graph import KnowledgeGraph
                graph = KnowledgeGraph(self.empire_id)
                graph.add_entity(
                    name=discovery.title[:100],
                    entity_type=discovery.entity_type,
                    description=discovery.content[:500],
                    confidence=0.6,
                    tags=["sweep", discovery.category],
                    valid_from=discovery.valid_from,
                )
                stored["entities"] = 1
        except Exception as e:
            logger.debug("Failed to store discovery in knowledge graph: %s", e)

        return stored

    def get_recent_discoveries(self, limit: int = 20) -> list[dict]:
        """Get recent sweep discoveries from memory."""
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        return mm.recall(query="Discovery sweep", memory_types=["semantic"], limit=limit)
