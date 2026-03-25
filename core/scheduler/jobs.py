"""Job class definitions for the scheduler daemon."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    """Result of a job execution."""
    success: bool = True
    data: dict = field(default_factory=dict)
    error: str = ""
    duration_seconds: float = 0.0
    items_processed: int = 0


class BaseJob(ABC):
    """Abstract base class for scheduled jobs."""

    name: str = "base_job"
    description: str = ""
    interval_seconds: int = 3600
    priority: int = 5
    enabled: bool = True

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self.run_count = 0
        self.error_count = 0
        self.last_result: JobResult | None = None

    @abstractmethod
    def run(self) -> JobResult:
        """Execute the job.

        Returns:
            JobResult.
        """
        ...

    def should_run(self) -> bool:
        """Check if this job should run (override for custom logic)."""
        return self.enabled

    def on_success(self, result: JobResult) -> None:
        """Called after successful execution."""
        self.run_count += 1
        self.last_result = result
        logger.debug("Job %s succeeded: %s", self.name, result.data)

    def on_failure(self, result: JobResult) -> None:
        """Called after failed execution."""
        self.error_count += 1
        self.last_result = result
        logger.warning("Job %s failed: %s", self.name, result.error)

    def execute(self) -> JobResult:
        """Execute with lifecycle hooks."""
        if not self.should_run():
            return JobResult(success=True, data={"skipped": True})

        start = time.time()
        try:
            result = self.run()
            result.duration_seconds = time.time() - start
            if result.success:
                self.on_success(result)
            else:
                self.on_failure(result)
            return result
        except Exception as e:
            result = JobResult(success=False, error=str(e), duration_seconds=time.time() - start)
            self.on_failure(result)
            return result


class LearningCycleJob(BaseJob):
    """Triggers learning cycles for all lieutenants."""

    name = "learning_cycle"
    description = "Run learning cycles for all active lieutenants"
    interval_seconds = 6 * 3600  # 6 hours
    priority = 5

    def run(self) -> JobResult:
        from core.lieutenant.manager import LieutenantManager
        manager = LieutenantManager(self.empire_id)
        result = manager.run_all_learning_cycles()
        return JobResult(
            success=True,
            data=result,
            items_processed=result.get("lieutenants_processed", 0),
        )


class EvolutionCycleJob(BaseJob):
    """Triggers a full evolution cycle."""

    name = "evolution_cycle"
    description = "Run self-improvement evolution cycle"
    interval_seconds = 12 * 3600  # 12 hours
    priority = 6

    def run(self) -> JobResult:
        from core.evolution.cycle import EvolutionCycleManager
        ecm = EvolutionCycleManager(self.empire_id)
        if not ecm.should_run_cycle():
            return JobResult(success=True, data={"skipped": True, "reason": "cooldown"})
        result = ecm.run_full_cycle()
        return JobResult(
            success=True,
            data={"proposals": result.proposals_collected, "approved": result.approved, "applied": result.applied},
            items_processed=result.proposals_collected,
        )


class HealthCheckJob(BaseJob):
    """Runs system health checks."""

    name = "health_check"
    description = "System health monitoring"
    interval_seconds = 5 * 60  # 5 minutes
    priority = 1

    def run(self) -> JobResult:
        from core.scheduler.health import HealthChecker
        checker = HealthChecker(self.empire_id)
        report = checker.run_all_checks()
        return JobResult(
            success=report.get("overall_status") != "unhealthy",
            data=report,
            items_processed=len(report.get("checks", [])),
        )


class KnowledgeMaintenanceJob(BaseJob):
    """Maintains the knowledge graph."""

    name = "knowledge_maintenance"
    description = "Knowledge graph health maintenance"
    interval_seconds = 4 * 3600  # 4 hours
    priority = 4

    def run(self) -> JobResult:
        from core.knowledge.maintenance import KnowledgeMaintainer
        maintainer = KnowledgeMaintainer(self.empire_id)
        report = maintainer.run_maintenance()
        return JobResult(
            success=True,
            data={"health_score": report.health_score, "entities": report.entity_count, "duplicates": report.duplicate_groups},
        )


class MemoryDecayJob(BaseJob):
    """Applies time-based decay to memories."""

    name = "memory_decay"
    description = "Apply memory decay and cleanup"
    interval_seconds = 3600  # 1 hour
    priority = 3

    def run(self) -> JobResult:
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        decayed = mm.decay()
        consolidated = mm.consolidate()
        return JobResult(
            success=True,
            data={"decayed": decayed, "consolidated": consolidated},
            items_processed=decayed,
        )


class BudgetCheckJob(BaseJob):
    """Checks budget limits and generates alerts."""

    name = "budget_check"
    description = "Monitor spending against budget limits"
    interval_seconds = 15 * 60  # 15 minutes
    priority = 2

    def run(self) -> JobResult:
        from core.routing.budget import BudgetManager
        bm = BudgetManager(self.empire_id)
        alerts = bm.get_budget_alerts()
        return JobResult(
            success=True,
            data={
                "daily_spend": bm.get_daily_spend(),
                "monthly_spend": bm.get_monthly_spend(),
                "over_budget": bm.is_over_budget(),
                "alerts": len(alerts),
            },
        )


class CrossEmpireSyncJob(BaseJob):
    """Syncs knowledge between empires."""

    name = "cross_empire_sync"
    description = "Sync knowledge across empire network"
    interval_seconds = 30 * 60  # 30 minutes
    priority = 7

    def run(self) -> JobResult:
        from core.knowledge.bridge import KnowledgeBridge
        bridge = KnowledgeBridge()
        statuses = bridge.get_sync_status(self.empire_id)
        return JobResult(
            success=True,
            data={"sync_count": len(statuses)},
        )


class AutonomousResearchJob(BaseJob):
    """Searches the web for latest AI developments and stores findings."""

    name = "autonomous_research"
    description = "Search web for latest AI news and research"
    interval_seconds = 6 * 3600  # 6 hours
    priority = 7

    # Rotate through AI research topics each run
    RESEARCH_TOPICS = [
        "new AI model release",
        "LLM agent framework",
        "AI safety alignment research",
        "open source LLM",
        "AI infrastructure tooling",
        "AI company funding acquisition",
        "multimodal AI breakthrough",
        "AI benchmark evaluation",
        "fine-tuning technique",
        "AI regulation policy",
    ]

    def __init__(self, empire_id: str = ""):
        super().__init__(empire_id)
        self._topic_index = 0

    def run(self) -> JobResult:
        from core.search.web import WebSearcher
        from core.search.scraper import WebScraper

        searcher = WebSearcher(self.empire_id)
        scraper = WebScraper(self.empire_id)

        # Pick topic for this run (rotates)
        topic = self.RESEARCH_TOPICS[self._topic_index % len(self.RESEARCH_TOPICS)]
        self._topic_index += 1

        # Search for latest news
        news = searcher.search_ai_news(topic, max_results=5)
        if not news.results:
            return JobResult(success=True, data={"topic": topic, "found": 0})

        # Try to scrape — attempt all results, keep what works
        stored = 0
        scraped_titles = []
        for article in news.results:
            if stored >= 2:  # Cap at 2 scraped articles per run
                break
            if article.url:
                result = scraper.scrape_and_store(article.url)
                if result.get("success"):
                    stored += 1
                    scraped_titles.append(result.get("title", ""))

        # Always store news snippets in memory — even if scraping fails
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        news_summary = "\n".join(
            f"- {r.title} ({r.source}): {r.snippet[:200]}"
            for r in news.results
        )
        mm.store(
            content=f"AI News Scan: {topic}\n\n{news_summary}",
            memory_type="semantic",
            title=f"News: {topic}",
            category="auto_research",
            importance=0.6,
            tags=["auto_research", "news", topic.replace(" ", "_")],
            source_type="autonomous",
        )

        return JobResult(
            success=True,
            data={
                "topic": topic,
                "news_found": len(news.results),
                "articles_scraped": stored,
                "snippets_stored": 1,  # Always stores snippet summary
                "titles": scraped_titles,
            },
            items_processed=stored + 1,  # Snippets always count
        )


class DirectiveCheckJob(BaseJob):
    """Checks for pending directives to execute."""

    name = "directive_check"
    description = "Check for pending directives"
    interval_seconds = 5 * 60  # 5 minutes
    priority = 3

    def run(self) -> JobResult:
        from core.directives.manager import DirectiveManager
        dm = DirectiveManager(self.empire_id)
        pending = dm.list_directives(status="pending")
        return JobResult(
            success=True,
            data={"pending_count": len(pending)},
        )


class CleanupJob(BaseJob):
    """Archives old data and cleans up temp files."""

    name = "cleanup"
    description = "Archive old data and cleanup"
    interval_seconds = 24 * 3600  # 24 hours
    priority = 8

    def run(self) -> JobResult:
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        cleanup = mm.cleanup()

        from db.engine import get_session
        from db.repositories.task import TaskRepository
        session = get_session()
        task_repo = TaskRepository(session)
        stale = task_repo.cleanup_stale(hours=48)
        session.commit()

        return JobResult(
            success=True,
            data={**cleanup, "stale_tasks_cleaned": stale},
        )


class IntelligenceSweepJob(BaseJob):
    """Proactive intelligence sweep across AI sources."""

    name = "intelligence_sweep"
    description = "Sweep HuggingFace, GitHub, arXiv, feeds for new AI developments"
    interval_seconds = 12 * 3600  # 12 hours
    priority = 6

    def run(self) -> JobResult:
        from core.search.sweep import IntelligenceSweep
        sweep = IntelligenceSweep(self.empire_id)
        result = sweep.run_full_sweep()
        return JobResult(
            success=True,
            data={
                "sources_checked": result.sources_checked,
                "total_found": result.total_found,
                "novel_items": result.novel_items,
                "stored_memories": result.stored_memories,
                "stored_entities": result.stored_entities,
                "errors": result.errors[:3],
            },
            items_processed=result.novel_items,
        )


class MemoryCompressionJob(BaseJob):
    """Compress old episodic memories into semantic summaries."""

    name = "memory_compression"
    description = "Compress and summarize old memories"
    interval_seconds = 24 * 3600  # 24 hours
    priority = 7

    def run(self) -> JobResult:
        from core.memory.consolidation import MemoryConsolidator
        consolidator = MemoryConsolidator(self.empire_id)
        result = consolidator.run_consolidation()
        return JobResult(
            success=True,
            data={
                "duplicates_merged": result.duplicates_merged,
                "promoted": result.promoted_count,
                "summarized": result.summarized_count,
            },
            items_processed=result.total_processed,
        )


class QualityScoringJob(BaseJob):
    """Score knowledge graph entities for quality."""

    name = "quality_scoring"
    description = "Rate knowledge entities across 8 quality dimensions"
    interval_seconds = 12 * 3600  # 12 hours
    priority = 7

    def run(self) -> JobResult:
        from core.knowledge.quality import EntityQualityScorer
        scorer = EntityQualityScorer(self.empire_id)
        stats = scorer.get_quality_stats()
        return JobResult(
            success=True,
            data=stats,
            items_processed=stats.get("total", 0),
        )


class DuplicateResolutionJob(BaseJob):
    """Find and merge duplicate entities in the knowledge graph."""

    name = "duplicate_resolution"
    description = "Resolve duplicate entities using fuzzy matching"
    interval_seconds = 24 * 3600  # 24 hours
    priority = 8

    def run(self) -> JobResult:
        from core.knowledge.resolution import EntityResolver
        resolver = EntityResolver(self.empire_id)
        duplicates = resolver.find_duplicates()
        merged = 0
        if duplicates:
            merged = resolver.merge_duplicates()
        return JobResult(
            success=True,
            data={"duplicate_groups": len(duplicates), "merged": merged},
            items_processed=merged,
        )


# Job registry
JOB_REGISTRY: dict[str, type[BaseJob]] = {
    "learning_cycle": LearningCycleJob,
    "evolution_cycle": EvolutionCycleJob,
    "health_check": HealthCheckJob,
    "knowledge_maintenance": KnowledgeMaintenanceJob,
    "memory_decay": MemoryDecayJob,
    "budget_check": BudgetCheckJob,
    "cross_empire_sync": CrossEmpireSyncJob,
    "autonomous_research": AutonomousResearchJob,
    "directive_check": DirectiveCheckJob,
    "cleanup": CleanupJob,
    "intelligence_sweep": IntelligenceSweepJob,
    "memory_compression": MemoryCompressionJob,
    "quality_scoring": QualityScoringJob,
    "duplicate_resolution": DuplicateResolutionJob,
}


def get_all_jobs(empire_id: str) -> list[BaseJob]:
    """Get instances of all registered jobs."""
    return [job_class(empire_id) for job_class in JOB_REGISTRY.values()]


def get_job(name: str, empire_id: str) -> BaseJob | None:
    """Get a specific job instance by name."""
    job_class = JOB_REGISTRY.get(name)
    if job_class:
        return job_class(empire_id)
    return None
