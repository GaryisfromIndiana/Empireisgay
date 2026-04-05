"""Knowledge maintenance — keeps the knowledge graph healthy and up-to-date."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DuplicateGroup:
    """A group of potentially duplicate entities."""
    entities: list[dict] = field(default_factory=list)
    similarity: float = 0.0
    suggested_merge: str = ""


@dataclass
class MergeResult:
    """Result of merging duplicate entities."""
    merged_count: int = 0
    groups_processed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class Contradiction:
    """A contradiction detected in the knowledge graph."""
    entity_a: dict = field(default_factory=dict)
    entity_b: dict = field(default_factory=dict)
    description: str = ""
    severity: str = "low"


@dataclass
class ValidationReport:
    """Report from relation validation."""
    total_relations: int = 0
    valid_relations: int = 0
    broken_relations: int = 0
    issues: list[str] = field(default_factory=list)


@dataclass
class KnowledgeReport:
    """Comprehensive knowledge graph health report."""
    entity_count: int = 0
    relation_count: int = 0
    health_score: float = 0.0
    duplicate_groups: int = 0
    contradictions: int = 0
    stale_entities: int = 0
    orphaned_entities: int = 0
    recommendations: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class KnowledgeGap:
    """An identified gap in knowledge."""
    topic: str
    importance: float = 0.5
    suggested_queries: list[str] = field(default_factory=list)
    related_entities: list[str] = field(default_factory=list)


class KnowledgeMaintainer:
    """Keeps the knowledge graph healthy through regular maintenance.

    Handles duplicate detection, relation validation, importance recalculation,
    contradiction detection, and knowledge gap analysis.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self._graph = None

    def _get_graph(self):
        if self._graph is None:
            from core.knowledge.graph import KnowledgeGraph
            self._graph = KnowledgeGraph(self.empire_id)
        return self._graph

    def run_maintenance(self) -> KnowledgeReport:
        """Run full maintenance cycle.

        Returns:
            KnowledgeReport with findings and actions taken.
        """
        logger.info("Starting knowledge maintenance for empire %s", self.empire_id)

        report = KnowledgeReport()

        # 1. Get baseline stats
        graph = self._get_graph()
        stats = graph.get_stats()
        report.entity_count = stats.entity_count
        report.relation_count = stats.relation_count

        # 2. Detect and merge duplicates
        duplicates = self.detect_duplicates()
        report.duplicate_groups = len(duplicates)
        if duplicates:
            merge_result = self.merge_duplicates(duplicates)
            report.recommendations.append(f"Merged {merge_result.merged_count} duplicate entities")

        # 3. Validate relations
        validation = self.validate_relations()
        if validation.broken_relations > 0:
            report.issues.append(f"{validation.broken_relations} broken relations found")

        # 4. Decay stale entities
        stale_count = self.decay_stale_entities()
        report.stale_entities = stale_count
        if stale_count > 0:
            report.recommendations.append(f"Decayed confidence on {stale_count} stale entities")

        # 5. Update importance scores
        self.update_importance_scores()

        # 6. Prune low-quality entities
        pruned = graph.prune(min_confidence=0.15, min_connections=0)
        if pruned > 0:
            report.recommendations.append(f"Pruned {pruned} low-quality entities")

        # Calculate health score
        total_issues = report.duplicate_groups + report.stale_entities + len(report.issues)
        if report.entity_count > 0:
            issue_ratio = total_issues / report.entity_count
            report.health_score = max(0.0, min(1.0, 1.0 - issue_ratio))
        else:
            report.health_score = 1.0

        logger.info("Maintenance complete. Health score: %.2f", report.health_score)
        return report

    def detect_duplicates(self) -> list[DuplicateGroup]:
        """Detect potentially duplicate entities.

        Uses name similarity to find candidates.

        Returns:
            List of duplicate groups.
        """
        from db.engine import repo_scope
        from db.repositories.knowledge import KnowledgeRepository
        with repo_scope(KnowledgeRepository) as repo:
            entities = repo.get_by_empire(self.empire_id, limit=5000)

            # Group by normalized name
            name_groups: dict[str, list] = {}
            for entity in entities:
                normalized = entity.name.lower().strip()
                # Also check without common suffixes/prefixes
                key = normalized.replace("the ", "").replace("a ", "").strip()
                if key not in name_groups:
                    name_groups[key] = []
                name_groups[key].append({
                    "id": entity.id,
                    "name": entity.name,
                    "type": entity.entity_type,
                    "confidence": entity.confidence,
                })

            duplicates = []
            for key, group in name_groups.items():
                if len(group) > 1:
                    # Find the one with highest confidence as merge target
                    best = max(group, key=lambda x: x["confidence"])
                    duplicates.append(DuplicateGroup(
                        entities=group,
                        similarity=0.95,
                        suggested_merge=best["name"],
                    ))

            return duplicates

    def merge_duplicates(self, groups: list[DuplicateGroup]) -> MergeResult:
        """Merge duplicate entity groups.

        Args:
            groups: Duplicate groups to merge.

        Returns:
            MergeResult.
        """
        graph = self._get_graph()
        result = MergeResult(groups_processed=len(groups))

        for group in groups:
            names = [e["name"] for e in group.entities]
            try:
                merge_info = graph.merge_entities(names)
                if merge_info:
                    result.merged_count += len(group.entities) - 1
            except Exception as e:
                result.errors.append(f"Failed to merge {names}: {e}")

        return result

    def decay_stale_entities(self, days_threshold: int = 90, rate: float = 0.05) -> int:
        """Reduce confidence of old, unaccessed entities.

        Args:
            days_threshold: Days of inactivity before decay.
            rate: Amount to reduce confidence.

        Returns:
            Number of entities decayed.
        """
        from db.engine import repo_scope
        from db.repositories.knowledge import KnowledgeRepository
        with repo_scope(KnowledgeRepository) as repo:
            count = repo.decay_confidence(self.empire_id, days_threshold, rate)
            repo.commit()
            return count

    def validate_relations(self) -> ValidationReport:
        """Check for broken or invalid relations.

        Returns:
            ValidationReport.
        """
        from db.engine import repo_scope
        from db.repositories.knowledge import KnowledgeRepository
        with repo_scope(KnowledgeRepository) as repo:
            from sqlalchemy import select
            from sqlalchemy.orm import joinedload
            from db.models import KnowledgeEntity

            # Eager load outgoing_relations to avoid N+1 queries
            stmt = (
                select(KnowledgeEntity)
                .where(KnowledgeEntity.empire_id == self.empire_id)
                .options(joinedload(KnowledgeEntity.outgoing_relations))
                .limit(10000)
            )
            entities = list(repo.session.execute(stmt).scalars().unique().all())

            report = ValidationReport()
            entity_ids = {e.id for e in entities}

            for entity in entities:
                for rel in (entity.outgoing_relations or []):
                    report.total_relations += 1
                    if rel.target_entity_id not in entity_ids:
                        report.broken_relations += 1
                        report.issues.append(
                            f"Broken relation: {entity.name} -> {rel.target_entity_id} ({rel.relation_type})"
                        )
                    else:
                        report.valid_relations += 1

            return report

    def update_importance_scores(self) -> None:
        """Recalculate PageRank-style importance scores."""
        graph = self._get_graph()
        graph.compute_pagerank()
        logger.info("Updated importance scores for empire %s", self.empire_id)

    def detect_contradictions(self) -> list[Contradiction]:
        """Detect contradictory information in the knowledge graph.

        Returns:
            List of contradictions found.
        """
        # Use semantic memory to check for contradictions
        try:
            from core.memory.semantic import SemanticMemory
            from core.memory.manager import MemoryManager
            mm = MemoryManager(self.empire_id)
            sm = SemanticMemory(mm)

            from db.engine import repo_scope
            from db.repositories.knowledge import KnowledgeRepository
            with repo_scope(KnowledgeRepository) as repo:
                entities = repo.get_by_empire(self.empire_id, limit=100)

                contradictions = []
                for entity in entities:
                    found = sm.find_contradictions(entity.description)
                    for c in found:
                        contradictions.append(Contradiction(
                            entity_a={"name": entity.name, "description": entity.description},
                            description=c.explanation,
                        ))

                return contradictions
        except Exception as e:
            logger.warning("Contradiction detection failed: %s", e)
            return []

    def suggest_gaps(self, domain: str = "") -> list[KnowledgeGap]:
        """Identify knowledge gaps — areas that need more research.

        Only counts externally-sourced entities (web_research or entities
        linked to research tasks) when assessing coverage. Internal entities
        from LLM synthesis, debates, and evolution stay in the graph for
        context but don't drive new research priorities. Without this gate
        the system researches topics it invented from its own output —
        debates about debates.

        Args:
            domain: Optional domain to focus on.

        Returns:
            List of knowledge gaps.
        """
        # Count only externally-sourced entities for gap assessment
        external_stats = self._get_external_entity_stats()

        gaps = []

        # Check for entity types with few EXTERNAL entries
        type_counts = external_stats["type_counts"]
        if type_counts:
            avg_count = sum(type_counts.values()) / len(type_counts) if type_counts else 0
            for entity_type, count in type_counts.items():
                if count < avg_count * 0.3:
                    gaps.append(KnowledgeGap(
                        topic=f"{entity_type} entities",
                        importance=0.6,
                        suggested_queries=[
                            f"Research key {entity_type}s in {domain or 'this domain'}",
                            f"Identify important {entity_type}s we're missing",
                        ],
                    ))

        # Check for poorly connected entities (central entities are fine
        # to pull from the full graph — they're context, not gap drivers)
        graph = self._get_graph()
        central = graph.get_central_entities(limit=5)
        if central:
            for node in central:
                if node.confidence < 0.5:
                    gaps.append(KnowledgeGap(
                        topic=f"Low confidence on key entity: {node.name}",
                        importance=0.7,
                        suggested_queries=[
                            f"Research {node.name} in depth",
                            f"Verify information about {node.name}",
                        ],
                        related_entities=[node.name],
                    ))

        # General gaps if external graph is small
        if external_stats["total"] < 10:
            gaps.append(KnowledgeGap(
                topic="General domain knowledge",
                importance=0.8,
                suggested_queries=[
                    f"Build foundational knowledge about {domain or 'this domain'}",
                    "Identify key concepts, players, and technologies",
                ],
            ))

        return gaps

    def _get_external_entity_stats(self) -> dict:
        """Count entities from external sources only.

        External = source_type='web_research' OR has a source_task_id
        (meaning it came from an actual research task that web-searched).
        Everything else (LLM synthesis, debates, evolution) is internal
        and excluded from gap assessment.
        """
        from db.engine import repo_scope
        from db.repositories.knowledge import KnowledgeRepository
        from sqlalchemy import select, func, or_
        from db.models import KnowledgeEntity

        with repo_scope(KnowledgeRepository) as repo:
            external_filter = or_(
                KnowledgeEntity.source_type == "web_research",
                KnowledgeEntity.source_task_id.is_not(None),
            )

            # Total external count
            total = repo.session.execute(
                select(func.count(KnowledgeEntity.id)).where(
                    KnowledgeEntity.empire_id == self.empire_id,
                    external_filter,
                )
            ).scalar() or 0

            # Type breakdown
            rows = repo.session.execute(
                select(
                    KnowledgeEntity.entity_type,
                    func.count(KnowledgeEntity.id),
                ).where(
                    KnowledgeEntity.empire_id == self.empire_id,
                    external_filter,
                ).group_by(KnowledgeEntity.entity_type)
            ).all()

            type_counts = {row[0]: row[1] for row in rows}

            return {"total": total, "type_counts": type_counts}

    def compact_graph(self) -> dict:
        """Remove orphaned nodes and edges, optimize storage.

        Returns:
            Stats about what was cleaned up.
        """
        graph = self._get_graph()

        # Prune entities with no connections and low importance
        pruned = graph.prune(min_confidence=0.1, min_connections=0)

        return {
            "entities_pruned": pruned,
            "empire_id": self.empire_id,
        }

    def deep_llm_audit(self, batch_size: int = 20) -> dict:
        """Deep LLM audit — scans entities for hallucinations, contamination, and malformed data.

        Uses an LLM to evaluate each entity's description for:
        - Hallucinated facts (plausible but false statements)
        - Prompt artifacts (leaked system prompts, formatting remnants)
        - Outdated information (superseded by newer data)
        - Malformed data (broken formatting, incomplete descriptions)

        Args:
            batch_size: Number of entities to audit per run.

        Returns:
            Audit results with purged/flagged entity counts.
        """
        from db.engine import repo_scope
        from db.repositories.knowledge import KnowledgeRepository
        with repo_scope(KnowledgeRepository) as repo:
            return self._deep_llm_audit_impl(repo, batch_size)

    def _deep_llm_audit_impl(self, repo, batch_size: int) -> dict:
        entities = repo.get_by_empire(self.empire_id, limit=batch_size)

        if not entities:
            return {"audited": 0, "flagged": 0, "purged": 0}

        flagged = []
        purged = 0

        try:
            from llm.router import ModelRouter, TaskMetadata
            from llm.base import LLMRequest, LLMMessage
            router = ModelRouter()

            # Batch entities into groups of 5 for efficiency
            for i in range(0, len(entities), 5):
                batch = entities[i:i + 5]
                entity_text = "\n".join(
                    f"[{e.id[:8]}] {e.name} ({e.entity_type}): {(e.description or '')[:200]}"
                    for e in batch
                )

                prompt = (
                    "You are a knowledge graph auditor. Evaluate each entity below for data quality issues.\n\n"
                    "Flag entities that have:\n"
                    "- HALLUCINATION: plausible but likely false or unverifiable claims\n"
                    "- ARTIFACT: prompt remnants, system instructions, formatting debris\n"
                    "- MALFORMED: broken text, incomplete data, nonsensical content\n"
                    "- OUTDATED: information known to be superseded\n\n"
                    f"Entities:\n{entity_text}\n\n"
                    "For each entity, respond with one line:\n"
                    "[entity_id] CLEAN or [entity_id] FLAG:reason\n"
                    "Only flag entities with clear issues. When in doubt, mark CLEAN."
                )

                try:
                    response = router.execute(
                        LLMRequest(
                            messages=[LLMMessage.user(prompt)],
                            max_tokens=500,
                            temperature=0.1,
                        ),
                        TaskMetadata(task_type="analysis", complexity="moderate"),
                    )

                    # Parse response for flagged entities
                    for line in response.content.strip().split("\n"):
                        line = line.strip()
                        if "FLAG:" in line.upper():
                            entity_id_prefix = line.split("]")[0].replace("[", "").strip()
                            reason = line.split("FLAG:")[-1].strip() if "FLAG:" in line else "unknown"

                            # Find matching entity and reduce confidence
                            for e in batch:
                                if e.id.startswith(entity_id_prefix):
                                    flagged.append({
                                        "id": e.id,
                                        "name": e.name,
                                        "reason": reason,
                                    })
                                    # Reduce confidence significantly
                                    if e.confidence > 0.2:
                                        e.confidence = max(0.1, e.confidence - 0.3)
                                    else:
                                        # Very low confidence — purge
                                        repo.delete(e.id)
                                        purged += 1
                                    break

                except Exception as e:
                    logger.warning("LLM audit batch failed: %s", e)
                    continue

            repo.commit()

        except Exception as e:
            logger.warning("Deep LLM audit failed: %s", e)
            return {"audited": len(entities), "error": str(e)}

        logger.info(
            "Deep LLM audit: %d audited, %d flagged, %d purged",
            len(entities), len(flagged), purged,
        )

        return {
            "audited": len(entities),
            "flagged": len(flagged),
            "purged": purged,
            "flagged_entities": flagged[:10],  # Return top 10
        }

    def generate_knowledge_report(self) -> KnowledgeReport:
        """Generate a comprehensive knowledge report without running maintenance."""
        graph = self._get_graph()
        stats = graph.get_stats()

        duplicates = self.detect_duplicates()
        gaps = self.suggest_gaps()

        report = KnowledgeReport(
            entity_count=stats.entity_count,
            relation_count=stats.relation_count,
            duplicate_groups=len(duplicates),
        )

        if stats.entity_count > 0:
            dup_ratio = len(duplicates) / stats.entity_count
            report.health_score = max(0.0, min(1.0, 1.0 - dup_ratio - len(gaps) * 0.05))
        else:
            report.health_score = 0.5

        for gap in gaps:
            report.recommendations.append(f"Knowledge gap: {gap.topic}")

        return report
