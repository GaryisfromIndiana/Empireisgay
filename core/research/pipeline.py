"""Research Pipeline — orchestrated multi-stage research from topic to knowledge.

Chains together: search → scrape → extract → deepen → synthesize
into a single pipeline that can be triggered from the God Panel,
API, or scheduler.

Stages:
  1. SEARCH  — web search for the topic (news + papers + general)
  2. SCRAPE  — scrape top results for full content
  3. EXTRACT — entity + relation extraction from scraped content
  4. DEEPEN  — run iterative deepening if signal is high
  5. SYNTHESIZE — LLM synthesis of all findings into a report
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PipelineStage:
    """Result of a single pipeline stage."""
    name: str
    success: bool = True
    items_produced: int = 0
    duration_seconds: float = 0.0
    error: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Full result of a research pipeline run."""
    topic: str
    stages: list[PipelineStage] = field(default_factory=list)
    total_entities: int = 0
    total_relations: int = 0
    total_memories: int = 0
    synthesis: str = ""
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    success: bool = True

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "stages": [
                {"name": s.name, "success": s.success, "items": s.items_produced,
                 "duration": round(s.duration_seconds, 1), "error": s.error}
                for s in self.stages
            ],
            "total_entities": self.total_entities,
            "total_relations": self.total_relations,
            "total_memories": self.total_memories,
            "synthesis": self.synthesis[:2000] if self.synthesis else "",
            "cost_usd": round(self.cost_usd, 4),
            "duration_seconds": round(self.duration_seconds, 1),
            "success": self.success,
        }


