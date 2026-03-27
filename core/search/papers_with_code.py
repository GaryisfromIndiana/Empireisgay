"""Papers With Code search — gives lieutenants access to papers, implementations, and trending research."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

_USER_AGENT = "Empire-AI-Research/1.0"


class PapersWithCodeSearcher:
    """Search for papers with code implementations.

    Uses HuggingFace Daily Papers API for trending papers and
    Semantic Scholar for paper search with implementation links.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id

    def _api_get(self, url: str) -> Any:
        """Make a GET request."""
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("API request failed: %s", e)
            return None

    def search(
        self,
        query: str,
        max_results: int = 5,
        search_type: str = "papers",
    ) -> dict:
        """Search for papers with implementations.

        Args:
            query: Search query.
            max_results: Maximum results (capped at 10).
            search_type: 'papers', 'trending', or 'methods'.

        Returns:
            Dict with found, summary, result_count, stored_entities.
        """
        max_results = min(max_results, 10)

        if search_type == "trending":
            return self._get_trending(max_results)
        elif search_type == "methods":
            return self._search_methods(query, max_results)
        else:
            return self._search_papers(query, max_results)

    def _search_papers(self, query: str, max_results: int) -> dict:
        """Search papers via Semantic Scholar and check for code repos."""
        # Use Semantic Scholar for paper search with external IDs
        fields = "paperId,title,abstract,year,citationCount,authors,url,openAccessPdf,externalIds"
        params = urllib.parse.urlencode({
            "query": query,
            "limit": max_results,
            "fields": fields,
        })
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}"

        start = time.time()
        data = self._api_get(url)
        elapsed = (time.time() - start) * 1000

        if not data:
            return {"found": False, "query": query, "summary": "Paper search failed (rate limited or unavailable)."}

        papers = data.get("data", [])
        if not papers:
            return {"found": False, "query": query, "summary": "No papers found."}

        output_parts = []
        items = []
        for paper in papers:
            title = paper.get("title", "Untitled")
            year = paper.get("year", "")
            citations = paper.get("citationCount", 0) or 0
            abstract = (paper.get("abstract") or "")[:250]
            authors = paper.get("authors", [])
            author_str = ", ".join(a.get("name", "") for a in authors[:3])
            if len(authors) > 3:
                author_str += f" +{len(authors) - 3}"

            # Get arxiv ID for linking
            ext_ids = paper.get("externalIds", {}) or {}
            arxiv_id = ext_ids.get("ArXiv", "")
            pdf = paper.get("openAccessPdf", {})
            pdf_url = pdf.get("url", "") if pdf else ""

            part = (
                f"**{title}** ({year}) — {citations:,} citations\n"
                f"  Authors: {author_str}"
            )
            if abstract:
                part += f"\n  {abstract}"
            if arxiv_id:
                part += f"\n  arXiv: https://arxiv.org/abs/{arxiv_id}"
                part += f"\n  PWC: https://paperswithcode.com/paper/?arxiv_id={arxiv_id}"
            if pdf_url:
                part += f"\n  PDF: {pdf_url}"

            output_parts.append(part)
            items.append({
                "title": title,
                "year": year,
                "citations": citations,
                "authors": author_str,
                "abstract": abstract,
                "arxiv_id": arxiv_id,
                "pdf_url": pdf_url,
            })

        summary = "\n\n".join(output_parts)
        logger.info("PWC paper search: '%s' -> %d results (%.0fms)", query, len(items), elapsed)

        stored = self._store_results(query, summary, items)

        return {
            "found": True,
            "query": query,
            "result_count": len(items),
            "summary": summary,
            "stored_entities": stored,
            "search_time_ms": elapsed,
        }

    def _get_trending(self, max_results: int) -> dict:
        """Get trending papers from HuggingFace Daily Papers."""
        url = f"https://huggingface.co/api/daily_papers?limit={max_results}"

        start = time.time()
        data = self._api_get(url)
        elapsed = (time.time() - start) * 1000

        if not isinstance(data, list) or not data:
            return {"found": False, "query": "trending", "summary": "Could not fetch trending papers."}

        output_parts = []
        items = []
        for entry in data[:max_results]:
            paper = entry.get("paper", {})
            paper_id = paper.get("id", "")
            title = paper.get("title", "Untitled")
            summary_text = (paper.get("summary") or "")[:250]
            authors = paper.get("authors", [])
            author_str = ", ".join(a.get("name", "") for a in authors[:3])
            if len(authors) > 3:
                author_str += f" +{len(authors) - 3}"
            upvotes = entry.get("paper", {}).get("upvotes", 0)
            num_comments = entry.get("numComments", 0)
            published = entry.get("publishedAt", "")[:10]

            part = (
                f"**{title}** (trending, {upvotes} upvotes, {num_comments} comments)\n"
                f"  Authors: {author_str}\n"
                f"  Published: {published}"
            )
            if summary_text:
                part += f"\n  {summary_text}"
            if paper_id:
                part += f"\n  arXiv: https://arxiv.org/abs/{paper_id}"
                part += f"\n  HF: https://huggingface.co/papers/{paper_id}"

            output_parts.append(part)
            items.append({
                "title": title,
                "arxiv_id": paper_id,
                "authors": author_str,
                "abstract": summary_text,
                "upvotes": upvotes,
                "published": published,
            })

        summary = "\n\n".join(output_parts)
        logger.info("Trending papers: %d results (%.0fms)", len(items), elapsed)

        stored = self._store_results("trending AI papers", summary, items)

        return {
            "found": True,
            "query": "trending",
            "result_count": len(items),
            "summary": summary,
            "stored_entities": stored,
            "search_time_ms": elapsed,
        }

    def _search_methods(self, query: str, max_results: int) -> dict:
        """Search for ML methods via web search fallback."""
        from core.search.web import WebSearcher
        ws = WebSearcher(self.empire_id)
        q = f"site:paperswithcode.com/method {query}"
        response = ws.search(q, max_results=max_results)

        if not response.results:
            return {"found": False, "query": query, "summary": "No methods found."}

        output_parts = []
        for r in response.results:
            output_parts.append(f"**{r.title}**\n  {r.snippet}\n  URL: {r.url}")

        return {
            "found": True,
            "query": query,
            "result_count": len(response.results),
            "summary": "\n\n".join(output_parts),
            "stored_entities": 0,
        }

    def _store_results(self, query: str, summary: str, items: list) -> int:
        """Store search results in memory and knowledge graph."""
        stored = 0
        try:
            from core.memory.manager import MemoryManager
            mm = MemoryManager(self.empire_id)
            mm.store(
                content=f"Papers With Code search: {query}\n\n{summary[:3000]}",
                memory_type="semantic",
                title=f"PWC: {query[:80]}",
                category="academic_research",
                importance=0.7,
                tags=["papers_with_code", "research", "implementations"],
                source_type="papers_with_code",
                metadata={"query": query, "result_count": len(items)},
            )

            from core.knowledge.graph import KnowledgeGraph
            graph = KnowledgeGraph(self.empire_id)
            for item in items[:5]:
                title = item.get("title", "")[:200]
                year = item.get("year", "")
                citations = item.get("citations", 0)
                abstract = item.get("abstract", "")[:200]
                if title:
                    desc = f"Paper ({year})."
                    if citations:
                        desc += f" {citations:,} citations."
                    if abstract:
                        desc += f" {abstract}"
                    graph.add_entity(
                        name=title,
                        entity_type="paper",
                        description=desc,
                        confidence=0.8,
                        tags=["paper", "papers_with_code"],
                    )
                    stored += 1

        except Exception as e:
            logger.warning("Failed to store PWC results: %s", e)

        return stored
