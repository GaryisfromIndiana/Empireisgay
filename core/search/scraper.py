"""Web scraper — fetches and extracts content from URLs."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import trafilatura

logger = logging.getLogger(__name__)


@dataclass
class ScrapedPage:
    """Content extracted from a web page."""
    url: str = ""
    title: str = ""
    content: str = ""
    author: str = ""
    date: str = ""
    domain: str = ""
    word_count: int = 0
    success: bool = False
    error: str = ""
    fetch_time_ms: float = 0.0


@dataclass
class ScrapedBatch:
    """Results from scraping multiple URLs."""
    pages: list[ScrapedPage] = field(default_factory=list)
    total_urls: int = 0
    successful: int = 0
    failed: int = 0
    total_words: int = 0


class WebScraper:
    """Fetches and extracts readable content from web pages.

    Uses trafilatura for high-quality content extraction —
    strips navigation, ads, and boilerplate, keeping the article text.
    """

    def __init__(self, empire_id: str = "", use_cache: bool = True):
        self.empire_id = empire_id
        self._max_content_length = 15000  # chars
        self._use_cache = use_cache
        self._cache = None

    def _get_cache(self):
        if self._cache is None:
            from core.search.cache import ScrapeCache
            self._cache = ScrapeCache(self.empire_id)
        return self._cache

    def scrape_url(self, url: str) -> ScrapedPage:
        """Fetch and extract content from a URL. Uses cache if available.

        Args:
            url: URL to scrape.

        Returns:
            ScrapedPage with extracted content.
        """
        start = time.time()
        page = ScrapedPage(url=url, domain=self._extract_domain(url))

        # Check cache first
        if self._use_cache:
            try:
                cached = self._get_cache().get(url)
                if cached:
                    page.title = cached.title
                    page.content = cached.content
                    page.domain = cached.domain
                    page.word_count = cached.word_count
                    page.success = True
                    page.fetch_time_ms = (time.time() - start) * 1000
                    logger.debug("Cache hit: %s", page.domain)
                    return page
            except Exception:
                pass

        try:
            # Download
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                page.error = "Failed to download page"
                page.fetch_time_ms = (time.time() - start) * 1000
                return page

            # Extract content
            result = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=True,
                include_links=False,
                output_format="txt",
                favor_precision=True,
            )

            if not result:
                page.error = "No content extracted"
                page.fetch_time_ms = (time.time() - start) * 1000
                return page

            # Extract metadata
            metadata = trafilatura.extract(
                downloaded,
                output_format="json",
                include_comments=False,
            )

            if metadata:
                import json
                try:
                    meta = json.loads(metadata) if isinstance(metadata, str) else {}
                    page.title = meta.get("title", "")
                    page.author = meta.get("author", "")
                    page.date = meta.get("date", "")
                except (json.JSONDecodeError, TypeError):
                    pass

            page.content = result[:self._max_content_length]
            page.word_count = len(result.split())
            page.success = True
            page.fetch_time_ms = (time.time() - start) * 1000

            logger.info("Scraped %s: %d words (%.0fms)", page.domain, page.word_count, page.fetch_time_ms)

            # Store in cache
            if self._use_cache:
                try:
                    self._get_cache().put(
                        url=url,
                        title=page.title,
                        content=page.content,
                        domain=page.domain,
                        word_count=page.word_count,
                    )
                except Exception:
                    pass

        except Exception as e:
            page.error = str(e)
            page.fetch_time_ms = (time.time() - start) * 1000
            logger.error("Scrape failed for %s: %s", url, e)

        return page

    def scrape_urls(self, urls: list[str]) -> ScrapedBatch:
        """Scrape multiple URLs.

        Args:
            urls: List of URLs.

        Returns:
            ScrapedBatch with all results.
        """
        batch = ScrapedBatch(total_urls=len(urls))

        for url in urls:
            page = self.scrape_url(url)
            batch.pages.append(page)
            if page.success:
                batch.successful += 1
                batch.total_words += page.word_count
            else:
                batch.failed += 1

        return batch

    def search_and_scrape(
        self,
        query: str,
        max_results: int = 3,
    ) -> list[ScrapedPage]:
        """Search the web and scrape the top results.

        Args:
            query: Search query.
            max_results: How many results to scrape.

        Returns:
            List of scraped pages.
        """
        from core.search.web import WebSearcher
        searcher = WebSearcher(self.empire_id)
        search_response = searcher.search(query, max_results=max_results)

        urls = [r.url for r in search_response.results if r.url]
        if not urls:
            # Fall back to news
            news = searcher.search_news(query, max_results=max_results)
            urls = [r.url for r in news.results if r.url]

        scraped = []
        for url in urls[:max_results]:
            page = self.scrape_url(url)
            if page.success:
                scraped.append(page)

        return scraped

    def scrape_and_store(
        self,
        url: str,
    ) -> dict:
        """Scrape a URL and store content in memory + knowledge graph.

        Args:
            url: URL to scrape.

        Returns:
            Dict with scrape results and storage stats.
        """
        page = self.scrape_url(url)

        if not page.success:
            return {"url": url, "success": False, "error": page.error}

        stored_entities = 0
        stored_memories = 0

        try:
            # Store in memory
            from core.memory.manager import MemoryManager
            mm = MemoryManager(self.empire_id)

            # Check if this URL was already stored
            existing = mm.recall(query=page.url, memory_types=["semantic"], limit=1)
            url_already_stored = any(page.url in m.get("content", "") for m in existing)

            if url_already_stored:
                logger.debug("URL already in memory: %s", page.url)
                stored_memories = 0
            else:
                # Store using smart temporal storage — auto-supersedes outdated facts
                from core.memory.bitemporal import BiTemporalMemory
                bt = BiTemporalMemory(self.empire_id)
                bt.store_smart(
                    content=f"Source: {page.url}\nTitle: {page.title}\n\n{page.content[:5000]}",
                    title=f"Web: {page.title[:80]}" if page.title else f"Web: {page.domain}",
                    category="web_scrape",
                    valid_from=page.date or None,
                    importance=0.65,
                    confidence=0.7,
                    source=page.domain,
                    source_url=url,
                    tags=["web_scrape", page.domain],
                )
                stored_memories = 1

            # Extract entities
            from core.knowledge.entities import EntityExtractor
            extractor = EntityExtractor()
            extraction = extractor.extract_from_text(
                page.content[:4000],
                context=f"Article from {page.domain}: {page.title}",
                max_entities=15,
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
                        tags=["web_scrape", page.domain],
                    )
                    stored_entities += 1

                for relation in extraction.relations:
                    graph.add_relation(
                        source_name=relation.get("source", ""),
                        target_name=relation.get("target", ""),
                        relation_type=relation.get("type", "related_to"),
                    )

        except Exception as e:
            logger.warning("Failed to store scraped content: %s", e)

        return {
            "url": url,
            "success": True,
            "title": page.title,
            "domain": page.domain,
            "word_count": page.word_count,
            "content_preview": page.content[:500],
            "stored_entities": stored_entities,
            "stored_memories": stored_memories,
        }

    def format_for_prompt(self, page: ScrapedPage, max_chars: int = 4000) -> str:
        """Format scraped content for LLM prompt injection."""
        if not page.success:
            return f"Failed to scrape {page.url}: {page.error}"

        header = f"## {page.title or page.url}\n_Source: {page.domain}_"
        if page.date:
            header += f" _| {page.date}_"
        header += f"\n\n"

        return header + page.content[:max_chars]

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            return urlparse(url).netloc.replace("www.", "")
        except Exception:
            return ""
