"""Scheduler daemon — the 60-second tick that drives everything autonomously."""

from __future__ import annotations

import logging
import signal
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class JobConfig:
    """Configuration for a scheduled job."""
    name: str
    job_type: str
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
        except Exception:
            # Use defaults
            class DefaultScheduler:
                health_check_interval_minutes = 5
                learning_cycle_hours = 6
                evolution_cycle_hours = 12
                knowledge_maintenance_hours = 4
            s = DefaultScheduler()

        self.register_job(JobConfig(
            name="health_check",
            job_type="health_check",
            interval_seconds=s.health_check_interval_minutes * 60,
            handler=self._run_health_check,
            priority=1,
            description="System health checks",
        ))

        self.register_job(JobConfig(
            name="memory_decay",
            job_type="memory_decay",
            interval_seconds=3600,  # 1 hour
            handler=self._run_memory_decay,
            priority=3,
            description="Apply memory decay",
        ))

        self.register_job(JobConfig(
            name="knowledge_maintenance",
            job_type="knowledge_maintenance",
            interval_seconds=s.knowledge_maintenance_hours * 3600,
            handler=self._run_knowledge_maintenance,
            priority=4,
            description="Knowledge graph maintenance",
        ))

        self.register_job(JobConfig(
            name="learning_cycle",
            job_type="learning_cycle",
            interval_seconds=s.learning_cycle_hours * 3600,
            handler=self._run_learning_cycle,
            priority=5,
            description="Lieutenant learning cycles",
        ))

        self.register_job(JobConfig(
            name="evolution_cycle",
            job_type="evolution_cycle",
            interval_seconds=s.evolution_cycle_hours * 3600,
            handler=self._run_evolution_cycle,
            priority=6,
            description="Self-improvement evolution cycle",
        ))

        self.register_job(JobConfig(
            name="budget_check",
            job_type="budget_check",
            interval_seconds=900,  # 15 minutes
            handler=self._run_budget_check,
            priority=2,
            description="Budget limit checking",
        ))

        self.register_job(JobConfig(
            name="directive_check",
            job_type="directive_check",
            interval_seconds=300,  # 5 minutes
            handler=self._run_directive_check,
            priority=3,
            description="Check for pending directives",
        ))

        self.register_job(JobConfig(
            name="cleanup",
            job_type="cleanup",
            interval_seconds=86400,  # 24 hours
            handler=self._run_cleanup,
            priority=8,
            description="Archive and cleanup old data",
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

    def start(self) -> None:
        """Start the scheduler daemon in a background thread."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._start_time = time.time()
        self._stop_event.clear()

        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="empire-scheduler")
        self._thread.start()

        logger.info("Scheduler daemon started (tick_interval=%ds, jobs=%d)", self.tick_interval, len(self._jobs))

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

    def _try_acquire_tick_lock(self) -> bool:
        """Try to acquire a Postgres advisory lock for this tick.

        Returns True if this worker should run the tick.
        On SQLite or connection failure, always returns True.
        """
        try:
            from db.engine import get_engine
            engine = get_engine()
            if "postgresql" not in str(engine.url):
                return True
            from sqlalchemy import text
            with engine.connect() as conn:
                result = conn.execute(text("SELECT pg_try_advisory_lock(42)"))
                acquired = result.scalar()
                if acquired:
                    conn.execute(text("SELECT pg_advisory_unlock(42)"))
                return bool(acquired)
        except Exception:
            return True

    def tick(self) -> list[str]:
        """Execute a single scheduler tick.

        Uses Postgres advisory lock so only one worker runs jobs per tick.

        Returns:
            List of job names that were executed.
        """
        if not self._try_acquire_tick_lock():
            return []

        self._tick_count += 1
        now = datetime.now(timezone.utc)
        executed = []

        # Sort jobs by priority
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.priority)

        for job in jobs:
            if not job.enabled:
                continue

            # Check if job is due
            if job.last_run is None or (now - job.last_run).total_seconds() >= job.interval_seconds:
                try:
                    start = time.time()
                    result = job.handler()
                    duration_ms = (time.time() - start) * 1000

                    job.last_run = now
                    job.run_count += 1
                    job.consecutive_errors = 0
                    job.avg_duration_ms = (job.avg_duration_ms * 0.9 + duration_ms * 0.1) if job.avg_duration_ms else duration_ms
                    self._total_job_runs += 1
                    executed.append(job.name)

                    logger.debug("Job %s completed in %.1fms", job.name, duration_ms)

                except Exception as e:
                    job.error_count += 1
                    job.consecutive_errors += 1
                    job.last_error = str(e)
                    self._total_errors += 1
                    logger.error("Job %s failed: %s", job.name, e)

                    # Disable job after 20 consecutive errors (auto-re-enables after 10 ticks)
                    if job.consecutive_errors >= 20:
                        job.enabled = False
                        job.metadata_json = job.metadata_json or {}
                        job.metadata_json["disabled_at_tick"] = self._tick_count
                        logger.warning("Job %s disabled after %d consecutive errors", job.name, job.consecutive_errors)

            # Auto-re-enable disabled jobs after 10 ticks (~50 min)
            for job in self._jobs.values():
                if not job.enabled:
                    meta = getattr(job, "metadata_json", None) or {}
                    disabled_at = meta.get("disabled_at_tick", 0)
                    if self._tick_count - disabled_at >= 10:
                        job.enabled = True
                        job.consecutive_errors = 0
                        logger.info("Job %s auto-re-enabled after cooldown", job.name)

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

    def _run_learning_cycle(self) -> dict:
        """Run lieutenant learning cycles."""
        from core.lieutenant.manager import LieutenantManager
        manager = LieutenantManager(self.empire_id)
        return manager.run_all_learning_cycles()

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
