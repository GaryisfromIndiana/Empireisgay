"""Memory compression — uses LLM to distill clusters of memories into concise knowledge.

50 episodic memories about "model releases" become 1 semantic memory:
"Key model releases in 2025-2026: GPT-4o, Claude 3.5, Llama 3, Gemini 1.5..."

Compression preserves the essential knowledge while freeing space.
Old memories are archived (importance reduced to near-zero) after compression.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CompressionResult:
    """Result of a memory compression cycle."""
    clusters_found: int = 0
    clusters_compressed: int = 0
    memories_consumed: int = 0
    summaries_created: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    compression_ratio: float = 0.0
    cost_usd: float = 0.0


@dataclass
class MemoryCluster:
    """A cluster of related memories that can be compressed."""
    cluster_key: str = ""
    memories: list[dict] = field(default_factory=list)
    total_words: int = 0
    memory_type: str = "episodic"
    category: str = ""
    oldest: str = ""
    newest: str = ""


class MemoryCompressor:
    """LLM-powered memory compression.

    Finds clusters of related memories, uses LLM to distill them into
    concise summaries, stores the summary as a higher-tier memory,
    and archives the originals.
    """

    def __init__(self, empire_id: str = "", min_cluster_size: int = 3):
        self.empire_id = empire_id
        self.min_cluster_size = min_cluster_size

    def run_compression(self) -> CompressionResult:
        """Run a full compression cycle.

        1. Find clusters of related memories
        2. Compress each cluster with LLM
        3. Store compressed summaries
        4. Archive originals

        Returns:
            CompressionResult.
        """
        result = CompressionResult()

        # Find compressible clusters
        clusters = self.find_clusters()
        result.clusters_found = len(clusters)

        for cluster in clusters:
            try:
                compressed = self.compress_cluster(cluster)
                if compressed:
                    result.clusters_compressed += 1
                    result.memories_consumed += len(cluster.memories)
                    result.summaries_created += 1
                    result.tokens_before += cluster.total_words
                    result.tokens_after += compressed.get("summary_words", 0)
                    result.cost_usd += compressed.get("cost", 0)
            except Exception as e:
                logger.warning("Cluster compression failed for '%s': %s", cluster.cluster_key, e)

        if result.tokens_before > 0:
            result.compression_ratio = 1.0 - (result.tokens_after / result.tokens_before)

        logger.info(
            "Compression: %d clusters, %d compressed, %d memories → %d summaries (%.0f%% reduction)",
            result.clusters_found, result.clusters_compressed,
            result.memories_consumed, result.summaries_created,
            result.compression_ratio * 100,
        )

        return result

    def find_clusters(self) -> list[MemoryCluster]:
        """Find clusters of related memories that should be compressed.

        Groups by:
        - Category (web_scrape, task_outcome, auto_research, etc.)
        - Memory type (episodic memories are highest priority)
        - Age (older memories get compressed first)
        """
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)

        clusters: dict[str, MemoryCluster] = {}

        # Get all memories, sorted by type and category
        for mtype in ["episodic", "semantic"]:
            memories = mm.recall(memory_types=[mtype], limit=200, refresh_on_access=False)

            for mem in memories:
                # Skip high-importance memories
                if mem.get("importance", 0) > 0.8:
                    continue

                # Skip very recent memories (< 24 hours)
                created = mem.get("created_at", "")
                if created:
                    try:
                        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if (datetime.now(timezone.utc) - created_dt).total_seconds() < 86400:
                            continue
                    except Exception:
                        pass

                # Build cluster key
                category = mem.get("category", "general")
                tags = mem.get("tags", [])

                # Cluster by category + primary tag
                primary_tag = tags[0] if tags else "general"
                cluster_key = f"{mtype}:{category}:{primary_tag}"

                if cluster_key not in clusters:
                    clusters[cluster_key] = MemoryCluster(
                        cluster_key=cluster_key,
                        memory_type=mtype,
                        category=category,
                    )

                cluster = clusters[cluster_key]
                content = mem.get("content", "")
                cluster.memories.append(mem)
                cluster.total_words += len(content.split())

                # Track time range
                if created:
                    if not cluster.oldest or created < cluster.oldest:
                        cluster.oldest = created
                    if not cluster.newest or created > cluster.newest:
                        cluster.newest = created

        # Filter to clusters that meet minimum size
        return [c for c in clusters.values() if len(c.memories) >= self.min_cluster_size]

    def compress_cluster(self, cluster: MemoryCluster) -> dict | None:
        """Compress a cluster of memories into a single summary.

        Uses LLM to distill the key information from multiple memories
        into one concise, high-quality memory.

        Args:
            cluster: The memory cluster to compress.

        Returns:
            Dict with summary info, or None if compression failed.
        """
        if len(cluster.memories) < self.min_cluster_size:
            return None

        # Build the content to compress
        memory_texts = []
        for i, mem in enumerate(cluster.memories[:20]):  # Cap at 20
            title = mem.get("title", "")
            content = mem.get("content", "")[:500]
            created = mem.get("created_at", "")[:10]
            memory_texts.append(f"[{i+1}] ({created}) {title}: {content}")

        combined = "\n\n".join(memory_texts)

        # Use LLM to compress
        from llm.base import LLMRequest, LLMMessage
        from llm.router import ModelRouter, TaskMetadata

        router = ModelRouter()
        prompt = f"""Compress these {len(cluster.memories)} memories into a single concise summary.

Category: {cluster.category}
Type: {cluster.memory_type}
Time range: {cluster.oldest[:10] if cluster.oldest else '?'} to {cluster.newest[:10] if cluster.newest else '?'}

