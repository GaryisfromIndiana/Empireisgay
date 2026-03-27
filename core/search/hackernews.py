"""Hacker News search — gives lieutenants access to HN stories, discussions, and trends."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

_HN_API = "https://hacker-news.firebaseio.com/v0"
_HN_SEARCH = "https://hn.algolia.com/api/v1"
_USER_AGENT = "Empire-AI-Research/1.0"


class HackerNewsSearcher:
    """Search Hacker News stories and comments.

    Uses the Algolia-powered HN Search API (no auth required, generous limits).
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
            logger.warning("HN API request failed: %s", e)
            return {}

    def search(
        self,
        query: str,
        max_results: int = 5,
        sort: str = "relevance",
        time_filter: str = "year",
    ) -> dict:
        """Search Hacker News stories.

        Args:
            query: Search query.
            max_results: Maximum results (capped at 10).
            sort: 'relevance' or 'date' (most recent first).
            time_filter: 'day', 'week', 'month', 'year', 'all'.

        Returns:
            Dict with found, summary, result_count, stored_entities.
        """
        max_results = min(max_results, 10)

        # Map time filter to seconds
        time_map = {
            "day": 86400,
            "week": 604800,
            "month": 2592000,
            "year": 31536000,
            "all": 0,
        }
        created_after = 0
        if time_filter in time_map and time_map[time_filter] > 0:
            created_after = int(time.time()) - time_map[time_filter]

        # Use search_by_relevance or search_by_date
        endpoint = "search" if sort == "relevance" else "search_by_date"
        params = {
            "query": query,
            "tags": "story",
            "hitsPerPage": max_results,
        }
        if created_after:
            params["numericFilters"] = f"created_at_i>{created_after}"

        url = f"{_HN_SEARCH}/{endpoint}?{urllib.parse.urlencode(params)}"

        start = time.time()
        data = self._api_get(url)
        elapsed = (time.time() - start) * 1000

        hits = data.get("hits", [])
        if not hits:
            return {"found": False, "query": query, "summary": "No Hacker News stories found."}

        output_parts = []
        items = []
        for hit in hits:
            title = hit.get("title", "")
            points = hit.get("points", 0) or 0
            num_comments = hit.get("num_comments", 0) or 0
            url_link = hit.get("url", "")
            object_id = hit.get("objectID", "")
            author = hit.get("author", "")
            created = hit.get("created_at", "")[:10]

            hn_url = f"https://news.ycombinator.com/item?id={object_id}"

            part = (
                f"**{title}** ({points:,} pts, {num_comments:,} comments)\n"
                f"  By: {author} | {created}"
            )
            if url_link:
                part += f"\n  Link: {url_link}"
            part += f"\n  Discussion: {hn_url}"

            output_parts.append(part)
            items.append({
                "title": title,
                "points": points,
                "num_comments": num_comments,
                "url": url_link,
                "hn_url": hn_url,
                "object_id": object_id,
                "author": author,
            })

        summary = "\n\n".join(output_parts)
        logger.info("HN search: '%s' -> %d results (%.0fms)", query, len(items), elapsed)

        stored = self._store_results(query, summary, items)

        return {
            "found": True,
            "query": query,
            "result_count": len(items),
            "summary": summary,
            "stored_entities": stored,
            "search_time_ms": elapsed,
        }

    def get_story_comments(self, story_id: str, max_comments: int = 10) -> str:
        """Fetch top comments from an HN story.

        Args:
            story_id: HN story/item ID.
            max_comments: Maximum comments to fetch.

        Returns:
            Formatted string of top comments.
        """
        url = f"{_HN_SEARCH}/search?tags=comment,story_{story_id}&hitsPerPage={max_comments}"
        data = self._api_get(url)

        hits = data.get("hits", [])
        if not hits:
            return "No comments found."

        parts = []
        for hit in hits:
            author = hit.get("author", "anon")
            text = (hit.get("comment_text") or "")[:500]
            # Strip HTML tags
            import re
            text = re.sub(r"<[^>]+>", " ", text).strip()
            points = hit.get("points") or 0
            parts.append(f"**{author}** ({points:+,} pts): {text}")

        return "\n\n---\n\n".join(parts)

    def get_front_page(self, max_results: int = 10) -> dict:
        """Get current HN front page stories.

        Args:
            max_results: Maximum stories.

        Returns:
            Dict with found, summary, result_count.
        """
        max_results = min(max_results, 15)
        url = f"{_HN_SEARCH}/search?tags=front_page&hitsPerPage={max_results}"

        data = self._api_get(url)
        hits = data.get("hits", [])

        if not hits:
            return {"found": False, "query": "front_page", "summary": "Could not fetch front page."}

        output_parts = []
        for hit in hits:
            title = hit.get("title", "")
            points = hit.get("points", 0) or 0
            num_comments = hit.get("num_comments", 0) or 0
            object_id = hit.get("objectID", "")
            output_parts.append(
                f"**{title}** ({points:,} pts, {num_comments:,} comments)\n"
                f"  https://news.ycombinator.com/item?id={object_id}"
            )

        return {
            "found": True,
            "query": "front_page",
            "result_count": len(hits),
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
                content=f"Hacker News search: {query}\n\n{summary[:3000]}",
                memory_type="semantic",
                title=f"HN: {query[:80]}",
                category="hackernews_research",
                importance=0.6,
                tags=["hackernews", "research", "discussion"],
                source_type="hackernews_search",
                metadata={"query": query, "result_count": len(items)},
            )

            from core.knowledge.graph import KnowledgeGraph
            graph = KnowledgeGraph(self.empire_id)
            for item in items[:3]:
                if item.get("points", 0) >= 50:
                    title = item.get("title", "")[:200]
                    pts = item.get("points", 0)
                    comments = item.get("num_comments", 0)
                    graph.add_entity(
                        name=title,
                        entity_type="discussion",
                        description=f"Hacker News post ({pts:,} points, {comments:,} comments). {item.get('url', '')}",
                        confidence=min(0.9, 0.5 + (pts / 1000)),
                        tags=["hackernews"],
                    )
                    stored += 1

        except Exception as e:
            logger.warning("Failed to store HN results: %s", e)

        return stored
