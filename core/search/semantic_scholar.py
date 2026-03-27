"""Semantic Scholar search — gives lieutenants access to academic papers with citation data."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

_S2_API = "https://api.semanticscholar.org/graph/v1"
_USER_AGENT = "Empire-AI-Research/1.0"


class SemanticScholarSearcher:
    """Search Semantic Scholar for academic papers.

    Uses the free Semantic Scholar API (no key required, 100 req/5 min).
    Provides citation counts, influence scores, and paper metadata
    that arXiv search alone cannot.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id

    def _api_get(self, url: str) -> Any:
        """Make a GET request to the Semantic Scholar API."""
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("Semantic Scholar API request failed: %s", e)
            return {}

    def search(
        self,
        query: str,
        max_results: int = 5,
        year_filter: str = "",
        fields_of_study: str = "",
    ) -> dict:
        """Search for academic papers.

        Args:
            query: Search query.
            max_results: Maximum results (capped at 10).
            year_filter: Year range, e.g. '2024-2025' or '2023-'.
            fields_of_study: Comma-separated fields, e.g. 'Computer Science'.

        Returns:
            Dict with found, summary, result_count, stored_entities.
        """
        max_results = min(max_results, 10)

        fields = "paperId,title,abstract,year,citationCount,influentialCitationCount,authors,url,venue,openAccessPdf,publicationDate"

        params = {
            "query": query,
            "limit": max_results,
            "fields": fields,
        }
        if year_filter:
            params["year"] = year_filter
        if fields_of_study:
            params["fieldsOfStudy"] = fields_of_study

        url = f"{_S2_API}/paper/search?{urllib.parse.urlencode(params)}"

        start = time.time()
        data = self._api_get(url)
        elapsed = (time.time() - start) * 1000

        papers = data.get("data", [])
        if not papers:
            return {"found": False, "query": query, "summary": "No papers found."}

        output_parts = []
        items = []
        for paper in papers:
            title = paper.get("title", "Untitled")
            year = paper.get("year", "")
            citations = paper.get("citationCount", 0) or 0
            influential = paper.get("influentialCitationCount", 0) or 0
            venue = paper.get("venue", "")
            authors = paper.get("authors", [])
            author_str = ", ".join(a.get("name", "") for a in authors[:3])
            if len(authors) > 3:
                author_str += f" +{len(authors) - 3} more"
            abstract = (paper.get("abstract") or "")[:300]
            paper_url = paper.get("url", "")
            pdf = paper.get("openAccessPdf", {})
            pdf_url = pdf.get("url", "") if pdf else ""

            part = (
                f"**{title}** ({year})\n"
                f"  Authors: {author_str}\n"
                f"  Citations: {citations:,} ({influential:,} influential)"
            )
            if venue:
                part += f" | Venue: {venue}"
            if abstract:
                part += f"\n  {abstract}"
            if pdf_url:
                part += f"\n  PDF: {pdf_url}"
            elif paper_url:
                part += f"\n  URL: {paper_url}"

            output_parts.append(part)
            items.append({
                "title": title,
                "year": year,
                "citations": citations,
                "influential_citations": influential,
                "authors": author_str,
                "abstract": abstract,
                "url": paper_url,
                "pdf_url": pdf_url,
                "paper_id": paper.get("paperId", ""),
            })

        summary = "\n\n".join(output_parts)
        logger.info("S2 search: '%s' -> %d results (%.0fms)", query, len(items), elapsed)

        stored = self._store_results(query, summary, items)

        return {
            "found": True,
            "query": query,
            "result_count": len(items),
            "summary": summary,
            "stored_entities": stored,
            "search_time_ms": elapsed,
        }

    def get_paper_details(self, paper_id: str) -> dict:
        """Get detailed info about a specific paper including references and citations.

        Args:
            paper_id: Semantic Scholar paper ID, DOI, or arXiv ID (e.g. 'arXiv:2301.12345').

        Returns:
            Dict with paper details.
        """
        fields = "paperId,title,abstract,year,citationCount,influentialCitationCount,authors,url,venue,references,citations,tldr"
        url = f"{_S2_API}/paper/{urllib.parse.quote(paper_id, safe='')}?fields={fields}"

        data = self._api_get(url)
        if not data or not data.get("title"):
            return {"found": False}

        title = data.get("title", "")
        tldr = data.get("tldr", {})
        tldr_text = tldr.get("text", "") if tldr else ""
        abstract = (data.get("abstract") or "")[:500]
        citations = data.get("citationCount", 0) or 0
        refs = data.get("references", [])
        cites = data.get("citations", [])

        parts = [f"**{title}** ({data.get('year', '')})"]
        if tldr_text:
            parts.append(f"TL;DR: {tldr_text}")
        if abstract:
            parts.append(f"Abstract: {abstract}")
        parts.append(f"Citations: {citations:,}")

        if refs:
            parts.append(f"\nKey References ({len(refs)} total):")
            for ref in refs[:5]:
                ref_title = ref.get("title", "")
                if ref_title:
                    parts.append(f"  - {ref_title}")

        if cites:
            parts.append(f"\nCited By ({len(cites)} shown):")
            for cite in cites[:5]:
                cite_title = cite.get("title", "")
                if cite_title:
                    parts.append(f"  - {cite_title}")

        return {
            "found": True,
            "summary": "\n".join(parts),
            "title": title,
            "citations": citations,
            "reference_count": len(refs),
        }

    def get_author_papers(self, author_name: str, max_results: int = 5) -> dict:
        """Search for papers by a specific author.

        Args:
            author_name: Author name to search for.
            max_results: Maximum results.

        Returns:
            Dict with found, summary, result_count.
        """
        return self.search(f"author:{author_name}", max_results=max_results)

    def find_related_papers(self, paper_id: str, max_results: int = 5) -> dict:
        """Find papers related to a given paper.

        Args:
            paper_id: Semantic Scholar paper ID.
            max_results: Maximum results.

        Returns:
            Dict with found, summary, result_count.
        """
        fields = "paperId,title,abstract,year,citationCount,authors,url"
        url = f"{_S2_API}/recommendations/v1/papers/forpaper/{paper_id}?fields={fields}&limit={max_results}"

        data = self._api_get(url)
        papers = data.get("recommendedPapers", [])

        if not papers:
            return {"found": False, "query": paper_id, "summary": "No related papers found."}

        output_parts = []
        for paper in papers[:max_results]:
            title = paper.get("title", "")
            year = paper.get("year", "")
            citations = paper.get("citationCount", 0) or 0
            authors = ", ".join(a.get("name", "") for a in paper.get("authors", [])[:3])
            output_parts.append(f"**{title}** ({year}) — {citations:,} citations\n  {authors}")

        return {
            "found": True,
            "query": paper_id,
            "result_count": len(papers),
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
                content=f"Academic search: {query}\n\n{summary[:3000]}",
                memory_type="semantic",
                title=f"Papers: {query[:80]}",
                category="academic_research",
                importance=0.7,
                tags=["academic", "research", "papers"],
                source_type="semantic_scholar",
                metadata={"query": query, "result_count": len(items)},
            )

            from core.knowledge.graph import KnowledgeGraph
            graph = KnowledgeGraph(self.empire_id)
            for item in items[:5]:
                title = item.get("title", "")[:200]
                citations = item.get("citations", 0)
                year = item.get("year", "")
                authors = item.get("authors", "")
                if title:
                    graph.add_entity(
                        name=title,
                        entity_type="paper",
                        description=f"Academic paper ({year}). {citations:,} citations. Authors: {authors}. {item.get('abstract', '')[:200]}",
                        confidence=min(0.95, 0.6 + (citations / 500)),
                        tags=["paper", "academic"],
                    )
                    stored += 1

        except Exception as e:
            logger.warning("Failed to store S2 results: %s", e)

        return stored
