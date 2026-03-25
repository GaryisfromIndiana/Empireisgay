"""Central memory manager — orchestrates the 4-tier memory system."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class MemoryContext:
    """All relevant memories for a task, organized by tier."""
    semantic: list[dict] = field(default_factory=list)
    experiential: list[dict] = field(default_factory=list)
    design: list[dict] = field(default_factory=list)
    episodic: list[dict] = field(default_factory=list)
    total_count: int = 0
    token_estimate: int = 0

    def to_prompt_sections(self) -> str:
        """Format memories for injection into LLM prompts."""
        parts = []
        if self.semantic:
            items = "\n".join(f"- {m.get('content', '')[:200]}" for m in self.semantic[:5])
            parts.append(f"## Domain Knowledge\n{items}")
        if self.experiential:
            items = "\n".join(f"- {m.get('content', '')[:200]}" for m in self.experiential[:5])
            parts.append(f"## Lessons Learned\n{items}")
        if self.design:
            items = "\n".join(f"- {m.get('content', '')[:200]}" for m in self.design[:3])
            parts.append(f"## Design Patterns\n{items}")
        if self.episodic:
            items = "\n".join(f"- {m.get('content', '')[:200]}" for m in self.episodic[:3])
            parts.append(f"## Recent Context\n{items}")
        return "\n\n".join(parts) if parts else ""


@dataclass
class MemoryStats:
    """Statistics about memory usage."""
    total_count: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    avg_importance: float = 0.0
    avg_decay: float = 0.0
    storage_estimate_kb: float = 0.0


class MemoryManager:
    """Orchestrates the 4-tier memory system.

    Manages storage, recall, consolidation, decay, and cleanup
    across semantic, experiential, design, and episodic memories.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self._memory_repo = None

    def _get_repo(self):
        """Get a fresh memory repository with its own session."""
        from db.engine import get_session
        from db.repositories.memory import MemoryRepository
        session = get_session()
        return MemoryRepository(session)

    def store(
        self,
        content: str,
        memory_type: str,
        lieutenant_id: str = "",
        title: str = "",
        category: str = "general",
        importance: float = 0.5,
        confidence: float = 0.8,
        tags: list[str] | None = None,
        metadata: dict | None = None,
        source_task_id: str = "",
        source_type: str = "task",
        expires_hours: int | None = None,
    ) -> dict:
        """Store a new memory entry.

        Args:
            content: Memory content.
            memory_type: One of: semantic, experiential, design, episodic.
            lieutenant_id: Owning lieutenant.
            title: Short title.
            category: Category for organization.
            importance: Importance score (0-1).
            confidence: Confidence in the memory (0-1).
            tags: Tags for searching.
            metadata: Additional metadata.
            source_task_id: Task that generated this memory.
            source_type: How the memory was created.
            expires_hours: Optional TTL in hours.

        Returns:
            Created memory entry as dict.
        """
        expires_at = None
        if expires_hours:
            from datetime import timedelta
            expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

        from db.engine import session_scope
        from db.models import MemoryEntry as MemoryModel
        from db.models import _generate_id

        entry_id = _generate_id()
        with session_scope() as session:
            entry = MemoryModel(
                id=entry_id,
                empire_id=self.empire_id,
                lieutenant_id=lieutenant_id or None,
                memory_type=memory_type,
                category=category,
                title=title,
                content=content,
                importance_score=importance,
                confidence_score=confidence,
                effective_importance=importance,
                decay_factor=1.0,
                tags_json=tags or [],
                metadata_json=metadata or {},
                source_task_id=source_task_id or None,
                source_type=source_type,
                expires_at=expires_at,
            )
            session.add(entry)

        logger.debug("Stored %s memory: %s (importance=%.2f)", memory_type, title or content[:50], importance)
        return {"id": entry_id, "type": memory_type, "title": title}

    def recall(
        self,
        query: str = "",
        memory_types: list[str] | None = None,
        lieutenant_id: str = "",
        limit: int = 20,
    ) -> list[dict]:
        """Recall memories matching a query.

        Args:
            query: Search query.
            memory_types: Filter by memory types.
            lieutenant_id: Filter by lieutenant.
            limit: Max results.

        Returns:
            List of memory entries as dicts.
        """
        repo = self._get_repo()

        if query:
            entries = repo.search(
                query=query,
                empire_id=self.empire_id,
                lieutenant_id=lieutenant_id or None,
                memory_types=memory_types,
                limit=limit,
            )
        else:
            entries = repo.get_most_important(
                empire_id=self.empire_id,
                lieutenant_id=lieutenant_id or None,
                memory_types=memory_types,
                limit=limit,
            )

        # Refresh access counts (best-effort — don't fail reads on write errors)
        try:
            for entry in entries:
                entry.refresh()
            repo.flush()
        except Exception:
            pass  # Access count update is not critical

        return [
            {
                "id": e.id,
                "type": e.memory_type,
                "title": e.title,
                "content": e.content,
                "importance": e.effective_importance,
                "category": e.category,
                "tags": e.tags_json,
                "metadata": e.metadata_json,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ]

    def recall_for_context(
        self,
        lieutenant_id: str,
        token_budget: int = 4000,
    ) -> MemoryContext:
        """Get all relevant memories for task context within token budget.

        Args:
            lieutenant_id: Lieutenant to get memories for.
            token_budget: Maximum tokens worth of memory.

        Returns:
            MemoryContext organized by tier.
        """
        repo = self._get_repo()
        memories_by_type = repo.get_for_context(
            empire_id=self.empire_id,
            lieutenant_id=lieutenant_id,
            token_budget=token_budget,
        )
        repo.commit()

        context = MemoryContext()
        for mtype, entries in memories_by_type.items():
            items = [
                {"id": e.id, "content": e.content, "title": e.title, "importance": e.effective_importance}
                for e in entries
            ]
            setattr(context, mtype, items)
            context.total_count += len(items)

        context.token_estimate = sum(
            len(m.get("content", "")) // 4
            for memories in [context.semantic, context.experiential, context.design, context.episodic]
            for m in memories
        )

        return context

    def consolidate(self, lieutenant_id: str = "") -> int:
        """Consolidate related memories by promoting episodic → experiential.

        Args:
            lieutenant_id: Lieutenant to consolidate for.

        Returns:
            Number of memories promoted.
        """
        repo = self._get_repo()
        candidates = repo.get_promotion_candidates(
            empire_id=self.empire_id,
            min_importance=0.7,
            min_access_count=3,
        )

        promoted = 0
        for entry in candidates:
            if lieutenant_id and entry.lieutenant_id != lieutenant_id:
                continue

            # Create experiential memory from episodic
            self.store(
                content=f"[Promoted from episodic] {entry.content}",
                memory_type="experiential",
                lieutenant_id=entry.lieutenant_id or "",
                title=f"Lesson: {entry.title}" if entry.title else "Promoted lesson",
                category=entry.category,
                importance=entry.importance_score * 1.1,  # Slight boost
                tags=entry.tags_json or [],
                source_type="promotion",
                metadata={"promoted_from": entry.id},
            )

            repo.mark_promoted(entry.id, "experiential")
            promoted += 1

        repo.commit()
        logger.info("Consolidated %d episodic memories to experiential", promoted)
        return promoted

    def decay(self, rate: float = 0.01) -> int:
        """Apply time-based decay to all memories.

        Args:
            rate: Decay rate per application.

        Returns:
            Number of memories decayed.
        """
        repo = self._get_repo()
        count = repo.apply_decay(empire_id=self.empire_id, rate=rate)
        repo.commit()
        logger.info("Applied decay to %d memories (rate=%.3f)", count, rate)
        return count

    def cleanup(self, importance_threshold: float = 0.05) -> dict:
        """Clean up low-value and expired memories.

        Args:
            importance_threshold: Remove memories below this importance.

        Returns:
            Cleanup stats.
        """
        repo = self._get_repo()

        expired = repo.cleanup_expired(self.empire_id)
        low_importance = repo.cleanup_low_importance(self.empire_id, threshold=importance_threshold)
        old_episodic = repo.cleanup_old_episodic(self.empire_id, days=30)

        repo.commit()

        stats = {
            "expired_removed": expired,
            "low_importance_removed": low_importance,
            "old_episodic_removed": old_episodic,
            "total_removed": expired + low_importance + old_episodic,
        }
        logger.info("Memory cleanup: %s", stats)
        return stats

    def get_stats(self, lieutenant_id: str = "") -> MemoryStats:
        """Get memory statistics.

        Args:
            lieutenant_id: Optional lieutenant filter.

        Returns:
            Memory statistics.
        """
        repo = self._get_repo()
        raw_stats = repo.get_stats(self.empire_id, lieutenant_id or None)

        return MemoryStats(
            total_count=raw_stats.get("total", 0),
            by_type=raw_stats.get("by_type", {}),
            avg_importance=raw_stats.get("avg_importance", 0.0),
            avg_decay=raw_stats.get("avg_decay", 0.0),
        )

    def search(
        self,
        query: str,
        memory_types: list[str] | None = None,
        lieutenant_id: str = "",
        limit: int = 20,
    ) -> list[dict]:
        """Search memories by content."""
        return self.recall(query=query, memory_types=memory_types, lieutenant_id=lieutenant_id, limit=limit)

    def store_task_outcome(
        self,
        task_id: str,
        task_title: str,
        outcome: str,
        success: bool,
        lieutenant_id: str,
        learnings: list[str] | None = None,
    ) -> list[dict]:
        """Store memories from a task outcome.

        Creates an episodic memory of the task, plus experiential memories
        for any learnings extracted.

        Args:
            task_id: Task ID.
            task_title: Task title.
            outcome: Task outcome summary.
            success: Whether task succeeded.
            lieutenant_id: Executing lieutenant.
            learnings: Extracted learnings.

        Returns:
            List of created memory entries.
        """
        created = []

        # Episodic: raw task record
        created.append(self.store(
            content=f"Task '{task_title}': {'SUCCESS' if success else 'FAILED'}\n\n{outcome[:2000]}",
            memory_type="episodic",
            lieutenant_id=lieutenant_id,
            title=f"Task: {task_title}",
            importance=0.6 if success else 0.7,
            source_task_id=task_id,
            expires_hours=720,  # 30 days
            tags=["task_outcome", "success" if success else "failure"],
        ))

        # Experiential: learnings
        for learning in (learnings or []):
            created.append(self.store(
                content=learning,
                memory_type="experiential",
                lieutenant_id=lieutenant_id,
                title=f"Learning from: {task_title}",
                importance=0.7,
                source_task_id=task_id,
                tags=["learning", "task_derived"],
            ))

        return created

    def export_memories(self, lieutenant_id: str = "") -> list[dict]:
        """Export memories for cross-empire sharing.

        Args:
            lieutenant_id: Optional lieutenant filter.

        Returns:
            List of serialized memory entries.
        """
        return self.recall(lieutenant_id=lieutenant_id, limit=500)

    def import_memories(
        self,
        memories: list[dict],
        lieutenant_id: str = "",
    ) -> int:
        """Import memories from another empire.

        Args:
            memories: List of memory dicts.
            lieutenant_id: Target lieutenant.

        Returns:
            Number imported.
        """
        imported = 0
        for mem in memories:
            self.store(
                content=mem.get("content", ""),
                memory_type=mem.get("type", "semantic"),
                lieutenant_id=lieutenant_id,
                title=mem.get("title", ""),
                category=mem.get("category", "imported"),
                importance=mem.get("importance", 0.5) * 0.8,  # Slight discount
                tags=mem.get("tags", []) + ["imported"],
                source_type="import",
            )
            imported += 1
        return imported

    def is_novel(self, content: str, threshold: float = 0.7) -> bool:
        """Check if content is novel (not already known).

        Searches existing memories for similar content. If a close match
        is found, returns False (not novel).

        Args:
            content: Content to check.
            threshold: Word overlap threshold (0-1). Higher = stricter.

        Returns:
            True if content is novel.
        """
        # Take key phrases from the content
        words = set(content.lower().split()[:50])
        if len(words) < 5:
            return True  # Too short to compare

        # Search for similar memories
        search_query = " ".join(list(words)[:10])
        existing = self.recall(query=search_query, limit=5)

        for mem in existing:
            existing_words = set(mem.get("content", "").lower().split()[:50])
            if not existing_words:
                continue

            overlap = len(words & existing_words)
            union = len(words | existing_words)
            similarity = overlap / union if union > 0 else 0

            if similarity >= threshold:
                return False  # Already known

        return True

    def store_if_novel(
        self,
        content: str,
        memory_type: str,
        title: str = "",
        novelty_threshold: float = 0.6,
        **kwargs,
    ) -> dict | None:
        """Store a memory only if the content is novel.

        Args:
            content: Memory content.
            memory_type: Memory type.
            title: Memory title.
            novelty_threshold: Similarity threshold for novelty check.
            **kwargs: Additional args passed to store().

        Returns:
            Created memory dict, or None if duplicate.
        """
        if not self.is_novel(content, threshold=novelty_threshold):
            logger.debug("Skipping duplicate memory: %s", title or content[:50])
            return None

        return self.store(content=content, memory_type=memory_type, title=title, **kwargs)

    def get_context_window(
        self,
        query: str = "",
        lieutenant_id: str = "",
        token_budget: int = 4000,
        include_types: list[str] | None = None,
    ) -> str:
        """Build a context string from memories that fits within a token budget.

        Selects the most relevant and important memories, formats them
        for LLM prompt injection, and ensures they fit within the budget.

        Args:
            query: Optional query for relevance filtering.
            lieutenant_id: Lieutenant to get memories for.
            token_budget: Maximum tokens worth of context.
            include_types: Memory types to include. Defaults to all.

        Returns:
            Formatted context string ready for prompt injection.
        """
        chars_per_token = 4
        char_budget = token_budget * chars_per_token

        types = include_types or ["semantic", "experiential", "design", "episodic"]

        # Get memories — prioritize by query relevance, then importance
        all_memories = []
        for mtype in types:
            if query:
                memories = self.recall(query=query, memory_types=[mtype], lieutenant_id=lieutenant_id, limit=10)
            else:
                memories = self.recall(memory_types=[mtype], lieutenant_id=lieutenant_id, limit=10)
            all_memories.extend(memories)

        # Sort by importance
        all_memories.sort(key=lambda m: m.get("importance", 0), reverse=True)

        # Build context within budget
        sections = {
            "semantic": ("Domain Knowledge", []),
            "experiential": ("Lessons Learned", []),
            "design": ("Design Patterns", []),
            "episodic": ("Recent Context", []),
        }

        used_chars = 0
        for mem in all_memories:
            mtype = mem.get("type", "semantic")
            content = mem.get("content", "")
            title = mem.get("title", "")

            # Truncate individual memory if needed
            entry = f"- {title}: {content[:300]}" if title else f"- {content[:300]}"
            entry_len = len(entry)

            if used_chars + entry_len > char_budget:
                break

            if mtype in sections:
                sections[mtype][1].append(entry)
                used_chars += entry_len

        # Format into sections
        parts = []
        for mtype, (header, entries) in sections.items():
            if entries:
                parts.append(f"## {header}\n" + "\n".join(entries))

        return "\n\n".join(parts) if parts else ""

    def get_memory_summary(self) -> str:
        """Get a human-readable summary of what Empire knows.

        Returns:
            Summary string.
        """
        stats = self.get_stats()
        total = stats.total_count
        by_type = stats.by_type

        if total == 0:
            return "Empire has no memories yet."

        parts = [f"Empire has {total} memories:"]
        for mtype, data in by_type.items():
            count = data.get("count", data) if isinstance(data, dict) else data
            parts.append(f"  - {mtype}: {count}")

        return "\n".join(parts)
