"""Health checking system — monitors all Empire subsystems."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HealthCheckResult:
    """Result of a single health check."""
    check_name: str
    status: str = "healthy"  # healthy, unhealthy, unknown
    message: str = ""
    details: dict = field(default_factory=dict)
    response_time_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class HealthReport:
    """Comprehensive health report."""
    overall_status: str = "healthy"
    checks: list[HealthCheckResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    critical_issues: list[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class SystemDashboard:
    """System dashboard data."""
    health: dict = field(default_factory=dict)
    budget: dict = field(default_factory=dict)
    performance: dict = field(default_factory=dict)
    active_tasks: int = 0
    upcoming_jobs: list[dict] = field(default_factory=list)


class HealthChecker:
    """Monitors all Empire subsystems for health issues.

    Runs periodic checks on database, LLM connectivity, budget,
    lieutenant health, scheduler, memory, and knowledge graph.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id

    def run_all_checks(self) -> dict:
        """Run all health checks and produce a report.

        Returns:
            Health report as dict.
        """
        checks = []

        checks.append(self.check_database())
        checks.append(self.check_redis())
        checks.append(self.check_circuit_breakers())
        checks.append(self.check_budget_status())
        checks.append(self.check_lieutenant_health())
        checks.append(self.check_memory_usage())
        checks.append(self.check_knowledge_graph())
        checks.append(self.check_disk_space())

        # Determine overall status
        statuses = [c.status for c in checks]
        if "unhealthy" in statuses:
            overall = "unhealthy"
        elif "unknown" in statuses:
            overall = "unhealthy"  # unknown is not OK — treat as unhealthy upstream
        else:
            overall = "healthy"

        warnings = [c.message for c in checks if c.status == "unknown"]
        critical = [c.message for c in checks if c.status == "unhealthy"]

        report = HealthReport(
            overall_status=overall,
            checks=checks,
            warnings=warnings,
            critical_issues=critical,
        )

        # Persist to database
        self._persist_checks(checks)

        return {
            "overall_status": overall,
            "checks": [
                {"name": c.check_name, "status": c.status, "message": c.message, "time_ms": c.response_time_ms}
                for c in checks
            ],
            "warnings": warnings,
            "critical_issues": critical,
            "timestamp": report.timestamp,
        }

    def check_database(self) -> HealthCheckResult:
        """Check database connectivity and health."""
        start = time.time()
        try:
            from db.engine import check_connection, get_db_stats
            healthy = check_connection()
            response_time = (time.time() - start) * 1000

            if healthy:
                return HealthCheckResult(
                    check_name="database",
                    status="healthy",
                    message="Database connection healthy",
                    response_time_ms=response_time,
                )
            return HealthCheckResult(
                check_name="database",
                status="unhealthy",
                message="Database connection failed",
                response_time_ms=response_time,
            )
        except Exception as e:
            return HealthCheckResult(
                check_name="database",
                status="unhealthy",
                message=f"Database error: {e}",
                response_time_ms=(time.time() - start) * 1000,
            )

    def check_budget_status(self) -> HealthCheckResult:
        """Check budget limits."""
        try:
            from core.routing.budget import BudgetManager
            bm = BudgetManager(self.empire_id)
            daily = bm.get_daily_spend()
            monthly = bm.get_monthly_spend()

            from config.settings import get_settings
            limits = get_settings().budget

            daily_pct = daily / limits.daily_limit_usd * 100 if limits.daily_limit_usd > 0 else 0
            monthly_pct = monthly / limits.monthly_limit_usd * 100 if limits.monthly_limit_usd > 0 else 0

            if daily_pct >= 100 or monthly_pct >= 100:
                return HealthCheckResult(
                    check_name="budget",
                    status="unhealthy",
                    message=f"Budget exceeded: daily {daily_pct:.0f}%, monthly {monthly_pct:.0f}%",
                    details={"daily_spend": daily, "monthly_spend": monthly},
                )
            elif daily_pct >= 80 or monthly_pct >= 80:
                logger.warning("Budget nearing limit: daily %.0f%%, monthly %.0f%%", daily_pct, monthly_pct)
                return HealthCheckResult(
                    check_name="budget",
                    status="healthy",
                    message=f"Budget warning: daily {daily_pct:.0f}%, monthly {monthly_pct:.0f}%",
                    details={"daily_spend": daily, "monthly_spend": monthly, "warning": True},
                )
            return HealthCheckResult(
                check_name="budget",
                status="healthy",
                message=f"Budget OK: daily {daily_pct:.0f}%, monthly {monthly_pct:.0f}%",
                details={"daily_spend": daily, "monthly_spend": monthly},
            )

        except Exception as e:
            logger.error("Budget health check failed: %s", e)
            return HealthCheckResult(
                check_name="budget",
                status="unhealthy",
                message=f"Budget check failed — cannot verify spend: {e}",
            )

    def check_lieutenant_health(self) -> HealthCheckResult:
        """Check lieutenant fleet health."""
        try:
            from db.engine import session_scope
            from db.repositories.lieutenant import LieutenantRepository

            with session_scope() as session:
                repo = LieutenantRepository(session)
                summary = repo.get_fleet_summary(self.empire_id)

            total = summary.get("total_lieutenants", 0)
            active = summary.get("by_status", {}).get("active", 0)
            avg_perf = summary.get("avg_performance", 0)

            if total == 0:
                return HealthCheckResult(
                    check_name="lieutenants",
                    status="unhealthy",
                    message="No lieutenants registered",
                )

            if active == 0:
                return HealthCheckResult(
                    check_name="lieutenants",
                    status="unhealthy",
                    message="No active lieutenants",
                    details={"total": total, "active": active},
                )

            if avg_perf < 0.3:
                logger.warning("Low fleet performance: %.2f", avg_perf)
                return HealthCheckResult(
                    check_name="lieutenants",
                    status="healthy",
                    message=f"Low fleet performance: {avg_perf:.2f}",
                    details={"total": total, "active": active, "avg_performance": avg_perf, "warning": True},
                )

            return HealthCheckResult(
                check_name="lieutenants",
                status="healthy",
                message=f"{active}/{total} active, avg performance {avg_perf:.2f}",
                details={"total": total, "active": active, "avg_performance": avg_perf},
            )

        except Exception as e:
            logger.error("Lieutenant health check failed: %s", e)
            return HealthCheckResult(check_name="lieutenants", status="unhealthy", message=f"Check failed: {e}")

    def check_memory_usage(self) -> HealthCheckResult:
        """Check memory system health."""
        try:
            from core.memory.manager import MemoryManager
            mm = MemoryManager(self.empire_id)
            stats = mm.get_stats()

            total = stats.total_count
            avg_decay = stats.avg_decay

            if total == 0:
                return HealthCheckResult(
                    check_name="memory",
                    status="healthy",
                    message="No memories stored yet",
                )

            if avg_decay < 0.2:
                logger.warning("High memory decay (%.2f), maintenance needed", avg_decay)
                return HealthCheckResult(
                    check_name="memory",
                    status="healthy",
                    message=f"High memory decay ({avg_decay:.2f}), maintenance needed",
                    details={"total": total, "avg_decay": avg_decay, "warning": True},
                )

            return HealthCheckResult(
                check_name="memory",
                status="healthy",
                message=f"{total} memories, avg decay {avg_decay:.2f}",
                details={"total": total, "avg_decay": avg_decay},
            )

        except Exception as e:
            logger.error("Memory health check failed: %s", e)
            return HealthCheckResult(check_name="memory", status="unhealthy", message=f"Check failed: {e}")

    def check_knowledge_graph(self) -> HealthCheckResult:
        """Check knowledge graph health."""
        try:
            from core.knowledge.graph import KnowledgeGraph
            graph = KnowledgeGraph(self.empire_id)
            stats = graph.get_stats()

            return HealthCheckResult(
                check_name="knowledge_graph",
                status="healthy",
                message=f"{stats.entity_count} entities, {stats.relation_count} relations",
                details={
                    "entities": stats.entity_count,
                    "relations": stats.relation_count,
                    "avg_confidence": stats.avg_confidence,
                },
            )

        except Exception as e:
            logger.error("Knowledge graph health check failed: %s", e)
            return HealthCheckResult(check_name="knowledge_graph", status="unhealthy", message=f"Check failed: {e}")

    def check_disk_space(self) -> HealthCheckResult:
        """Check available disk space."""
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            free_gb = free / (1024 ** 3)
            used_pct = used / total * 100

            if free_gb < 1.0:
                return HealthCheckResult(
                    check_name="disk_space",
                    status="unhealthy",
                    message=f"Low disk space: {free_gb:.1f}GB free",
                    details={"free_gb": free_gb, "used_percent": used_pct},
                )
            elif free_gb < 5.0:
                logger.warning("Low disk space: %.1fGB free", free_gb)
                return HealthCheckResult(
                    check_name="disk_space",
                    status="healthy",
                    message=f"Disk space warning: {free_gb:.1f}GB free",
                    details={"free_gb": free_gb, "used_percent": used_pct, "warning": True},
                )
            return HealthCheckResult(
                check_name="disk_space",
                status="healthy",
                message=f"{free_gb:.1f}GB free",
                details={"free_gb": free_gb, "used_percent": used_pct},
            )

        except Exception as e:
            logger.error("Disk space health check failed: %s", e)
            return HealthCheckResult(check_name="disk_space", status="unhealthy", message=f"Check failed: {e}")

    def get_system_dashboard(self) -> SystemDashboard:
        """Get comprehensive system dashboard data."""
        health_report = self.run_all_checks()

        return SystemDashboard(
            health=health_report,
            active_tasks=0,
        )

    def check_redis(self) -> HealthCheckResult:
        """Check Redis connectivity and LLM cache stats."""
        start = time.time()
        try:
            from llm.cache import get_cache
            cache = get_cache()
            response_time = (time.time() - start) * 1000

            if not cache.enabled:
                return HealthCheckResult(
                    check_name="redis",
                    status="healthy",
                    message="Redis disabled — LLM cache inactive",
                    response_time_ms=response_time,
                    details={**cache.get_stats(), "warning": True},
                )

            stats = cache.get_stats()
            return HealthCheckResult(
                check_name="redis",
                status="healthy",
                message=f"Redis connected — {stats['hits']} hits, {stats['hit_rate']:.0%} rate, ~${stats['estimated_savings_usd']:.2f} saved",
                response_time_ms=response_time,
                details=stats,
            )
        except Exception as e:
            logger.error("Redis health check failed: %s", e)
            return HealthCheckResult(
                check_name="redis",
                status="unhealthy",
                message=f"Redis check failed: {e}",
                response_time_ms=(time.time() - start) * 1000,
            )

    def check_circuit_breakers(self) -> HealthCheckResult:
        """Check circuit breaker states for LLM providers."""
        try:
            from utils.circuit_breaker import get_all_circuit_stats

            stats = get_all_circuit_stats()
            if not stats:
                return HealthCheckResult(
                    check_name="circuit_breakers",
                    status="healthy",
                    message="No circuits initialized yet",
                    details={},
                )

            open_circuits = [
                name for name, info in stats.items()
                if info.get("state") == "open"
            ]

            if open_circuits:
                return HealthCheckResult(
                    check_name="circuit_breakers",
                    status="unhealthy",
                    message=f"Open circuits: {', '.join(open_circuits)}",
                    details=stats,
                )

            return HealthCheckResult(
                check_name="circuit_breakers",
                status="healthy",
                message=f"{len(stats)} circuit(s), all closed",
                details=stats,
            )
        except Exception as e:
            logger.error("Circuit breaker health check failed: %s", e)
            return HealthCheckResult(
                check_name="circuit_breakers",
                status="unhealthy",
                message=f"Circuit breaker check failed: {e}",
            )

    def _persist_checks(self, checks: list[HealthCheckResult]) -> None:
        """Save health check results to database."""
        try:
            from db.engine import session_scope
            from db.models import HealthCheck as HealthCheckModel

            with session_scope() as session:
                for check in checks:
                    hc = HealthCheckModel(
                        empire_id=self.empire_id,
                        check_type=check.check_name,
                        status=check.status,
                        message=check.message,
                        details_json=check.details,
                        response_time_ms=check.response_time_ms,
                    )
                    session.add(hc)
        except Exception as e:
            logger.warning("Failed to persist health checks: %s", e)
