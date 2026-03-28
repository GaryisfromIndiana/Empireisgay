"""Memory-specific repository with decay management and tier queries."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, func, and_, or_, desc, asc, delete

from db.models import MemoryEntry
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class MemoryRepository(BaseRepository[MemoryEntry]):
    """Repository for the 4-tier memory system."""

    model_class = MemoryEntry

    # ── Tier queries ───────────────────────────────────────────────────

    def get_by_type(
        self,
        memory_type: str,
        empire_id: str | None = None,
        lieutenant_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryEntry]:
        """Get memories by type (semantic, experiential, design, episodic)."""
        filters: dict[str, Any] = {"memory_type": memory_type}
        if empire_id:
            filters["empire_id"] = empire_id
        if lieutenant_id:
            filters["lieutenant_id"] = lieutenant_id
        return self.find(filters=filters, limit=limit, order_by="effective_importance", order_dir="desc")

    def get_semantic(self, empire_id: str, lieutenant_id: str | None = None, limit: int = 50) -> list[MemoryEntry]:
        """Get semantic (factual) memories."""
        return self.get_by_type("semantic", empire_id, lieutenant_id, limit)

    def get_experiential(self, empire_id: str, lieutenant_id: str | None = None, limit: int = 50) -> list[MemoryEntry]:
        """Get experiential (lessons learned) memories."""
        return self.get_by_type("experiential", empire_id, lieutenant_id, limit)

    def get_design(self, empire_id: str, lieutenant_id: str | None = None, limit: int = 50) -> list[MemoryEntry]:
        """Get design pattern memories."""
        return self.get_by_type("design", empire_id, lieutenant_id, limit)

    def get_episodic(self, empire_id: str, lieutenant_id: str | None = None, limit: int = 50) -> list[MemoryEntry]:
        """Get episodic (task record) memories."""
        return self.get_by_type("episodic", empire_id, lieutenant_id, limit)

    # ── Importance & relevance ─────────────────────────────────────────

    def get_most_important(
        self,
        empire_id: str,
        lieutenant_id: str | None = None,
        memory_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """Get most important memories (by effective_importance)."""
        stmt = (
            select(MemoryEntry)
            .where(MemoryEntry.empire_id == empire_id)
        )
        if lieutenant_id:
            stmt = stmt.where(MemoryEntry.lieutenant_id == lieutenant_id)
        if memory_types:
            stmt = stmt.where(MemoryEntry.memory_type.in_(memory_types))
        stmt = stmt.order_by(desc(MemoryEntry.effective_importance)).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def get_most_accessed(
        self,
        empire_id: str,
        lieutenant_id: str | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """Get most frequently accessed memories."""
        stmt = (
            select(MemoryEntry)
            .where(MemoryEntry.empire_id == empire_id)
        )
        if lieutenant_id:
            stmt = stmt.where(MemoryEntry.lieutenant_id == lieutenant_id)
        stmt = stmt.order_by(desc(MemoryEntry.access_count)).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def get_recent(
        self,
        empire_id: str,
        lieutenant_id: str | None = None,
        hours: int = 24,
        limit: int = 50,
    ) -> list[MemoryEntry]:
        """Get recently created memories."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = (
            select(MemoryEntry)
            .where(and_(
                MemoryEntry.empire_id == empire_id,
                MemoryEntry.created_at >= since,
            ))
        )
        if lieutenant_id:
            stmt = stmt.where(MemoryEntry.lieutenant_id == lieutenant_id)
        stmt = stmt.order_by(desc(MemoryEntry.created_at)).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def search(
        self,
        query: str,
        empire_id: str,
        lieutenant_id: str | None = None,
        memory_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """Search memories by content (LIKE query)."""
        pattern = f"%{query}%"
        stmt = (
            select(MemoryEntry)
            .where(and_(
                MemoryEntry.empire_id == empire_id,
                or_(
                    MemoryEntry.content.ilike(pattern),
                    MemoryEntry.title.ilike(pattern),
                    MemoryEntry.summary.ilike(pattern),
                ),
            ))
        )
        if lieutenant_id:
            stmt = stmt.where(MemoryEntry.lieutenant_id == lieutenant_id)
        if memory_types:
            stmt = stmt.where(MemoryEntry.memory_type.in_(memory_types))
        stmt = stmt.order_by(desc(MemoryEntry.effective_importance)).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def search_by_tags(
        self,
        tags: list[str],
        empire_id: str,
        lieutenant_id: str | None = None,
    ) -> list[MemoryEntry]:
        """Search memories that contain any of the given tags."""
        stmt = select(MemoryEntry).where(MemoryEntry.empire_id == empire_id)
        if lieutenant_id:
            stmt = stmt.where(MemoryEntry.lieutenant_id == lieutenant_id)

        # JSON array contains — works for SQLite with JSON1
        conditions = []
        for tag in tags:
            conditions.append(MemoryEntry.tags_json.contains(tag))
        if conditions:
            stmt = stmt.where(or_(*conditions))

        return list(self.session.execute(stmt).scalars().all())

    # ── Decay management ───────────────────────────────────────────────

    def apply_decay(
        self,
        empire_id: str,
        rate: float = 0.01,
        min_decay: float = 0.0,
    ) -> int:
        """Apply time-based decay to all memories.

        Args:
            empire_id: Empire ID.
            rate: Decay rate per application.
            min_decay: Minimum decay factor (memories won't go below this).

        Returns:
            Number of memories decayed.
        """
        stmt = (
            select(MemoryEntry)
            .where(and_(
                MemoryEntry.empire_id == empire_id,
                MemoryEntry.decay_factor > min_decay,
            ))
        )
        memories = list(self.session.execute(stmt).scalars().all())

        count = 0
        for memory in memories:
            # Episodic memories decay faster
            actual_rate = rate * 2 if memory.memory_type == "episodic" else rate
            # Semantic memories decay slower
            if memory.memory_type == "semantic":
                actual_rate = rate * 0.5

            memory.decay_factor = max(min_decay, memory.decay_factor - actual_rate)
            memory.effective_importance = memory.importance_score * memory.decay_factor
            count += 1

        self.session.flush()
        return count

    def refresh_memory(self, memory_id: str) -> MemoryEntry | None:
        """Refresh a memory on access (slows decay)."""
        memory = self.get(memory_id)
        if memory:
            memory.refresh()
            self.session.flush()
        return memory

    # ── Cleanup ────────────────────────────────────────────────────────

    def cleanup_expired(self, empire_id: str) -> int:
        """Remove expired memories."""
        now = datetime.now(timezone.utc)
        stmt = (
            delete(MemoryEntry)
            .where(and_(
                MemoryEntry.empire_id == empire_id,
                MemoryEntry.expires_at.is_not(None),
                MemoryEntry.expires_at < now,
            ))
        )
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

    def cleanup_low_importance(
        self,
        empire_id: str,
        threshold: float = 0.05,
        memory_types: list[str] | None = None,
    ) -> int:
        """Remove memories with very low effective importance."""
        stmt = (
            delete(MemoryEntry)
            .where(and_(
                MemoryEntry.empire_id == empire_id,
                MemoryEntry.effective_importance < threshold,
            ))
        )
        if memory_types:
            stmt = stmt.where(MemoryEntry.memory_type.in_(memory_types))
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

    def cleanup_old_episodic(self, empire_id: str, days: int = 30) -> int:
        """Remove old episodic memories (they should be promoted or discarded)."""
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            delete(MemoryEntry)
            .where(and_(
                MemoryEntry.empire_id == empire_id,
                MemoryEntry.memory_type == "episodic",
                MemoryEntry.created_at < threshold,
                MemoryEntry.promoted_to_type.is_(None),  # Not promoted
                MemoryEntry.importance_score < 0.5,  # Not high importance
            ))
        )
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

    # ── Promotion ──────────────────────────────────────────────────────

    def get_promotion_candidates(
        self,
        empire_id: str,
        min_importance: float = 0.7,
        min_access_count: int = 3,
    ) -> list[MemoryEntry]:
        """Get episodic memories that should be promoted to experiential."""
        stmt = (
            select(MemoryEntry)
            .where(and_(
                MemoryEntry.empire_id == empire_id,
                MemoryEntry.memory_type == "episodic",
                MemoryEntry.promoted_to_type.is_(None),
                MemoryEntry.importance_score >= min_importance,
                MemoryEntry.access_count >= min_access_count,
            ))
            .order_by(desc(MemoryEntry.importance_score))
        )
        return list(self.session.execute(stmt).scalars().all())

    def mark_promoted(self, memory_id: str, promoted_to_type: str) -> None:
        """Mark a memory as promoted to a higher tier."""
        self.update(memory_id, promoted_to_type=promoted_to_type)

    # ── Stats ──────────────────────────────────────────────────────────

    def get_stats(self, empire_id: str, lieutenant_id: str | None = None) -> dict:
        """Get memory statistics."""
        base_filter = and_(MemoryEntry.empire_id == empire_id)
        if lieutenant_id:
            base_filter = and_(base_filter, MemoryEntry.lieutenant_id == lieutenant_id)

        stmt = (
            select(
                MemoryEntry.memory_type,
                func.count(MemoryEntry.id).label("count"),
                func.avg(MemoryEntry.importance_score).label("avg_importance"),
                func.avg(MemoryEntry.decay_factor).label("avg_decay"),
                func.avg(MemoryEntry.access_count).label("avg_access"),
            )
            .where(base_filter)
            .group_by(MemoryEntry.memory_type)
        )
        results = self.session.execute(stmt).all()

        stats = {
            "by_type": {},
            "total": 0,
            "avg_importance": 0.0,
            "avg_decay": 0.0,
        }

        for row in results:
            mtype, count, avg_imp, avg_dec, avg_acc = row
            stats["by_type"][mtype] = {
                "count": count,
                "avg_importance": float(avg_imp or 0),
                "avg_decay": float(avg_dec or 0),
                "avg_access_count": float(avg_acc or 0),
            }
            stats["total"] += count

        if stats["total"] > 0:
            stats["avg_importance"] = (
                sum(d["avg_importance"] * d["count"] for d in stats["by_type"].values())
                / stats["total"]
            )
            stats["avg_decay"] = (
                sum(d["avg_decay"] * d["count"] for d in stats["by_type"].values())
                / stats["total"]
            )

        return stats

    def similarity_search(
        self,
        embedding: list[float],
        empire_id: str,
        lieutenant_id: str | None = None,
        memory_types: list[str] | None = None,
        limit: int = 10,
        min_similarity: float = 0.5,
    ) -> list[dict]:
        """Find memories similar to a given embedding.

        Uses Qdrant when available for sub-millisecond ANN search,
        falls back to in-memory cosine similarity over SQL rows.
        """
        # ── Try Qdrant first ──────────────────────────────────────
        try:
            from core.vector.store import VectorStore
            vs = VectorStore.get_instance(empire_id)
            if vs.enabled:
                hits = vs.search_memories(
                    embedding=embedding,
                    empire_id=empire_id,
                    lieutenant_id=lieutenant_id,
                    memory_types=memory_types,
                    limit=limit,
                    min_score=min_similarity,
                )
                if hits:
                    # Fetch full MemoryEntry objects by ID
                    memory_ids = [h["memory_id"] for h in hits]
                    score_map = {h["memory_id"]: h["score"] for h in hits}
                    entries = list(self.session.execute(
                        select(MemoryEntry).where(MemoryEntry.id.in_(memory_ids))
                    ).scalars().all())
                    entry_map = {e.id: e for e in entries}
                    results = []
                    for mid in memory_ids:
                        entry = entry_map.get(mid)
                        if entry:
                            results.append({"memory": entry, "similarity": score_map[mid]})
                    return results
        except Exception as e:
            logger.debug("Qdrant memory search unavailable, falling back to SQL: %s", e)

        # ── Fallback: in-memory cosine similarity ─────────────────
        stmt = (
            select(MemoryEntry)
            .where(and_(
                MemoryEntry.empire_id == empire_id,
                MemoryEntry.embedding_json.is_not(None),
            ))
        )
        if lieutenant_id:
            stmt = stmt.where(MemoryEntry.lieutenant_id == lieutenant_id)
        if memory_types:
            stmt = stmt.where(MemoryEntry.memory_type.in_(memory_types))

        memories = list(self.session.execute(stmt).scalars().all())

        results = []
        for memory in memories:
            if not memory.embedding_json:
                continue
            sim = self._cosine_similarity(embedding, memory.embedding_json)
            if sim >= min_similarity:
                results.append({"memory": memory, "similarity": sim})

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def get_for_context(
        self,
        empire_id: str,
        lieutenant_id: str,
        token_budget: int = 4000,
        chars_per_token: int = 4,
    ) -> dict[str, list[MemoryEntry]]:
        """Get memories for task context within a token budget.

        Selects the most important memories from each tier that fit
        within the token budget.

        Args:
            empire_id: Empire ID.
            lieutenant_id: Lieutenant ID.
            token_budget: Maximum tokens worth of memory content.
            chars_per_token: Approximate characters per token.

        Returns:
            Dict of memory_type → list of memories.
        """
        char_budget = token_budget * chars_per_token

        result: dict[str, list[MemoryEntry]] = {
            "semantic": [],
            "experiential": [],
            "design": [],
            "episodic": [],
        }

        # Allocate budget: 30% semantic, 30% experiential, 20% design, 20% episodic
        allocations = {
            "semantic": 0.30,
            "experiential": 0.30,
            "design": 0.20,
            "episodic": 0.20,
        }

        for mtype, alloc in allocations.items():
            type_budget = int(char_budget * alloc)
            type_used = 0

            memories = self.get_most_important(
                empire_id=empire_id,
                lieutenant_id=lieutenant_id,
                memory_types=[mtype],
                limit=20,
            )

            for memory in memories:
                content_len = len(memory.content or "")
                if type_used + content_len <= type_budget:
                    result[mtype].append(memory)
                    type_used += content_len
                    # Refresh on access
                    memory.refresh()

        self.session.flush()
        return result