Memories:
{combined}

Instructions:
1. Extract the key facts, insights, and learnings
2. Preserve specific names, dates, numbers, and technical details
3. Remove redundancy and repetition
4. Produce a concise summary that captures everything important
5. Format as a structured knowledge entry

Respond as JSON:
{{
    "title": "Concise title for this knowledge",
    "summary": "The compressed knowledge (be thorough but concise)...",
    "key_facts": ["fact 1", "fact 2", ...],
    "entities_mentioned": ["entity1", "entity2", ...],
    "time_range": "{cluster.oldest[:10] if cluster.oldest else ''} to {cluster.newest[:10] if cluster.newest else ''}"
}}
"""
        try:
            request = LLMRequest(
                messages=[LLMMessage.user(prompt)],
                system_prompt="You are a knowledge compression expert. Distill memories into concise, structured knowledge. Preserve all important facts.",
                temperature=0.2,
                max_tokens=2000,
            )
            response = router.execute(request, TaskMetadata(task_type="analysis", complexity="moderate"))

            # Parse response
            from llm.schemas import _find_json_object, _extract_json_block
            raw = response.content
            data = {}
            for attempt in [raw, _extract_json_block(raw), _find_json_object(raw)]:
                if attempt:
                    try:
                        data = json.loads(attempt)
                        break
                    except (json.JSONDecodeError, TypeError):
                        continue

            if not data.get("summary"):
                data = {"title": f"Compressed: {cluster.category}", "summary": response.content}

            # Store the compressed summary as a semantic memory
            from core.memory.manager import MemoryManager
            mm = MemoryManager(self.empire_id)

            summary_content = data.get("summary", "")
            if data.get("key_facts"):
                summary_content += "\n\nKey facts:\n" + "\n".join(f"- {f}" for f in data["key_facts"])

            mm.store(
                content=summary_content,
                memory_type="semantic",
                title=data.get("title", f"Compressed: {cluster.category}"),
                category=f"compressed_{cluster.category}",
                importance=0.75,  # Compressed memories are high value
                tags=["compressed", cluster.category, cluster.memory_type],
                source_type="compression",
                metadata={
                    "compressed_from": len(cluster.memories),
                    "original_type": cluster.memory_type,
                    "time_range": data.get("time_range", ""),
                    "entities_mentioned": data.get("entities_mentioned", []),
                    "compression_date": datetime.now(timezone.utc).isoformat(),
                },
            )

            # Archive the original memories (reduce importance dramatically)
            self._archive_originals(cluster.memories)

            cluster.total_words = sum(len(m.get("content", "").split()) for m in cluster.memories)
            summary_words = len(summary_content.split())
            logger.info(
                "Compressed %d memories → '%s' (%d words → %d words)",
                len(cluster.memories), data.get("title", "?")[:50],
                cluster.total_words, summary_words,
            )

            return {
                "title": data.get("title", ""),
                "summary_words": summary_words,
                "memories_compressed": len(cluster.memories),
                "cost": response.cost_usd,
            }

        except Exception as e:
            logger.error("LLM compression failed: %s", e)
            return None

    def _archive_originals(self, memories: list[dict]) -> None:
        """Archive original memories after compression.

        Doesn't delete them — just reduces importance to near-zero
        so they don't appear in context windows but remain queryable.
        """
        try:
            from db.engine import session_scope
            from db.models import MemoryEntry

            with session_scope() as session:
                for mem in memories:
                    mem_id = mem.get("id")
                    if mem_id:
                        entry = session.get(MemoryEntry, mem_id)
                        if entry:
                            entry.importance_score = 0.01
                            entry.effective_importance = 0.01
                            # Mark as compressed in metadata
                            meta = dict(entry.metadata_json or {})
                            meta["compressed"] = True
                            meta["compressed_at"] = datetime.now(timezone.utc).isoformat()
                            entry.metadata_json = meta

        except Exception as e:
            logger.warning("Failed to archive originals: %s", e)

    def get_compression_stats(self) -> dict:
        """Get statistics about compressed vs uncompressed memories."""
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)

        all_memories = mm.recall(limit=500, refresh_on_access=False)

        total = len(all_memories)
        compressed = 0
        archived = 0
        compressible = 0

        for mem in all_memories:
            meta = mem.get("metadata", {})
            if isinstance(meta, dict):
                if "compressed_from" in meta:
                    compressed += 1
                if meta.get("compressed"):
                    archived += 1

        clusters = self.find_clusters()
        compressible = sum(len(c.memories) for c in clusters)

        return {
            "total_memories": total,
            "compressed_summaries": compressed,
            "archived_originals": archived,
            "compressible_now": compressible,
            "compressible_clusters": len(clusters),
        }

    def compress_by_topic(self, topic: str) -> dict | None:
        """Compress all memories related to a specific topic.

        Args:
            topic: Topic to compress memories about.

        Returns:
            Compression result or None.
        """
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)

        memories = mm.recall(query=topic, limit=30, refresh_on_access=False)
        if len(memories) < self.min_cluster_size:
            return None

        cluster = MemoryCluster(
            cluster_key=f"topic:{topic}",
            memories=memories,
            total_words=sum(len(m.get("content", "").split()) for m in memories),
            category=topic,
        )

        # Set time range
        dates = [m.get("created_at", "") for m in memories if m.get("created_at")]
        if dates:
            cluster.oldest = min(dates)
            cluster.newest = max(dates)

        return self.compress_cluster(cluster)
