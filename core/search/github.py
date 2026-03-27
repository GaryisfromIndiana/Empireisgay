"""GitHub search — gives lieutenants access to GitHub repos, code, and topics."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_USER_AGENT = "Empire-AI-Research/1.0"


class GitHubSearcher:
    """Search GitHub repositories, code, and topics.

    Uses the public GitHub Search API (no token required for basic use,
    rate-limited to 10 requests/minute unauthenticated).
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id

    def _api_get(self, url: str) -> dict:
        """Make a GET request to the GitHub API."""
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": _USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("GitHub API request failed: %s", e)
            return {}

    def search(
        self,
        query: str,
        search_type: str = "repositories",
        max_results: int = 5,
        sort: str = "best-match",
    ) -> dict:
        """Search GitHub and store results.

        Args:
            query: Search query.
            search_type: 'repositories', 'code', or 'topics'.
            max_results: Maximum results (capped at 10).
            sort: Sort order.

        Returns:
            Dict with found, summary, result_count, stored_entities.
        """
        max_results = min(max_results, 10)

        if search_type == "topics":
            return self._search_topics(query, max_results)
        elif search_type == "code":
            return self._search_code(query, max_results)
        else:
            return self._search_repos(query, max_results, sort)

    def _search_repos(self, query: str, max_results: int, sort: str) -> dict:
        """Search GitHub repositories."""
        params = urllib.parse.urlencode({
            "q": query,
            "sort": sort if sort != "best-match" else "",
            "order": "desc",
            "per_page": max_results,
        })
        url = f"{_GITHUB_API}/search/repositories?{params}"

        start = time.time()
        data = self._api_get(url)
        elapsed = (time.time() - start) * 1000

        items = data.get("items", [])
        if not items:
            return {"found": False, "query": query, "summary": "No repositories found."}

        output_parts = []
        for repo in items:
            stars = repo.get("stargazers_count", 0)
            forks = repo.get("forks_count", 0)
            lang = repo.get("language", "Unknown")
            updated = repo.get("updated_at", "")[:10]
            desc = (repo.get("description") or "No description")[:200]
            topics = ", ".join(repo.get("topics", [])[:5])

            part = (
                f"**{repo['full_name']}** ({stars:,} stars, {forks:,} forks)\n"
                f"  Language: {lang} | Updated: {updated}\n"
                f"  {desc}"
            )
            if topics:
                part += f"\n  Topics: {topics}"
            part += f"\n  URL: {repo['html_url']}"
            output_parts.append(part)

        summary = "\n\n".join(output_parts)

        logger.info("GitHub repo search: '%s' -> %d results (%.0fms)", query, len(items), elapsed)

        stored = self._store_results(query, summary, items, "repository")

        return {
            "found": True,
            "query": query,
            "result_count": len(items),
            "summary": summary,
            "stored_entities": stored,
            "search_time_ms": elapsed,
        }

    def _search_code(self, query: str, max_results: int) -> dict:
        """Search GitHub code."""
        params = urllib.parse.urlencode({
            "q": query,
            "per_page": max_results,
        })
        url = f"{_GITHUB_API}/search/code?{params}"

        data = self._api_get(url)
        items = data.get("items", [])

        if not items:
            return {"found": False, "query": query, "summary": "No code results found."}

        output_parts = []
        for item in items:
            repo_name = item.get("repository", {}).get("full_name", "unknown")
            path = item.get("path", "")
            url = item.get("html_url", "")
            output_parts.append(f"**{repo_name}** — `{path}`\n  URL: {url}")

        summary = "\n\n".join(output_parts)

        return {
            "found": True,
            "query": query,
            "result_count": len(items),
            "summary": summary,
            "stored_entities": 0,
        }

    def _search_topics(self, query: str, max_results: int) -> dict:
        """Search GitHub topics."""
        params = urllib.parse.urlencode({
            "q": query,
            "per_page": max_results,
        })
        url = f"{_GITHUB_API}/search/topics?{params}"

        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github.mercy-preview+json",
                "User-Agent": _USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("GitHub topics search failed: %s", e)
            return {"found": False, "query": query, "summary": f"Topic search failed: {e}"}

        items = data.get("items", [])
        if not items:
            return {"found": False, "query": query, "summary": "No topics found."}

        output_parts = []
        for topic in items:
            name = topic.get("name", "")
            desc = (topic.get("short_description") or topic.get("description") or "")[:200]
            repos = topic.get("featured_repos", [])
            output_parts.append(f"**{name}**: {desc}")

        return {
            "found": True,
            "query": query,
            "result_count": len(items),
            "summary": "\n\n".join(output_parts),
            "stored_entities": 0,
        }

    def search_trending(self, language: str = "", since: str = "weekly") -> dict:
        """Get trending repositories (via web search fallback since no official API)."""
        query = f"trending {language} repositories github {since}".strip()
        from core.search.web import WebSearcher
        ws = WebSearcher(self.empire_id)
        return ws.search_and_store(query, max_results=5)

    def get_repo_readme(self, owner: str, repo: str) -> str:
        """Fetch a repo's README content."""
        url = f"{_GITHUB_API}/repos/{owner}/{repo}/readme"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github.v3.raw",
                "User-Agent": _USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8")
                return content[:8000]
        except Exception as e:
            logger.warning("Failed to fetch README for %s/%s: %s", owner, repo, e)
            return ""

    def _store_results(self, query: str, summary: str, items: list, item_type: str) -> int:
        """Store search results in memory and knowledge graph."""
        stored = 0
        try:
            from core.memory.manager import MemoryManager
            mm = MemoryManager(self.empire_id)
            mm.store(
                content=f"GitHub search: {query}\n\n{summary[:3000]}",
                memory_type="semantic",
                title=f"GitHub: {query[:80]}",
                category="github_research",
                importance=0.65,
                tags=["github", "research", item_type],
                source_type="github_search",
                metadata={"query": query, "result_count": len(items)},
            )

            from core.knowledge.graph import KnowledgeGraph
            graph = KnowledgeGraph(self.empire_id)
            for item in items[:5]:
                name = item.get("full_name", item.get("name", ""))
                desc = (item.get("description") or "")[:300]
                if name and desc:
                    graph.add_entity(
                        name=name,
                        entity_type=item_type,
                        description=desc,
                        confidence=0.8,
                        tags=["github", item_type],
                    )
                    stored += 1

        except Exception as e:
            logger.warning("Failed to store GitHub results: %s", e)

        return stored
