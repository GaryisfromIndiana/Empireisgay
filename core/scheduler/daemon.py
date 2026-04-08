"""Scheduler daemon — the 60-second tick that drives everything autonomously."""

from __future__ import annotations

import logging
import signal
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Optional

from core.errors import TransientError, ConfigError, FatalError

logger = logging.getLogger(__name__)


@dataclass
class JobConfig:
    """Configuration for a scheduled job."""
    name: str
    interval_seconds: int
    handler: Callable[[], dict]
    enabled: bool = True
    priority: int = 5  # 1 = highest
    description: str = ""
    last_run: Optional[datetime] = None
    run_count: int = 0
    error_count: int = 0
    consecutive_errors: int = 0
    last_error: str = ""
    avg_duration_ms: float = 0.0
    metadata_json: dict = field(default_factory=dict)

    @property
    def job_type(self) -> str:
        return self.name


@dataclass
class DaemonStatus:
    """Status of the scheduler daemon."""
    running: bool = False
    uptime_seconds: float = 0.0
    jobs_registered: int = 0
    jobs_active: int = 0
    last_tick: str = ""
    total_ticks: int = 0
    total_job_runs: int = 0
    errors: int = 0


@dataclass
class ScheduledRun:
    """Information about a scheduled job run."""
    job_name: str
    next_run: str
    interval_seconds: int
    last_run: str = ""
    status: str = "pending"


