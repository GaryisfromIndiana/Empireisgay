"""Web search — gives lieutenants the ability to search the internet."""

from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

try:
    from ddgs import DDGS
except ImportError:
    DDGS = importlib.import_module("duckduckgo_search").DDGS

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single web search result."""
    title: str = ""
    url: str = ""
    snippet: str = ""
    source: str = ""
    published: str = ""


@dataclass
class WebSearchResponse:
    """Response from a web search."""
    query: str = ""
    results: list[SearchResult] = field(default_factory=list)
    total_results: int = 0
    search_time_ms: float = 0.0
    source: str = "duckduckgo"


@dataclass
class NewsResult:
    """A news article result."""
    title: str = ""
    url: str = ""
    snippet: str = ""
    source: str = ""
    published: str = ""
    image: str = ""


@dataclass
class NewsSearchResponse:
    """Response from a news search."""
    query: str = ""
    results: list[NewsResult] = field(default_factory=list)
    total_results: int = 0


class WebSearcher:
    """Web search engine for Empire lieutenants.

    Uses DuckDuckGo for web and news search — no API key needed.
    Results are formatted for LLM consumption and stored in the
    knowledge graph when relevant entities are found.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self._ddgs = DDGS()

    def search(
        self,
        query: str,
        max_results: int = 10,
        region: str = "wt-wt",
        time_range: str = "",
    ) -> WebSearchResponse:
        """Search the web.

        Args:
            query: Search query.
            max_results: Maximum results.
            region: Region code (wt-wt = worldwide).
            time_range: Time filter (d=day, w=week, m=month, y=year).

        Returns:
            WebSearchResponse.
        """
        start = time.time()

        try:
            try:
                # ddgs >= 8.0 API (positional query arg)
                raw_results = list(self._ddgs.text(
                    query, max_results=max_results, region=region,
                    **({"timelimit": time_range} if time_range else {}),
                ))
            except TypeError:
                # Fallback for older duckduckgo-search API
                raw_results = list(self._ddgs.text(
                    keywords=query, max_results=max_results, region=region,
                    **({"timelimit": time_range} if time_range else {}),
                ))

            results = [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", r.get("link", "")),
                    snippet=r.get("body", r.get("snippet", "")),
                    source=self._extract_domain(r.get("href", "")),
                )
                for r in raw_results
            ]

            elapsed = (time.time() - start) * 1000
            logger.info("Web search: '%s' → %d results (%.0fms)", query, len(results), elapsed)

            return WebSearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                search_time_ms=elapsed,
            )

        except Exception as e:
            logger.error("Web search failed for '%s': %s", query, e)
            return WebSearchResponse(query=query, search_time_ms=(time.time() - start) * 1000)

    def search_news(
        self,
        query: str,
        max_results: int = 10,
        time_range: str = "w",
    ) -> NewsSearchResponse:
        """Search news articles.

        Args:
            query: Search query.
            max_results: Maximum results.
            time_range: Time filter (d=day, w=week, m=month).

        Returns:
            NewsSearchResponse.
        """
        try:
            try:
                raw_results = list(self._ddgs.news(
                    query, max_results=max_results, timelimit=time_range,
                ))
            except TypeError:
                raw_results = list(self._ddgs.news(
                    keywords=query, max_results=max_results, timelimit=time_range,
                ))

            results = [
                NewsResult(
                    title=r.get("title", ""),
                    url=r.get("url", r.get("link", "")),
                    snippet=r.get("body", r.get("excerpt", "")),
                    source=r.get("source", self._extract_domain(r.get("url", ""))),
                    published=r.get("date", ""),
                    image=r.get("image", ""),
                )
                for r in raw_results
            ]

            logger.info("News search: '%s' → %d results", query, len(results))

            return NewsSearchResponse(
                query=query,
                results=results,
                total_results=len(results),
            )

        except Exception as e:
            logger.error("News search failed for '%s': %s", query, e)
            return NewsSearchResponse(query=query)

    def search_ai_news(self, topic: str = "", max_results: int = 10) -> NewsSearchResponse:
        """Search for AI-specific news.

        Args:
            topic: Specific AI topic (e.g., "Claude", "GPT-5", "open source LLM").
            max_results: Maximum results.

        Returns:
            NewsSearchResponse.
        """
        query = f"AI {topic}" if topic else "artificial intelligence AI news"
        return self.search_news(query, max_results=max_results, time_range="w")

    def search_ai_papers(self, topic: str, max_results: int = 10) -> WebSearchResponse:
        """Search for AI research papers.

        Args:
            topic: Research topic.
            max_results: Maximum results.

        Returns:
            WebSearchResponse.
        """
        query = f"{topic} site:arxiv.org OR site:openreview.net OR site:papers.nips.cc"
        return self.search(query, max_results=max_results)

    def search_ai_models(self, model_name: str = "", max_results: int = 10) -> WebSearchResponse:
        """Search for AI model information.

        Args:
            model_name: Model name to search for.
            max_results: Maximum results.

        Returns:
            WebSearchResponse.
        """
        query = f"{model_name} AI model" if model_name else "latest AI model release 2026"
        return self.search(query, max_results=max_results, time_range="m")

    def refine_query(self, raw_query: str, max_queries: int = 4) -> list[str]:
        """Use an LLM to expand a raw query into multiple targeted search queries.

        Takes a natural-language topic and generates specific, diverse queries
        that cover different angles — news, technical, academic, competitive.
        Uses Haiku for speed and cost.

        Args:
            raw_query: The raw user query or topic.
            max_queries: Maximum number of refined queries to generate.

        Returns:
            List of refined search query strings. Falls back to [raw_query]
            on any error.
        """
        try:
            from llm.router import ModelRouter, TaskMetadata
            from llm.base import LLMRequest, LLMMessage
            import json

            router = ModelRouter(self.empire_id)

            prompt = (
                "You are a search query optimizer for an AI research system. "
                "Given a research topic, generate exactly "
                f"{max_queries} targeted web search queries that will find "
                "the most relevant, recent, and diverse results.\n\n"
                "Each query should cover a different angle:\n"
                "- Recent news and announcements\n"
                "- Technical details, specs, or documentation\n"
                "- Academic papers or research\n"
                "- Comparisons, benchmarks, or competitive analysis\n\n"
                "Make queries specific and search-engine-optimized "
                "(use key terms, not full sentences).\n\n"
                f'Topic: "{raw_query}"\n\n'
                "Respond with ONLY a JSON array of query strings, nothing else.\n"
                f'Example: ["query 1", "query 2", "query 3", "query 4"]'
            )

            response = router.execute(
                LLMRequest(
                    messages=[LLMMessage.user(prompt)],
                    max_tokens=200,
                    temperature=0.4,
                ),
                TaskMetadata(task_type="extraction", complexity="simple"),
            )

            text = response.content.strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                queries = json.loads(text[start:end])
                if isinstance(queries, list) and queries:
                    refined = [q for q in queries if isinstance(q, str) and q.strip()]
                    if refined:
                        logger.info(
                            "Query refined: '%s' → %d queries (cost $%.4f)",
                            raw_query, len(refined), response.cost_usd,
                        )
                        return refined[:max_queries]

        except Exception as e:
            logger.debug("Query refinement failed, using raw query: %s", e)

        return [raw_query]

    def search_and_summarize(
        self,
        query: str,
        max_results: int = 5,
        refine: bool = True,
    ) -> dict:
        """Search the web and create an LLM-ready summary.

        Args:
            query: Search query.
            max_results: Maximum results.
            refine: Whether to use LLM query refinement.

        Returns:
            Dict with results formatted for LLM prompt injection.
        """
        if refine:
            queries = self.refine_query(query)
        else:
            queries = [query]

        all_results = []
        seen_urls = set()
        per_query = max(2, max_results // len(queries))

        for q in queries:
            response = self.search(q, max_results=per_query)
            for r in response.results:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)

        if not all_results:
            return {"query": query, "found": False, "summary": "No results found."}

        # Format for LLM consumption
        formatted = []
        for i, r in enumerate(all_results[:max_results], 1):
            formatted.append(
                f"[{i}] {r.title}\n"
                f"    Source: {r.source}\n"
                f"    {r.snippet}"
            )

        summary = "\n\n".join(formatted)

        return {
            "query": query,
            "found": True,
            "result_count": len(all_results),
            "queries_used": queries,
            "summary": summary,
            "results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet}
                for r in all_results[:max_results]
            ],
            "search_time_ms": 0.0,
        }

    def search_and_store(
        self,
        query: str,
        max_results: int = 5,
    ) -> dict:
        """Search the web and store relevant findings in knowledge + memory.

        Args:
            query: Search query.
            max_results: Maximum results.

        Returns:
            Dict with search results and storage stats.
        """
        search_data = self.search_and_summarize(query, max_results)

        if not search_data.get("found"):
            return search_data

        stored_entities = 0
        stored_memories = 0

        try:
            # Store as semantic memory
            from core.memory.manager import MemoryManager
            mm = MemoryManager(self.empire_id)
            mm.store(
                content=f"Web search: {query}\n\n{search_data['summary'][:3000]}",
                memory_type="semantic",
                title=f"Web: {query[:80]}",
                category="web_research",
                importance=0.6,
                tags=["web_search", "research"],
                source_type="web_search",
                metadata={"query": query, "result_count": search_data["result_count"]},
            )
            stored_memories = 1

            # Extract entities from results
            from core.knowledge.entities import EntityExtractor
            extractor = EntityExtractor()
            extraction = extractor.extract_from_text(
                search_data["summary"][:4000],
                context=f"Web search results for: {query}",
                max_entities=10,
            )

            if extraction.entities:
                from core.knowledge.graph import KnowledgeGraph
                graph = KnowledgeGraph(self.empire_id)
                for entity in extraction.entities:
                    graph.add_entity(
                        name=entity.get("name", ""),
                        entity_type=entity.get("entity_type", "concept"),
                        description=entity.get("description", ""),
                        confidence=entity.get("confidence", 0.6),
                        tags=["web_search"],
                    )
                    stored_entities += 1

        except Exception as e:
            logger.warning("Failed to store search results: %s", e)

        search_data["stored_entities"] = stored_entities
        search_data["stored_memories"] = stored_memories

        return search_data

    def format_for_prompt(self, response: WebSearchResponse, max_chars: int = 3000) -> str:
        """Format search results for injection into an LLM prompt.

        Args:
            response: Web search response.
            max_chars: Maximum characters.

        Returns:
            Formatted string for prompt.
        """
        if not response.results:
            return f"No web results found for: {response.query}"

        parts = [f"## Web Search Results for: {response.query}\n"]
        char_count = len(parts[0])

        for i, r in enumerate(response.results, 1):
            entry = f"**[{i}] {r.title}**\n{r.snippet}\n_Source: {r.source}_\n"
            if char_count + len(entry) > max_chars:
                break
            parts.append(entry)
            char_count += len(entry)

        return "\n".join(parts)

    def research_topic(
        self,
        topic: str,
        depth: str = "standard",
        max_results: int = 8,
    ) -> dict:
        """Research a topic end-to-end: refine queries, search, store, and synthesize.

        This is the main entry point used by the God Panel RESEARCH action.

        Args:
            topic: Research topic.
            depth: "shallow" (search only), "standard" (search+store),
                   "deep" (search+store+synthesize).
            max_results: Maximum search results.

        Returns:
            Dict with success, sources, synthesis, cost, etc.
        """
        # Step 1: LLM-refined search + store to KG/memory
        search_data = self.search_and_store(topic, max_results=max_results)

        result = {
            "success": search_data.get("found", False),
            "source_count": search_data.get("result_count", 0),
            "queries_used": search_data.get("queries_used", [topic]),
            "stored_entities": search_data.get("stored_entities", 0),
            "stored_memories": search_data.get("stored_memories", 0),
            "cost_usd": 0.0,
        }

        if depth == "shallow" or not search_data.get("found"):
            return result

        # Step 2: Synthesize findings with LLM (for standard and deep)
        try:
            from llm.router import ModelRouter, TaskMetadata
            from llm.base import LLMRequest, LLMMessage

            router = ModelRouter(self.empire_id)
            tier = "synthesis" if depth == "deep" else "analysis"

            prompt = (
                f"You are an AI research analyst. Based on these search results "
                f"about '{topic}', write a concise research brief covering:\n"
                f"1. Key findings\n2. Major players\n3. Technical details\n"
                f"4. Trends and implications\n\n"
                f"Search results:\n{search_data.get('summary', '')[:6000]}"
            )

            response = router.execute(
                LLMRequest(
                    messages=[LLMMessage.user(prompt)],
                    max_tokens=1000,
                    temperature=0.3,
                ),
                TaskMetadata(task_type=tier, complexity="moderate"),
            )

            result["synthesis"] = response.content
            result["cost_usd"] = response.cost_usd

        except Exception as e:
            logger.warning("Research synthesis failed for '%s': %s", topic, e)

        return result

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc.replace("www.", "")
        except Exception:
            return url[:50]