class ResearchPipeline:
    """Orchestrated multi-stage research pipeline.

    Usage:
        pipeline = ResearchPipeline("empire-alpha")
        result = pipeline.run("Model Context Protocol MCP")
        # result.synthesis contains the final report
        # result.total_entities shows how many KG entries were created
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id

    def run(
        self,
        topic: str,
        depth: str = "standard",
        max_sources: int = 8,
        skip_stages: list[str] | None = None,
    ) -> PipelineResult:
        """Run the full research pipeline on a topic.

        Args:
            topic: Research topic.
            depth: "shallow" (search only), "standard" (search+scrape+extract),
                   "deep" (all stages including synthesis).
            max_sources: Maximum sources to search.
            skip_stages: Stages to skip (e.g., ["SCRAPE", "DEEPEN"]).

        Returns:
            PipelineResult with all stage results.
        """
        start = time.time()
        result = PipelineResult(topic=topic)
        skip = set(s.upper() for s in (skip_stages or []))

        logger.info("Research pipeline START: '%s' (depth=%s)", topic, depth)

        # Stage 1: SEARCH
        if "SEARCH" not in skip:
            stage = self._stage_search(topic, max_sources)
            result.stages.append(stage)
            if not stage.success:
                result.success = False
                result.duration_seconds = time.time() - start
                return result

        # Stage 2: SCRAPE (skip for shallow)
        scraped_content = []
        if depth != "shallow" and "SCRAPE" not in skip:
            stage = self._stage_scrape(topic, result.stages[0].data.get("urls", []))
            result.stages.append(stage)
            scraped_content = stage.data.get("content_pieces", [])

        # Stage 3: EXTRACT
        if depth != "shallow" and "EXTRACT" not in skip:
            search_summary = result.stages[0].data.get("summary", "") if result.stages else ""
            stage = self._stage_extract(topic, search_summary, scraped_content)
            result.stages.append(stage)
            result.total_entities += stage.data.get("entities", 0)
            result.total_relations += stage.data.get("relations", 0)
            result.total_memories += stage.data.get("memories", 0)

        # Stage 4: DEEPEN (only for deep mode)
        if depth == "deep" and "DEEPEN" not in skip:
            stage = self._stage_deepen(topic)
            result.stages.append(stage)
            result.total_entities += stage.data.get("new_entities", 0)
            result.total_relations += stage.data.get("new_relations", 0)

        # Stage 5: SYNTHESIZE (only for deep or standard)
        if depth in ("deep", "standard") and "SYNTHESIZE" not in skip:
            search_summary = result.stages[0].data.get("summary", "") if result.stages else ""
            stage = self._stage_synthesize(topic, search_summary, scraped_content)
            result.stages.append(stage)
            result.synthesis = stage.data.get("synthesis", "")
            result.cost_usd += stage.data.get("cost_usd", 0)
            result.total_memories += 1 if stage.success else 0

        result.duration_seconds = time.time() - start
        result.success = all(s.success for s in result.stages)

        logger.info(
            "Research pipeline DONE: '%s' — %d entities, %d relations, %.1fs, $%.4f",
            topic, result.total_entities, result.total_relations,
            result.duration_seconds, result.cost_usd,
        )
        return result

    # ── Stage implementations ────────────────────────────────────────

    def _stage_search(self, topic: str, max_sources: int) -> PipelineStage:
        """Stage 1: Multi-query web search."""
        start = time.time()
        stage = PipelineStage(name="SEARCH")

        try:
            from core.search.web import WebSearcher
            searcher = WebSearcher(self.empire_id)

            # LLM-refined search: generates targeted queries from the topic
            search_data = searcher.search_and_summarize(topic, max_results=max_sources, refine=True)

            all_results = search_data.get("results", [])
            all_urls = [r["url"] for r in all_results if r.get("url")]
            queries = search_data.get("queries_used", [topic])

            stage.items_produced = len(all_results)
            stage.data = {
                "results": len(all_results),
                "urls": all_urls[:max_sources],
                "summary": search_data.get("summary", "")[:6000],
                "queries": queries,
            }

        except Exception as e:
            stage.success = False
            stage.error = str(e)
            logger.warning("Pipeline SEARCH failed for '%s': %s", topic, e)

        stage.duration_seconds = time.time() - start
        return stage

    def _stage_scrape(self, topic: str, urls: list[str]) -> PipelineStage:
        """Stage 2: Scrape top URLs for full content."""
        start = time.time()
        stage = PipelineStage(name="SCRAPE")

        content_pieces = []
        try:
            from core.search.scraper import WebScraper
            scraper = WebScraper(self.empire_id)

            for url in urls[:5]:  # Cap at 5 scrapes
                try:
                    result = scraper.scrape_and_store(url)
                    if result.get("success"):
                        content = result.get("content", "")
                        if content:
                            content_pieces.append({
                                "url": url,
                                "title": result.get("title", ""),
                                "content": content[:3000],
                            })
                except Exception as e:
                    logger.debug("Scrape failed for %s: %s", url, e)

            stage.items_produced = len(content_pieces)
            stage.data = {"content_pieces": content_pieces, "attempted": len(urls[:5])}

        except Exception as e:
            stage.success = False
            stage.error = str(e)
            logger.warning("Pipeline SCRAPE failed: %s", e)

        stage.duration_seconds = time.time() - start
        return stage

    def _stage_extract(
        self, topic: str, search_summary: str, scraped_content: list[dict]
    ) -> PipelineStage:
        """Stage 3: Entity and relation extraction."""
        start = time.time()
        stage = PipelineStage(name="EXTRACT")

        total_entities = 0
        total_relations = 0
        total_memories = 0

        try:
            from core.knowledge.entities import EntityExtractor
            from core.knowledge.graph import KnowledgeGraph
            from core.memory.manager import MemoryManager

            extractor = EntityExtractor()
            graph = KnowledgeGraph(self.empire_id)
            mm = MemoryManager(self.empire_id)

            # Extract from search summary
            texts_to_process = [search_summary[:5000]] if search_summary else []

            # Also extract from scraped content
            for piece in scraped_content:
                texts_to_process.append(piece.get("content", "")[:4000])

            for text in texts_to_process:
                if not text.strip():
                    continue

                # Extract entities
                extraction = extractor.extract_from_text(
                    text,
                    context=f"Research pipeline on: {topic}",
                    max_entities=15,
                )

                if extraction.entities:
                    before = graph.get_stats().entity_count
                    for entity in extraction.entities:
                        graph.add_entity(
                            name=entity.get("name", ""),
                            entity_type=entity.get("entity_type", "concept"),
                            description=entity.get("description", ""),
                            confidence=entity.get("confidence", 0.65),
                            tags=["pipeline", topic.replace(" ", "_")[:30]],
                            attributes={"pipeline_topic": topic},
                        )
                    total_entities += max(0, graph.get_stats().entity_count - before)

                if extraction.relations:
                    before_r = graph.get_stats().relation_count
                    for rel in extraction.relations:
                        graph.add_relation(
                            source_name=rel.get("source", ""),
                            target_name=rel.get("target", ""),
                            relation_type=rel.get("type", "related_to"),
                            confidence=rel.get("confidence", 0.6),
                        )
                    total_relations += max(0, graph.get_stats().relation_count - before_r)

            # Store research memory
            mm.store(
                content=f"Research Pipeline: {topic}\n\n{search_summary[:3000]}",
                memory_type="semantic",
                title=f"Pipeline: {topic[:60]}",
                category="research_pipeline",
                importance=0.7,
                tags=["pipeline", "research"],
                source_type="pipeline",
                metadata={"topic": topic, "entities": total_entities, "relations": total_relations},
            )
            total_memories = 1

            stage.items_produced = total_entities + total_relations
            stage.data = {
                "entities": total_entities,
                "relations": total_relations,
                "memories": total_memories,
                "texts_processed": len(texts_to_process),
            }

        except Exception as e:
            stage.success = False
            stage.error = str(e)
            logger.warning("Pipeline EXTRACT failed: %s", e)

        stage.duration_seconds = time.time() - start
        return stage

    def _stage_deepen(self, topic: str) -> PipelineStage:
        """Stage 4: Iterative deepening on high-signal findings."""
        start = time.time()
        stage = PipelineStage(name="DEEPEN")

        try:
            from core.research.deepening import IterativeDeepener, DeepeningCandidate
            deepener = IterativeDeepener(self.empire_id)

            # Create a candidate directly for this topic
            candidate = DeepeningCandidate(
                topic=topic,
                entity_names=[],
                current_depth=0,
                signal_score=0.8,
                trigger_reason="pipeline deep mode",
            )

            result = deepener.deepen(candidate)
            stage.items_produced = result.new_entities + result.new_relations
            stage.data = {
                "new_entities": result.new_entities,
                "new_relations": result.new_relations,
                "queries_run": result.queries_run,
                "cost_usd": result.cost_usd,
            }

        except Exception as e:
            stage.success = False
            stage.error = str(e)
            logger.warning("Pipeline DEEPEN failed: %s", e)

        stage.duration_seconds = time.time() - start
        return stage

    def _stage_synthesize(
        self, topic: str, search_summary: str, scraped_content: list[dict]
    ) -> PipelineStage:
        """Stage 5: LLM synthesis of all findings."""
        start = time.time()
        stage = PipelineStage(name="SYNTHESIZE")

        try:
            from llm.router import ModelRouter, TaskMetadata
            from llm.base import LLMRequest, LLMMessage
            from core.memory.manager import MemoryManager

            router = ModelRouter(self.empire_id)

            # Build context from all gathered info
            context_parts = []
            if search_summary:
                context_parts.append(f"## Search Results\n{search_summary[:3000]}")
            for piece in scraped_content[:3]:
                context_parts.append(
                    f"## {piece.get('title', 'Article')}\n{piece.get('content', '')[:2000]}"
                )

            combined = "\n\n---\n\n".join(context_parts)

            prompt = (
                f"You are an AI research analyst. Synthesize these findings about "
                f"'{topic}' into a comprehensive research brief.\n\n"
                f"Include:\n"
                f"1. Key findings and developments\n"
                f"2. Major players and their positions\n"
                f"3. Technical details and capabilities\n"
                f"4. Trends and implications\n"
                f"5. Open questions for further research\n\n"
                f"Research data:\n{combined[:8000]}"
            )

            response = router.execute(
                LLMRequest(
                    messages=[LLMMessage.user(prompt)],
                    max_tokens=1500,
                    temperature=0.3,
                ),
                TaskMetadata(task_type="synthesis", complexity="complex"),
            )

            synthesis = response.content
            stage.data = {
                "synthesis": synthesis,
                "cost_usd": response.cost_usd,
                "model_used": response.model,
            }
            stage.items_produced = 1

            # Store synthesis as high-importance memory
            mm = MemoryManager(self.empire_id)
            mm.store(
                content=f"Research Synthesis: {topic}\n\n{synthesis}",
                memory_type="semantic",
                title=f"Synthesis: {topic[:60]}",
                category="research_pipeline",
                importance=0.85,
                tags=["pipeline", "synthesis", topic.replace(" ", "_")[:30]],
                source_type="pipeline",
                metadata={"topic": topic, "model": response.model},
            )

        except Exception as e:
            stage.success = False
            stage.error = str(e)
            logger.warning("Pipeline SYNTHESIZE failed: %s", e)

        stage.duration_seconds = time.time() - start
        return stage
