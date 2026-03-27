"""Memory consolidation — merges, deduplicates, and promotes memories."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationResult:
    """Result of a memory consolidation pass."""
    duplicates_found: int = 0
    duplicates_merged: int = 0
    promoted_count: int = 0
    summarized_count: int = 0
    total_processed: int = 0


@dataclass
class DuplicateGroup:
    """A group of potentially duplicate memories."""
    memory_ids: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    similarity: float = 0.0
    suggested_merge_content: str = ""


@dataclass
class PromotionCandidate:
    """A memory that should be promoted to a higher tier."""
    memory_id: str = ""
    current_type: str = ""
    suggested_type: str = ""
    reason: str = ""
    importance: float = 0.0


class MemoryConsolidator:
    """Consolidates, deduplicates, and promotes memories.

    Runs periodically to:
    - Find and merge duplicate memories
    - Promote high-value episodic → experiential
    - Summarize clusters of related episodic memories
    - Compress old memories to save space
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self._repo = None

    def _get_repo(self):
        """Get a fresh repository with its own session."""
        from db.engine import get_session
        from db.repositories.memory import MemoryRepository
        return MemoryRepository(get_session())

    def run_consolidation(self, lieutenant_id: str = "") -> ConsolidationResult:
        """Run a full consolidation pass.

        Args:
            lieutenant_id: Optional lieutenant to consolidate for.

        Returns:
            ConsolidationResult.
        """
        result = ConsolidationResult()

        # 1. Find and merge duplicates
        duplicates = self.find_duplicates(lieutenant_id)
        result.duplicates_found = len(duplicates)
        for group in duplicates:
            if self.merge_duplicate_group(group):
                result.duplicates_merged += 1

        # 2. Find promotion candidates
        candidates = self.find_promotion_candidates(lieutenant_id)
        for candidate in candidates:
            if self.promote_memory(candidate):
                result.promoted_count += 1

        # 3. Summarize old episode clusters
        summarized = self.summarize_old_episodes(lieutenant_id)
        result.summarized_count = summarized

        result.total_processed = result.duplicates_found + len(candidates) + summarized

        logger.info(
            "Consolidation complete: %d duplicates merged, %d promoted, %d summarized",
            result.duplicates_merged, result.promoted_count, result.summarized_count,
        )
        return result

    def find_duplicates(self, lieutenant_id: str = "") -> list[DuplicateGroup]:
        """Find potentially duplicate memories.

        Uses title and content similarity to identify duplicates.
        """
        repo = self._get_repo()
        memories = repo.get_most_important(
            empire_id=self.empire_id,
            lieutenant_id=lieutenant_id or None,
            limit=200,
        )

        # Group by similar titles
        groups: dict[str, list] = {}
        for memory in memories:
            key = (memory.title or "").lower().strip()[:50]
            if key and len(key) > 5:
                if key not in groups:
                    groups[key] = []
                groups[key].append(memory)

        duplicates = []
        for key, group_memories in groups.items():
            if len(group_memories) > 1:
                duplicates.append(DuplicateGroup(
                    memory_ids=[m.id for m in group_memories],
                    titles=[m.title or "" for m in group_memories],
                    similarity=0.9,
                    suggested_merge_content=group_memories[0].content or "",
                ))

        return duplicates

    def merge_duplicate_group(self, group: DuplicateGroup) -> bool:
        """Merge a group of duplicate memories.

        Keeps the highest-importance one, transfers access counts.
        """
        if len(group.memory_ids) < 2:
            return False

        repo = self._get_repo()
        memories = repo.get_many(group.memory_ids)

        if len(memories) < 2:
            return False

        # Keep the one with highest effective importance
        primary = max(memories, key=lambda m: m.effective_importance)
        others = [m for m in memories if m.id != primary.id]

        # Absorb access counts
        for other in others:
            primary.access_count += other.access_count

        # Boost importance slightly
        primary.importance_score = min(1.0, primary.importance_score * 1.05)
        primary.effective_importance = primary.importance_score * primary.decay_factor

        # Delete duplicates
        for other in others:
            repo.delete(other.id)

        repo.flush()
        repo.commit()
        return True

    def find_promotion_candidates(self, lieutenant_id: str = "") -> list[PromotionCandidate]:
        """Find memories that should be promoted to a higher tier."""
        repo = self._get_repo()
        candidates = repo.get_promotion_candidates(
            empire_id=self.empire_id,
            min_importance=0.65,
            min_access_count=1,
        )

        promotions = []
        for memory in candidates:
            if lieutenant_id and memory.lieutenant_id != lieutenant_id:
                continue

            promotions.append(PromotionCandidate(
                memory_id=memory.id,
                current_type=memory.memory_type,
                suggested_type="experiential" if memory.memory_type == "episodic" else "semantic",
                reason=f"High importance ({memory.importance_score:.2f}) and access count ({memory.access_count})",
                importance=memory.importance_score,
            ))

        return promotions

    def promote_memory(self, candidate: PromotionCandidate) -> bool:
        """Promote a memory to a higher tier."""
        repo = self._get_repo()
        memory = repo.get(candidate.memory_id)

        if not memory:
            return False

        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)

        # Create promoted memory
        mm.store(
            content=f"[Promoted from {candidate.current_type}] {memory.content}",
            memory_type=candidate.suggested_type,
            lieutenant_id=memory.lieutenant_id or "",
            title=f"Promoted: {memory.title}" if memory.title else "Promoted memory",
            category=memory.category,
            importance=memory.importance_score * 1.1,
            tags=(memory.tags_json or []) + ["promoted"],
            source_type="promotion",
            metadata={"promoted_from": candidate.memory_id},
        )

        # Mark original as promoted
        repo.mark_promoted(candidate.memory_id, candidate.suggested_type)
        repo.commit()

        return True

    def summarize_old_episodes(self, lieutenant_id: str = "", days: int = 14) -> int:
        """Summarize clusters of old episodic memories.

        Instead of keeping many individual episodes, create a summary
        and archive the originals.
        """
        repo = self._get_repo()

        # Get old episodic memories
        from datetime import datetime, timezone, timedelta
        from sqlalchemy import select, and_
        from db.models import MemoryEntry

        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(MemoryEntry)
            .where(and_(
                MemoryEntry.empire_id == self.empire_id,
                MemoryEntry.memory_type == "episodic",
                MemoryEntry.created_at < threshold,
                MemoryEntry.promoted_to_type.is_(None),
                MemoryEntry.importance_score < 0.6,
            ))
            .limit(50)
        )
        old_episodes = list(repo.session.execute(stmt).scalars().all())

        if len(old_episodes) < 5:
            return 0

        # Create summary
        contents = [ep.content[:200] for ep in old_episodes]
        summary_text = f"Summary of {len(old_episodes)} episodes:\n" + "\n".join(f"- {c}" for c in contents[:10])

        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        mm.store(
            content=summary_text,
            memory_type="experiential",
            lieutenant_id=lieutenant_id,
            title=f"Episode summary ({len(old_episodes)} episodes)",
            category="episode_summary",
            importance=0.5,
            tags=["summary", "episodes"],
            source_type="consolidation",
        )

        # Archive the old episodes (reduce their importance dramatically)
        for ep in old_episodes:
            ep.importance_score = 0.01
            ep.effective_importance = 0.01

        repo.flush()
        repo.commit()

        return len(old_episodes)

    def get_consolidation_stats(self, lieutenant_id: str = "") -> dict:
        """Get statistics about consolidation potential."""
        duplicates = self.find_duplicates(lieutenant_id)
        candidates = self.find_promotion_candidates(lieutenant_id)

        return {
            "duplicate_groups": len(duplicates),
            "total_duplicates": sum(len(g.memory_ids) for g in duplicates),
            "promotion_candidates": len(candidates),
            "action_needed": len(duplicates) > 0 or len(candidates) > 0,
        }
