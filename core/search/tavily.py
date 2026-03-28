"""Tavily search — AI-optimized web search for lieutenants.

Tavily returns clean, extracted content (not just links) making it
ideal for AI agents. Replaces DuckDuckGo as the primary search when
a Tavily API key is configured.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

TAVILY_API_URL = "https://api.tavily.com"


@dataclass
class TavilyResult:
    """A single Tavily search result."""
    title: str = ""
    url: str = ""
    content: str = ""
    raw_content: str = ""
    score: float = 0.0
    published_date: str = ""


@dataclass
class TavilyResponse:
    """Full response from a Tavily search."""
    query: str = ""
    results: list[TavilyResult] = field(default_factory=list)
    answer: str = ""
    follow_up_questions: list[str] = field(default_factory=list)
    search_time_ms: float = 0.0


class TavilySearcher:
    """Tavily-powered search for Empire lieutenants.

    Features:
      - AI-extracted content (not just snippets)
      - Optional AI-generated answer
      - Topic-based search depth (basic vs advanced)
      - Domain include/exclude filtering
    """

    def __init__(self, empire_id: str = "", api_key: str = ""):
        self._empire_id = empire_id
        self._api_key = api_key
        if not self._api_key:
            try:
                from config.settings import get_settings
                self._api_key = get_settings().tavily_api_key
            except Exception:
                pass

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        topic: str = "general",
        include_answer: bool = True,
        include_raw_content: bool = False,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> TavilyResponse:
        """Run a Tavily search.

        Args:
            query: Search query.
            max_results: Max results (1-20).
            search_depth: "basic" (fast) or "advanced" (deeper extraction).
            topic: "general" or "news".
            include_answer: Include AI-generated answer summary.
            include_raw_content: Include full page content (costs more tokens).
            include_domains: Only search these domains.
            exclude_domains: Exclude these domains.

        Returns:
            TavilyResponse with results and optional answer.
        """
        if not self._api_key:
            logger.warning("Tavily API key not set")
            return TavilyResponse(query=query)

        start = time.time()

        payload: dict[str, Any] = {
            "api_key": self._api_key,
            "query": query,
            "max_results": min(max_results, 20),
            "search_depth": search_depth,
            "topic": topic,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{TAVILY_API_URL}/search",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read().decode("utf-8"))

            results = []
            for r in data.get("results", []):
                results.append(TavilyResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=r.get("content", ""),
                    raw_content=r.get("raw_content", ""),
                    score=r.get("score", 0.0),
                    published_date=r.get("published_date", ""),
                ))

            elapsed = (time.time() - start) * 1000

            return TavilyResponse(
                query=query,
                results=results,
                answer=data.get("answer", ""),
                follow_up_questions=data.get("follow_up_questions", []),
                search_time_ms=elapsed,
            )
        except urllib.error.HTTPError as e:
            logger.error("Tavily API error %d: %s", e.code, e.read().decode()[:200])
            return TavilyResponse(query=query)
        except Exception as e:
            logger.error("Tavily search failed: %s", e)
            return TavilyResponse(query=query)

    def search_news(
        self,
        query: str,
        max_results: int = 5,
        days: int = 7,
    ) -> TavilyResponse:
        """Search for recent news."""
        return self.search(
            query=query,
            max_results=max_results,
            topic="news",
            search_depth="basic",
        )

    def search_ai(
        self,
        query: str,
        max_results: int = 5,
    ) -> TavilyResponse:
        """Search AI-specific sources with deep extraction."""
        return self.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            include_domains=[
                "arxiv.org",
                "huggingface.co",
                "github.com",
                "openai.com",
                "anthropic.com",
                "deepmind.google",
                "ai.meta.com",
                "blog.google",
                "techcrunch.com",
                "theverge.com",
            ],
        )

    def search_and_format(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
    ) -> dict:
        """Search and return formatted results for tool use."""
        response = self.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer=True,
        )

        if not response.results:
            return {"found": False, "summary": f"No results for: {query}"}

        parts = []
        if response.answer:
            parts.append(f"**AI Summary:** {response.answer}\n")

        for r in response.results:
            content_preview = r.content[:300] if r.content else ""
            parts.append(f"**{r.title}**\n{content_preview}\n_Source: {r.url}_")

        return {
            "found": True,
            "summary": "\n\n".join(parts),
            "result_count": len(response.results),
            "answer": response.answer,
            "search_time_ms": response.search_time_ms,
        }
