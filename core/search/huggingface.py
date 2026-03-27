"""HuggingFace search — gives lieutenants access to models, datasets, and spaces."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

_HF_API = "https://huggingface.co/api"
_USER_AGENT = "Empire-AI-Research/1.0"


class HuggingFaceSearcher:
    """Search HuggingFace for models, datasets, and spaces.

    Uses the public HuggingFace API (no token required, generous rate limits).
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id

    def _api_get(self, url: str) -> Any:
        """Make a GET request to the HuggingFace API."""
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("HuggingFace API request failed: %s", e)
            return []

    def search(
        self,
        query: str,
        search_type: str = "models",
        max_results: int = 5,
        sort: str = "downloads",
    ) -> dict:
        """Search HuggingFace and store results.

        Args:
            query: Search query.
            search_type: 'models', 'datasets', or 'spaces'.
            max_results: Maximum results (capped at 10).
            sort: Sort order.

        Returns:
            Dict with found, summary, result_count, stored_entities.
        """
        max_results = min(max_results, 10)

        if search_type == "datasets":
            return self._search_datasets(query, max_results, sort)
        elif search_type == "spaces":
            return self._search_spaces(query, max_results, sort)
        else:
            return self._search_models(query, max_results, sort)

    def _search_models(self, query: str, max_results: int, sort: str) -> dict:
        """Search HuggingFace models."""
        sort_key = self._resolve_sort(sort)
        params = urllib.parse.urlencode({
            "search": query,
            "limit": max_results,
            "sort": sort_key,
            "direction": "-1",
        })
        url = f"{_HF_API}/models?{params}"

        start = time.time()
        items = self._api_get(url)
        elapsed = (time.time() - start) * 1000

        if not isinstance(items, list) or not items:
            return {"found": False, "query": query, "summary": "No models found."}

        output_parts = []
        for model in items:
            model_id = model.get("modelId", model.get("id", "unknown"))
            downloads = model.get("downloads", 0)
            likes = model.get("likes", 0)
            pipeline_tag = model.get("pipeline_tag", "")
            tags = model.get("tags", [])
            library = next((t for t in tags if t in ("transformers", "pytorch", "tensorflow", "jax", "gguf", "diffusers")), "")
            last_modified = model.get("lastModified", "")[:10]

            part = (
                f"**{model_id}** ({downloads:,} downloads, {likes:,} likes)\n"
                f"  Task: {pipeline_tag or 'N/A'} | Library: {library or 'N/A'} | Updated: {last_modified}"
            )
            # Show key tags (skip generic ones)
            interesting_tags = [t for t in tags[:8] if t not in ("transformers", "pytorch", "tensorflow", "jax", pipeline_tag)]
            if interesting_tags:
                part += f"\n  Tags: {', '.join(interesting_tags[:5])}"
            part += f"\n  URL: https://huggingface.co/{model_id}"
            output_parts.append(part)

        summary = "\n\n".join(output_parts)
        logger.info("HF model search: '%s' -> %d results (%.0fms)", query, len(items), elapsed)

        stored = self._store_results(query, summary, items, "model")

        return {
            "found": True,
            "query": query,
            "result_count": len(items),
            "summary": summary,
            "stored_entities": stored,
            "search_time_ms": elapsed,
        }

    def _search_datasets(self, query: str, max_results: int, sort: str) -> dict:
        """Search HuggingFace datasets."""
        sort_key = self._resolve_sort(sort)
        params = urllib.parse.urlencode({
            "search": query,
            "limit": max_results,
            "sort": sort_key,
            "direction": "-1",
        })
        url = f"{_HF_API}/datasets?{params}"

        start = time.time()
        items = self._api_get(url)
        elapsed = (time.time() - start) * 1000

        if not isinstance(items, list) or not items:
            return {"found": False, "query": query, "summary": "No datasets found."}

        output_parts = []
        for ds in items:
            ds_id = ds.get("id", "unknown")
            downloads = ds.get("downloads", 0)
            likes = ds.get("likes", 0)
            tags = ds.get("tags", [])
            last_modified = ds.get("lastModified", "")[:10]

            part = (
                f"**{ds_id}** ({downloads:,} downloads, {likes:,} likes)\n"
                f"  Updated: {last_modified}"
            )
            interesting_tags = [t for t in tags[:8] if not t.startswith("region:") and not t.startswith("license:")]
            if interesting_tags:
                part += f"\n  Tags: {', '.join(interesting_tags[:5])}"
            part += f"\n  URL: https://huggingface.co/datasets/{ds_id}"
            output_parts.append(part)

        summary = "\n\n".join(output_parts)
        logger.info("HF dataset search: '%s' -> %d results (%.0fms)", query, len(items), elapsed)

        stored = self._store_results(query, summary, items, "dataset")

        return {
            "found": True,
            "query": query,
            "result_count": len(items),
            "summary": summary,
            "stored_entities": stored,
            "search_time_ms": elapsed,
        }

    def _search_spaces(self, query: str, max_results: int, sort: str) -> dict:
        """Search HuggingFace spaces."""
        sort_key = self._resolve_sort(sort)
        params = urllib.parse.urlencode({
            "search": query,
            "limit": max_results,
            "sort": sort_key,
            "direction": "-1",
        })
        url = f"{_HF_API}/spaces?{params}"

        start = time.time()
        items = self._api_get(url)
        elapsed = (time.time() - start) * 1000

        if not isinstance(items, list) or not items:
            return {"found": False, "query": query, "summary": "No spaces found."}

        output_parts = []
        for space in items:
            space_id = space.get("id", "unknown")
            likes = space.get("likes", 0)
            sdk = space.get("sdk", "unknown")
            last_modified = space.get("lastModified", "")[:10]

            part = (
                f"**{space_id}** ({likes:,} likes)\n"
                f"  SDK: {sdk} | Updated: {last_modified}\n"
                f"  URL: https://huggingface.co/spaces/{space_id}"
            )
            output_parts.append(part)

        summary = "\n\n".join(output_parts)
        logger.info("HF space search: '%s' -> %d results (%.0fms)", query, len(items), elapsed)

        return {
            "found": True,
            "query": query,
            "result_count": len(items),
            "summary": summary,
            "stored_entities": 0,
        }

    def get_model_card(self, model_id: str) -> str:
        """Fetch a model's README/card content."""
        url = f"https://huggingface.co/{model_id}/raw/main/README.md"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8")[:8000]
        except Exception as e:
            logger.warning("Failed to fetch model card for %s: %s", model_id, e)
            return ""

    def _resolve_sort(self, sort: str) -> str:
        """Map user-friendly sort names to API sort keys."""
        mapping = {
            "downloads": "downloads",
            "likes": "likes",
            "trending": "trending",
            "recent": "lastModified",
        }
        return mapping.get(sort, "downloads")

    def _store_results(self, query: str, summary: str, items: list, item_type: str) -> int:
        """Store search results in memory and knowledge graph."""
        stored = 0
        try:
            from core.memory.manager import MemoryManager
            mm = MemoryManager(self.empire_id)
            mm.store(
                content=f"HuggingFace search: {query}\n\n{summary[:3000]}",
                memory_type="semantic",
                title=f"HuggingFace: {query[:80]}",
                category="huggingface_research",
                importance=0.65,
                tags=["huggingface", "research", item_type],
                source_type="huggingface_search",
                metadata={"query": query, "result_count": len(items)},
            )

            from core.knowledge.graph import KnowledgeGraph
            graph = KnowledgeGraph(self.empire_id)
            for item in items[:5]:
                name = item.get("modelId", item.get("id", ""))
                if not name:
                    continue

                if item_type == "model":
                    pipeline = item.get("pipeline_tag", "")
                    downloads = item.get("downloads", 0)
                    desc = f"HuggingFace model. Task: {pipeline}. Downloads: {downloads:,}."
                elif item_type == "dataset":
                    downloads = item.get("downloads", 0)
                    desc = f"HuggingFace dataset. Downloads: {downloads:,}."
                else:
                    desc = f"HuggingFace {item_type}."

                graph.add_entity(
                    name=name,
                    entity_type=item_type,
                    description=desc,
                    confidence=0.8,
                    tags=["huggingface", item_type],
                )
                stored += 1

        except Exception as e:
            logger.warning("Failed to store HuggingFace results: %s", e)

        return stored