class SchedulerDaemon:
    """The autonomous scheduler daemon.

    Ticks every 60 seconds (configurable), checking which jobs are due
    and executing them. Drives learning cycles, evolution runs,
    health checks, and knowledge maintenance without human intervention.
    """

    def __init__(self, empire_id: str = "", tick_interval: int = 60):
        self.empire_id = empire_id
        self.tick_interval = tick_interval
        self._jobs: dict[str, JobConfig] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._start_time: Optional[float] = None
        self._tick_count = 0
        self._total_job_runs = 0
        self._total_errors = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Register default jobs
        self._register_default_jobs()

    def _register_default_jobs(self) -> None:
        """Register the default set of recurring jobs."""
        try:
            from config.settings import get_settings
            s = get_settings().scheduler
        except Exception as e:
            logger.error("Scheduler settings load failed, using defaults: %s", e)
            class DefaultScheduler:
                health_check_interval_minutes = 5
                learning_cycle_hours = 6
                evolution_cycle_hours = 12
                knowledge_maintenance_hours = 4
            s = DefaultScheduler()

        # (name, interval_seconds, priority, description)
        #
        # Jobs are categorized by what they produce:
        #   INFRASTRUCTURE — keeps the system healthy (no API cost)
        #   RESEARCH       — discovers new information (API cost, produces knowledge)
        #   MAINTENANCE    — improves existing knowledge quality (some API cost)
        #
        # CUT: learning_cycle (lieutenants are cosmetic — same engine, different prompt)
        # CUT: autonomous_warroom (sequential summarization, not real debate — expensive theater)
        # CUT: auto_spawn (spawns more cosmetic lieutenants)
        # CUT: cross_synthesis (overlaps with research pipeline, no unique output)
        # CUT: shallow_enrichment (LLM-rewrites entity descriptions — low signal, high cost)
        # CUT: content_generation (no audience defined — generate reports on demand instead)
        #
        jobs = [
            # ── Infrastructure (no API cost) ─────────────────────────
            ("health_check",         s.health_check_interval_minutes * 60, 1, "System health checks"),
            ("budget_check",         900,                                  2, "Budget limit checking"),
            ("directive_check",      300,                                  3, "Check for pending directives"),
            ("stale_task_cleanup",   900,                                  2, "Fail tasks stuck in executing > 30 min"),
            ("memory_decay",         3600,                                 3, "Apply memory decay"),
            ("cleanup",              86400,                                3, "Retention policy enforcement"),
            ("embedding_backfill",   3600,                                 4, "Backfill embeddings for vector search"),
            ("duplicate_resolution", 14400,                                5, "3-stage fuzzy entity deduplication"),
            # ── Research (API cost → new knowledge) ──────────────────
            ("intelligence_sweep",   43200,                                4, "Proactive discovery across AI sources"),
            ("autonomous_research",  21600,                                4, "Gap-driven autonomous research"),
            ("iterative_deepening",  28800,                                6, "Deepen high-signal shallow research"),
            # ── Quality (some API cost → better knowledge) ───────────
            ("knowledge_maintenance", s.knowledge_maintenance_hours * 3600, 4, "Knowledge graph maintenance"),
            ("quality_scoring",      21600,                                5, "8-dimension entity quality scoring"),
            ("llm_audit",            43200,                                6, "Deep LLM audit for contaminated entities"),
            ("memory_compression",   43200,                                6, "LLM-powered memory compression"),
            ("evolution_cycle",      s.evolution_cycle_hours * 3600,        7, "Self-improvement evolution cycle"),
        ]

        for name, interval, priority, description in jobs:
            handler = getattr(self, f"_run_{name}", None)
            if not handler:
                logger.error("Scheduler job '%s' has no handler method _run_%s", name, name)
                continue
            self.register_job(JobConfig(
                name=name, interval_seconds=interval, handler=handler,
                priority=priority, description=description,
            ))

    def register_job(self, job: JobConfig) -> None:
        """Register a recurring job."""
        with self._lock:
            self._jobs[job.name] = job
        logger.debug("Registered job: %s (interval=%ds)", job.name, job.interval_seconds)

    def unregister_job(self, job_name: str) -> None:
        """Unregister a job."""
        with self._lock:
            self._jobs.pop(job_name, None)

    def _sync_from_db(self) -> int:
        """Load persisted job state from the scheduler_jobs table.

        Restores last_run, run_count, error_count so the daemon resumes
        where it left off after a process restart instead of re-running everything.

        Returns number of jobs synced.
        """
        synced = 0
        try:
            from db.engine import session_scope
            from db.models import SchedulerJob
            from sqlalchemy import select, and_

            with session_scope() as session:
                stmt = select(SchedulerJob).where(SchedulerJob.empire_id == self.empire_id)
                db_jobs = {j.job_type: j for j in session.execute(stmt).scalars().all()}

                with self._lock:
                    for job in self._jobs.values():
                        db_job = db_jobs.get(job.job_type)
                        if db_job and db_job.last_run_at:
                            # SQLite strips tzinfo — coerce to UTC so tick
                            # math with datetime.now(timezone.utc) works.
                            last_run = db_job.last_run_at
                            if last_run.tzinfo is None:
                                last_run = last_run.replace(tzinfo=timezone.utc)
                            job.last_run = last_run
                            job.run_count = db_job.run_count or 0
                            job.error_count = db_job.error_count or 0
                            job.consecutive_errors = db_job.consecutive_errors or 0
                            job.enabled = db_job.enabled
                            synced += 1

            if synced:
                logger.info("Synced %d jobs from DB — resuming from last known state", synced)
        except Exception as e:
            logger.error("DB sync on startup failed — job state may be lost: %s", e)
        return synced

    def _sync_to_db(self) -> None:
        """Persist current job state to the scheduler_jobs table.

        Uses a single session for all jobs to avoid pool exhaustion.
        Per-row savepoints so one IntegrityError (race with another worker)
        doesn't roll back the entire batch.
        """
        from db.engine import session_scope
        from db.models import SchedulerJob
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError

        with self._lock:
            snapshot = list(self._jobs.values())

        persisted = 0
        try:
            with session_scope() as session:
                for job in snapshot:
                    try:
                        savepoint = session.begin_nested()
                        existing = session.execute(
                            select(SchedulerJob).where(
                                SchedulerJob.empire_id == self.empire_id,
                                SchedulerJob.job_type == job.job_type,
                            )
                        ).scalar_one_or_none()

                        next_run = None
                        if job.last_run:
                            next_run = job.last_run + timedelta(seconds=job.interval_seconds)

                        if existing:
                            existing.last_run_at = job.last_run
                            existing.next_run_at = next_run
                            existing.run_count = job.run_count
                            existing.success_count = job.run_count - job.error_count
                            existing.error_count = job.error_count
                            existing.consecutive_errors = job.consecutive_errors
                            existing.last_error = job.last_error or None
                            existing.avg_duration_ms = job.avg_duration_ms or None
                            existing.enabled = job.enabled
                            existing.status = "active" if job.enabled else "disabled"
                        else:
                            session.add(SchedulerJob(
                                empire_id=self.empire_id,
                                job_type=job.job_type,
                                name=job.name,
                                description=job.description,
                                status="active" if job.enabled else "disabled",
                                enabled=job.enabled,
                                interval_seconds=job.interval_seconds,
                                priority=job.priority,
                                last_run_at=job.last_run,
                                next_run_at=next_run,
                                run_count=job.run_count,
                                success_count=job.run_count - job.error_count,
                                error_count=job.error_count,
                                consecutive_errors=job.consecutive_errors,
                                last_error=job.last_error or None,
                                avg_duration_ms=job.avg_duration_ms or None,
                            ))

                        savepoint.commit()
                        persisted += 1
                    except IntegrityError:
                        savepoint.rollback()
                    except Exception as e:
                        savepoint.rollback()
                        logger.error("Failed to persist scheduler job %s: %s", job.job_type, e)
        except Exception as e:
            logger.error("Failed to sync scheduler jobs to DB: %s", e)

        if persisted:
            logger.debug("Persisted %d/%d scheduler jobs", persisted, len(snapshot))

    def start(self) -> None:
        """Start the scheduler daemon in a background thread.

        On startup, syncs job state from the DB so the daemon resumes where
        it left off after a process restart. Only staggers jobs if this is a
        fresh start (no DB state).
        """
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._start_time = time.time()
        self._stop_event.clear()

        # Try to restore job state from DB (survives process restarts)
        synced = self._sync_from_db()

        # Stagger expensive jobs on startup regardless of whether this is a
        # fresh start or a restore.  If the previous worker was OOM-killed
        # mid-tick, its last_run never persisted, so _sync_from_db will show
        # many jobs as "overdue" and they'll all fire on tick 0 — which is
        # exactly how you get an OOM death spiral across every restart.
        # Push high-priority (expensive) jobs forward by their interval so
        # the new worker warms up before touching them.
        now = datetime.now(timezone.utc)
        immediate_jobs = {"health_check", "budget_check", "directive_check"}
        with self._lock:
            for job in self._jobs.values():
                if job.name in immediate_jobs:
                    continue
                # If last_run is stale (>interval ago) OR None, defer it to
                # now so tick 0 doesn't fire every overdue job simultaneously.
                if job.last_run is None:
                    job.last_run = now
                elif (now - job.last_run).total_seconds() >= job.interval_seconds:
                    job.last_run = now

        # Persist job registry IMMEDIATELY, before any tick runs.  Previously
        # sync only fired after a successful tick, so if the process died
        # before any job executed, scheduler_jobs stayed empty forever.
        self._sync_to_db()

        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="empire-scheduler")
        self._thread.start()

        logger.info("Scheduler daemon started (tick_interval=%ds, jobs=%d, synced=%d)", self.tick_interval, len(self._jobs), synced)

    def stop(self) -> None:
        """Stop the scheduler daemon gracefully."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

        logger.info("Scheduler daemon stopped")

    def _run_loop(self) -> None:
        """Main scheduler loop — runs until stopped."""
        while self._running and not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                logger.error("Scheduler tick error: %s", e)
                self._total_errors += 1

            self._stop_event.wait(timeout=self.tick_interval)

    def _acquire_tick_lock(self):
        """Try to acquire a Postgres advisory lock for this tick.

        Returns (conn, True) if this worker is leader, (None, False) if
        another worker holds the lock, (None, True) if no Postgres (no
        mutex needed — SQLite, tests, etc).

        Caller MUST call _release_tick_lock(conn) in a finally block.
        Previously the lock was acquired and released in the same call,
        giving zero mutual exclusion during the actual tick work.
        """
        try:
            from db.engine import get_engine
            from sqlalchemy import text
            engine = get_engine()
            if "postgresql" not in str(engine.url):
                return None, True
            conn = engine.connect()
            try:
                result = conn.execute(text("SELECT pg_try_advisory_lock(42)"))
                acquired = bool(result.scalar())
            except Exception as e:
                conn.close()
                logger.warning("Advisory lock query failed, proceeding without mutex: %s", e)
                return None, True
            if not acquired:
                conn.close()
                return None, False
            return conn, True
        except Exception as e:
            logger.warning("Advisory lock setup failed, proceeding without mutex: %s", e)
            return None, True

    def _release_tick_lock(self, conn) -> None:
        """Release the advisory lock held by _acquire_tick_lock."""
        if conn is None:
            return
        try:
            from sqlalchemy import text
            conn.execute(text("SELECT pg_advisory_unlock(42)"))
        except Exception as e:
            logger.warning("Advisory lock release failed: %s", e)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def tick(self) -> list[str]:
        """Execute a single scheduler tick.

        Holds a Postgres advisory lock for the whole tick so only one
        worker executes jobs at a time. Returns empty list if another
        worker already holds the lock.
        """
        conn, is_leader = self._acquire_tick_lock()
        if not is_leader:
            return []
        try:
            return self._do_tick()
        finally:
            self._release_tick_lock(conn)

    def _do_tick(self) -> list[str]:

        with self._lock:
            self._tick_count += 1
        now = datetime.now(timezone.utc)
        executed = []

        # Sort jobs by priority
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.priority)

        for job in jobs:
            with self._lock:
                if not job.enabled:
                    continue

                # Check if job is due
                if job.last_run is not None and (now - job.last_run).total_seconds() < job.interval_seconds:
                    continue

            # Run handler WITHOUT lock (can be slow)
            try:
                start = time.time()
                result = job.handler()
                duration_ms = (time.time() - start) * 1000

                with self._lock:
                    job.last_run = now
                    job.run_count += 1
                    job.consecutive_errors = 0
                    job.avg_duration_ms = (job.avg_duration_ms * 0.9 + duration_ms * 0.1) if job.avg_duration_ms else duration_ms
                    self._total_job_runs += 1
                executed.append(job.name)

                logger.debug("Job %s completed in %.1fms", job.name, duration_ms)

            except TransientError as e:
                # Self-healing — don't count toward consecutive errors
                with self._lock:
                    job.error_count += 1
                    job.last_error = str(e)
                    self._total_errors += 1
                logger.warning("Job %s transient failure (will retry): %s", job.name, e)

            except ConfigError as e:
                # Permanent until human fixes — disable this job
                with self._lock:
                    job.error_count += 1
                    job.consecutive_errors += 1
                    job.last_error = str(e)
                    job.enabled = False
                    job.metadata_json = job.metadata_json or {}
                    job.metadata_json["disabled_reason"] = "config_error"
                    self._total_errors += 1
                logger.error("Job %s disabled — config error: %s", job.name, e)

            except FatalError as e:
                # System-wide problem — disable all expensive jobs
                with self._lock:
                    job.error_count += 1
                    job.last_error = str(e)
                    self._total_errors += 1
                    for j in self._jobs.values():
                        if j.priority >= 4:  # research + quality jobs
                            j.enabled = False
                            j.metadata_json = j.metadata_json or {}
                            j.metadata_json["disabled_reason"] = "fatal_error"
                            j.metadata_json["disabled_at_tick"] = self._tick_count
                logger.critical("Job %s fatal error — all expensive jobs disabled: %s", job.name, e)

            except Exception as e:
                with self._lock:
                    job.error_count += 1
                    job.consecutive_errors += 1
                    job.last_error = str(e)
                    self._total_errors += 1
                logger.error("Job %s failed (unclassified): %s", job.name, e, exc_info=True)

                with self._lock:
                    if job.consecutive_errors >= 20:
                        job.enabled = False
                        job.metadata_json = job.metadata_json or {}
                        job.metadata_json["disabled_at_tick"] = self._tick_count
                        logger.error("Job %s disabled after %d consecutive errors", job.name, job.consecutive_errors)

        # Auto-re-enable disabled jobs after 10 ticks (~10 min)
        # EXCEPT config errors — those need a human fix, not a timer
        with self._lock:
            for job in self._jobs.values():
                if not job.enabled:
                    meta = getattr(job, "metadata_json", None) or {}
                    reason = meta.get("disabled_reason", "")
                    if reason in ("config_error", "fatal_error"):
                        continue  # don't auto-re-enable — needs human intervention
                    disabled_at = meta.get("disabled_at_tick", 0)
                    if self._tick_count - disabled_at >= 10:
                        job.enabled = True
                        job.consecutive_errors = 0
                        logger.info("Job %s auto-re-enabled after cooldown", job.name)

        # Persist job state every tick — not just when jobs ran.  Even an
        # idle tick bumps metadata (tick_count, consecutive_errors cooldown),
        # and this is the only place "no jobs ran" state gets a chance to
        # survive a restart.
        self._sync_to_db()

        return executed

    def force_run(self, job_name: str) -> dict:
        """Immediately run a specific job."""
        with self._lock:
            job = self._jobs.get(job_name)

        if not job:
            return {"error": f"Job not found: {job_name}"}

        try:
            start = time.time()
            result = job.handler()
            duration = time.time() - start
            with self._lock:
                job.last_run = datetime.now(timezone.utc)
                job.run_count += 1
            return {"job": job_name, "duration_seconds": duration, "result": result}
        except Exception as e:
            return {"job": job_name, "error": str(e)}

    def pause_job(self, job_name: str) -> bool:
        """Pause a job."""
        with self._lock:
            if job_name in self._jobs:
                self._jobs[job_name].enabled = False
                return True
        return False

    def resume_job(self, job_name: str) -> bool:
        """Resume a paused job."""
        with self._lock:
            if job_name in self._jobs:
                self._jobs[job_name].enabled = True
                self._jobs[job_name].consecutive_errors = 0
                return True
        return False

    def get_status(self) -> DaemonStatus:
        """Get daemon status."""
        uptime = time.time() - self._start_time if self._start_time else 0
        with self._lock:
            active_jobs = sum(1 for j in self._jobs.values() if j.enabled)

        return DaemonStatus(
            running=self._running,
            uptime_seconds=uptime,
            jobs_registered=len(self._jobs),
            jobs_active=active_jobs,
            last_tick=datetime.now(timezone.utc).isoformat(),
            total_ticks=self._tick_count,
            total_job_runs=self._total_job_runs,
            errors=self._total_errors,
        )

    def get_next_runs(self) -> list[ScheduledRun]:
        """Get upcoming scheduled runs."""
        runs = []
        now = datetime.now(timezone.utc)

        with self._lock:
            for job in self._jobs.values():
                if not job.enabled:
                    continue

                if job.last_run:
                    next_run = job.last_run + timedelta(seconds=job.interval_seconds)
                else:
                    next_run = now

                runs.append(ScheduledRun(
                    job_name=job.name,
                    next_run=next_run.isoformat(),
                    interval_seconds=job.interval_seconds,
                    last_run=job.last_run.isoformat() if job.last_run else "",
                    status="active" if job.enabled else "paused",
                ))

        runs.sort(key=lambda r: r.next_run)
        return runs

    def get_job_status(self, job_name: str) -> dict:
        """Get status of a specific job."""
        with self._lock:
            job = self._jobs.get(job_name)
            if not job:
                return {"error": "Job not found"}
            return {
                "name": job.name,
                "type": job.job_type,
                "enabled": job.enabled,
                "interval_seconds": job.interval_seconds,
                "run_count": job.run_count,
                "error_count": job.error_count,
                "consecutive_errors": job.consecutive_errors,
                "last_run": job.last_run.isoformat() if job.last_run else None,
                "last_error": job.last_error,
                "avg_duration_ms": job.avg_duration_ms,
            }

    # ── Job handlers ───────────────────────────────────────────────────

    def _run_stale_task_cleanup(self) -> dict:
        """Fail tasks stuck in 'executing' for > 30 minutes.

        Prevents ghost rows from accumulating when a worker dies mid-research
        or _complete_task throws. The TaskRepository.cleanup_stale method
        already exists — this just wires it into the scheduler.
        """
        from db.engine import repo_scope
        from db.repositories.task import TaskRepository

        with repo_scope(TaskRepository) as repo:
            # cleanup_stale marks 'executing' tasks older than N hours as failed.
            # We use a tighter window (0.5h) than the default (24h) because
            # research tasks should complete in minutes, not hours.
            from datetime import timedelta
            from sqlalchemy import and_, update
            from db.models import Task

            threshold = datetime.now(timezone.utc) - timedelta(minutes=30)
            stmt = (
                update(Task)
                .where(and_(
                    Task.status == "executing",
                    Task.started_at < threshold,
                ))
                .values(
                    status="failed",
                    last_error="Stuck in executing > 30 min — auto-cleaned by scheduler",
                    completed_at=datetime.now(timezone.utc),
                )
            )
            result = repo.session.execute(stmt)
            cleaned = result.rowcount
            repo.commit()

        if cleaned > 0:
            logger.warning("Stale task cleanup: failed %d stuck tasks", cleaned)
        return {"cleaned": cleaned}

    def _run_health_check(self) -> dict:
        """Run system health checks."""
        from core.scheduler.health import HealthChecker
        checker = HealthChecker(self.empire_id)
        report = checker.run_all_checks()
        return {"status": report.get("overall_status", "unknown"), "checks": len(report.get("checks", []))}

    def _run_memory_decay(self) -> dict:
        """Apply memory decay."""
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        decayed = mm.decay()
        return {"decayed": decayed}

    def _run_knowledge_maintenance(self) -> dict:
        """Run knowledge maintenance."""
        from core.knowledge.maintenance import KnowledgeMaintainer
        maintainer = KnowledgeMaintainer(self.empire_id)
        report = maintainer.run_maintenance()
        return {"health_score": report.health_score, "entities": report.entity_count}

    def _run_evolution_cycle(self) -> dict:
        """Run evolution cycle."""
        from core.evolution.cycle import EvolutionCycleManager
        ecm = EvolutionCycleManager(self.empire_id)
        if ecm.should_run_cycle():
            result = ecm.run_full_cycle()
            return {"proposals": result.proposals_collected, "applied": result.applied}
        return {"skipped": True, "reason": "cooldown"}

    def _run_budget_check(self) -> dict:
        """Check budget limits."""
        from core.routing.budget import BudgetManager
        bm = BudgetManager(self.empire_id)
        return {
            "daily_spend": bm.get_daily_spend(),
            "monthly_spend": bm.get_monthly_spend(),
            "over_budget": bm.is_over_budget(),
        }

    def _run_directive_check(self) -> dict:
        """Check for pending directives."""
        from core.directives.manager import DirectiveManager
        dm = DirectiveManager(self.empire_id)
        pending = dm.list_directives(status="pending")
        return {"pending_count": len(pending)}

    def _run_cleanup(self) -> dict:
        """Archive old data and cleanup."""
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)
        cleanup = mm.cleanup()
        return cleanup

    def _run_intelligence_sweep(self) -> dict:
        """Proactive discovery across AI sources."""
        try:
            from core.search.sweep import IntelligenceSweep
            sweep = IntelligenceSweep(self.empire_id)
            result = sweep.run_full_sweep()
            return {
                "total_found": result.total_found,
                "novel_items": result.novel_items,
                "stored_memories": result.stored_memories,
                "stored_entities": result.stored_entities,
                "errors": result.errors[:3],
            }
        except Exception as e:
            logger.error("Intelligence sweep failed: %s", e)
            return {"error": str(e)}

    def _run_quality_scoring(self) -> dict:
        """Score entity quality across 8 dimensions."""
        try:
            from core.knowledge.quality import EntityQualityScorer
            scorer = EntityQualityScorer(self.empire_id)
            scored = scorer.score_all()
            return {"scored": scored}
        except Exception as e:
            logger.warning("Quality scoring failed: %s", e)
            return {"error": str(e)}

    def _run_duplicate_resolution(self) -> dict:
        """3-stage fuzzy entity deduplication."""
        try:
            from core.knowledge.resolution import EntityResolver
            resolver = EntityResolver(self.empire_id)
            merged = resolver.merge_duplicates()
            return {"merged": merged}
        except Exception as e:
            logger.error("Duplicate resolution failed: %s", e)
            return {"error": str(e)}

    def _run_memory_compression(self) -> dict:
        """LLM-powered memory compression."""
        try:
            from core.memory.compression import MemoryCompressor
            compressor = MemoryCompressor(self.empire_id)
            result = compressor.run_compression()
            return {
                "clusters_found": result.clusters_found,
                "clusters_compressed": result.clusters_compressed,
                "memories_consumed": result.memories_consumed,
                "compression_ratio": result.compression_ratio,
                "cost_usd": result.cost_usd,
            }
        except Exception as e:
            logger.error("Memory compression failed: %s", e)
            return {"error": str(e)}

    def _run_autonomous_research(self) -> dict:
        """Closed-loop autonomous research via AutoResearcher.

        Full pipeline: detect gaps → generate questions → search → scrape →
        extract entities → synthesize → update strategy tracker.
        """
        try:
            from core.research.autoresearcher import AutoResearcher

            researcher = AutoResearcher(self.empire_id)
            result = researcher.run_cycle()

            return {
                "cycle_id": result.cycle_id,
                "gaps_detected": result.gaps_detected,
                "questions_generated": result.questions_generated,
                "questions_researched": result.questions_researched,
                "total_findings": result.total_findings,
                "novel_findings": result.novel_findings,
                "entities_extracted": result.entities_extracted,
                "memories_stored": result.memories_stored,
                "synthesis_reports": result.synthesis_reports,
                "domains_covered": result.domains_covered,
                "cost_usd": result.total_cost_usd,
                "duration_seconds": result.duration_seconds,
                "errors": result.errors[:5],
            }
        except Exception as e:
            logger.warning("Autonomous research failed: %s", e)
            return {"error": str(e)}

    def _run_llm_audit(self) -> dict:
        """Deep LLM audit for contaminated/hallucinated entities."""
        try:
            from core.knowledge.maintenance import KnowledgeMaintainer
            maintainer = KnowledgeMaintainer(self.empire_id)
            return maintainer.deep_llm_audit(batch_size=20)
        except Exception as e:
            logger.warning("LLM audit failed: %s", e)
            return {"error": str(e)}

    def _run_iterative_deepening(self) -> dict:
        """Detect high-signal topics and deepen research."""
        try:
            from core.research.deepening import IterativeDeepener
            deepener = IterativeDeepener(self.empire_id)
            results = deepener.run_deepening_cycle(max_topics=3)
            return {
                "topics_deepened": len(results),
                "new_entities": sum(r.new_entities for r in results),
                "new_relations": sum(r.new_relations for r in results),
                "topics": [r.topic for r in results],
            }
        except Exception as e:
            logger.warning("Iterative deepening failed: %s", e)
            return {"error": str(e)}

    def _run_embedding_backfill(self) -> dict:
        """Backfill embeddings for memories and KG entities that lack them."""
        from core.memory.embeddings import backfill_embeddings
        return backfill_embeddings(self.empire_id)
