"""Lieutenant-specific repository with domain queries and performance tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import select, func, and_, desc, case

from db.models import Lieutenant, Task, MemoryEntry, BudgetLog
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class LieutenantRepository(BaseRepository[Lieutenant]):
    """Repository for Lieutenant entities with specialized queries."""

    model_class = Lieutenant

    def get_by_empire(
        self,
        empire_id: str,
        status: str | None = None,
        domain: str | None = None,
        limit: int = 100,
    ) -> list[Lieutenant]:
        """Get lieutenants for an empire with optional filters.

        Args:
            empire_id: Empire ID.
            status: Optional status filter.
            domain: Optional domain filter.
            limit: Maximum results.

        Returns:
            List of lieutenants.
        """
        filters: dict[str, Any] = {"empire_id": empire_id}
        if status:
            filters["status"] = status
        if domain:
            filters["domain"] = domain
        return self.find(filters=filters, limit=limit, order_by="name", order_dir="asc")

    def get_active(self, empire_id: str) -> list[Lieutenant]:
        """Get all active lieutenants for an empire."""
        return self.get_by_empire(empire_id, status="active")

    def get_by_domain(self, domain: str, empire_id: str | None = None) -> list[Lieutenant]:
        """Get lieutenants by domain across all or specific empire."""
        filters: dict[str, Any] = {"domain": domain, "status": "active"}
        if empire_id:
            filters["empire_id"] = empire_id
        return self.find(filters=filters)

    def get_by_name(self, name: str, empire_id: str) -> Lieutenant | None:
        """Get lieutenant by name within an empire."""
        return self.find_one({"name": name, "empire_id": empire_id})

    def get_performance_ranking(
        self,
        empire_id: str,
        limit: int = 20,
    ) -> list[Lieutenant]:
        """Get lieutenants ranked by performance score.

        Args:
            empire_id: Empire ID.
            limit: Maximum results.

        Returns:
            Lieutenants ordered by performance (highest first).
        """
        stmt = (
            select(Lieutenant)
            .where(and_(
                Lieutenant.empire_id == empire_id,
                Lieutenant.status == "active",
            ))
            .order_by(desc(Lieutenant.performance_score))
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_best_for_domain(self, domain: str, empire_id: str) -> Lieutenant | None:
        """Get the highest-performing lieutenant for a domain."""
        stmt = (
            select(Lieutenant)
            .where(and_(
                Lieutenant.empire_id == empire_id,
                Lieutenant.domain == domain,
                Lieutenant.status == "active",
            ))
            .order_by(desc(Lieutenant.performance_score))
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_idle_lieutenants(
        self,
        empire_id: str,
        idle_minutes: int = 30,
    ) -> list[Lieutenant]:
        """Get lieutenants that have been idle for a while.

        Args:
            empire_id: Empire ID.
            idle_minutes: Minutes of inactivity to consider idle.

        Returns:
            List of idle lieutenants.
        """
        threshold = datetime.now(timezone.utc) - timedelta(minutes=idle_minutes)
        stmt = (
            select(Lieutenant)
            .where(and_(
                Lieutenant.empire_id == empire_id,
                Lieutenant.status == "active",
                Lieutenant.current_task_id.is_(None),
                (Lieutenant.last_active_at < threshold) | Lieutenant.last_active_at.is_(None),
            ))
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_overloaded_lieutenants(self, empire_id: str) -> list[Lieutenant]:
        """Get lieutenants with active tasks (potentially overloaded)."""
        stmt = (
            select(Lieutenant)
            .where(and_(
                Lieutenant.empire_id == empire_id,
                Lieutenant.status == "active",
                Lieutenant.current_task_id.is_not(None),
            ))
        )
        return list(self.session.execute(stmt).scalars().all())

    def update_performance(
        self,
        lieutenant_id: str,
        task_succeeded: bool,
        quality_score: float | None = None,
        cost_usd: float = 0.0,
        execution_time: float = 0.0,
    ) -> Lieutenant | None:
        """Update lieutenant performance metrics after a task.

        Args:
            lieutenant_id: Lieutenant ID.
            task_succeeded: Whether the task succeeded.
            quality_score: Quality score of the task result.
            cost_usd: Cost of the task.
            execution_time: Execution time in seconds.

        Returns:
            Updated lieutenant.
        """
        lt = self.get(lieutenant_id)
        if lt is None:
            return None

        if task_succeeded:
            lt.tasks_completed += 1
        else:
            lt.tasks_failed += 1

        lt.total_cost_usd += cost_usd

        # Rolling average for quality and execution time
        total_tasks = lt.tasks_completed + lt.tasks_failed
        if quality_score is not None:
            lt.avg_quality_score = (
                (lt.avg_quality_score * (total_tasks - 1) + quality_score) / total_tasks
            )
        if execution_time > 0:
            lt.avg_execution_time = (
                (lt.avg_execution_time * (total_tasks - 1) + execution_time) / total_tasks
            )

        # Recalculate performance score (weighted composite)
        success_rate = lt.tasks_completed / total_tasks if total_tasks > 0 else 0.5
        quality_factor = lt.avg_quality_score if lt.avg_quality_score > 0 else 0.5
        lt.performance_score = min(1.0, (success_rate * 0.4 + quality_factor * 0.6))

        lt.last_active_at = datetime.now(timezone.utc)
        self.session.flush()
        return lt

    def get_task_stats(self, lieutenant_id: str) -> dict:
        """Get detailed task statistics for a lieutenant.

        Returns:
            Dict with task counts by status, avg quality, total cost, etc.
        """
        stmt = (
            select(
                Task.status,
                func.count(Task.id).label("count"),
                func.avg(Task.quality_score).label("avg_quality"),
                func.sum(Task.cost_usd).label("total_cost"),
                func.avg(Task.execution_time_seconds).label("avg_time"),
            )
            .where(Task.lieutenant_id == lieutenant_id)
            .group_by(Task.status)
        )
        results = self.session.execute(stmt).all()

        stats: dict[str, Any] = {
            "by_status": {},
            "total_tasks": 0,
            "avg_quality": 0.0,
            "total_cost": 0.0,
            "avg_execution_time": 0.0,
        }

        total_quality_sum = 0.0
        quality_count = 0

        for row in results:
            status, count, avg_q, total_c, avg_t = row
            stats["by_status"][status] = count
            stats["total_tasks"] += count
            stats["total_cost"] += float(total_c or 0)
            if avg_q is not None:
                total_quality_sum += float(avg_q) * count
                quality_count += count
            if avg_t is not None:
                stats["avg_execution_time"] += float(avg_t) * count

        if quality_count > 0:
            stats["avg_quality"] = total_quality_sum / quality_count
        if stats["total_tasks"] > 0:
            stats["avg_execution_time"] /= stats["total_tasks"]

        return stats

    def get_cost_breakdown(self, lieutenant_id: str, days: int = 30) -> dict:
        """Get cost breakdown for a lieutenant over a time period.

        Args:
            lieutenant_id: Lieutenant ID.
            days: Number of days to look back.

        Returns:
            Dict with cost by model, by purpose, daily totals.
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        # By model
        stmt_model = (
            select(
                BudgetLog.model_used,
                func.sum(BudgetLog.cost_usd).label("total"),
                func.count(BudgetLog.id).label("count"),
            )
            .where(and_(
                BudgetLog.lieutenant_id == lieutenant_id,
                BudgetLog.created_at >= since,
            ))
            .group_by(BudgetLog.model_used)
        )
        model_results = self.session.execute(stmt_model).all()

        # By purpose
        stmt_purpose = (
            select(
                BudgetLog.purpose,
                func.sum(BudgetLog.cost_usd).label("total"),
            )
            .where(and_(
                BudgetLog.lieutenant_id == lieutenant_id,
                BudgetLog.created_at >= since,
            ))
            .group_by(BudgetLog.purpose)
        )
        purpose_results = self.session.execute(stmt_purpose).all()

        return {
            "by_model": {row[0]: {"cost": float(row[1]), "count": row[2]} for row in model_results},
            "by_purpose": {row[0]: float(row[1]) for row in purpose_results},
            "total": sum(float(row[1]) for row in model_results),
            "period_days": days,
        }

    def get_real_cost(self, lieutenant_id: str) -> float:
        """Get real cost for a lieutenant from BudgetLog.

        Lieutenant.total_cost_usd is not reliably incremented, so we
        sum from BudgetLog instead (same pattern used for Empire costs).
        """
        total = self.session.execute(
            select(func.coalesce(func.sum(BudgetLog.cost_usd), 0.0))
            .where(BudgetLog.lieutenant_id == lieutenant_id)
        ).scalar()
        return float(total or 0.0)

    def get_real_costs_bulk(self, lieutenant_ids: list[str]) -> dict[str, float]:
        """Get real costs for multiple lieutenants from BudgetLog.

        Returns:
            Dict mapping lieutenant_id -> total cost USD.
        """
        if not lieutenant_ids:
            return {}
        stmt = (
            select(
                BudgetLog.lieutenant_id,
                func.coalesce(func.sum(BudgetLog.cost_usd), 0.0).label("total"),
            )
            .where(BudgetLog.lieutenant_id.in_(lieutenant_ids))
            .group_by(BudgetLog.lieutenant_id)
        )
        results = self.session.execute(stmt).all()
        costs = {lid: 0.0 for lid in lieutenant_ids}
        for row in results:
            costs[row[0]] = float(row[1])
        return costs

    def get_domains(self, empire_id: str) -> list[str]:
        """Get all unique domains for an empire's lieutenants."""
        return self.distinct_values("domain", {"empire_id": empire_id})

    def needs_learning(self, empire_id: str, hours: int = 6) -> list[Lieutenant]:
        """Get lieutenants that haven't had a learning cycle recently.

        Args:
            empire_id: Empire ID.
            hours: Hours since last learning to consider due.

        Returns:
            Lieutenants due for learning.
        """
        threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = (
            select(Lieutenant)
            .where(and_(
                Lieutenant.empire_id == empire_id,
                Lieutenant.status == "active",
                (Lieutenant.last_learning_at < threshold) | Lieutenant.last_learning_at.is_(None),
            ))
            .order_by(Lieutenant.last_learning_at.asc().nullsfirst())
        )
        return list(self.session.execute(stmt).scalars().all())

    def set_current_task(self, lieutenant_id: str, task_id: str | None) -> None:
        """Set or clear the current task for a lieutenant."""
        self.update(
            lieutenant_id,
            current_task_id=task_id,
            last_active_at=datetime.now(timezone.utc),
        )

    def get_fleet_summary(self, empire_id: str) -> dict:
        """Get a summary of the lieutenant fleet for an empire."""
        stmt = (
            select(
                Lieutenant.status,
                func.count(Lieutenant.id).label("count"),
                func.avg(Lieutenant.performance_score).label("avg_perf"),
                func.sum(Lieutenant.tasks_completed).label("total_completed"),
                func.sum(Lieutenant.tasks_failed).label("total_failed"),
            )
            .where(Lieutenant.empire_id == empire_id)
            .group_by(Lieutenant.status)
        )
        results = self.session.execute(stmt).all()

        summary = {
            "by_status": {},
            "total_lieutenants": 0,
            "avg_performance": 0.0,
            "total_tasks_completed": 0,
            "total_tasks_failed": 0,
            "total_cost_usd": 0.0,
        }

        perf_sum = 0.0
        perf_count = 0

        for row in results:
            status, count, avg_perf, completed, failed = row
            summary["by_status"][status] = count
            summary["total_lieutenants"] += count
            summary["total_tasks_completed"] += int(completed or 0)
            summary["total_tasks_failed"] += int(failed or 0)
            if avg_perf is not None:
                perf_sum += float(avg_perf) * count
                perf_count += count

        if perf_count > 0:
            summary["avg_performance"] = perf_sum / perf_count

        # Pull real cost from BudgetLog (Lieutenant.total_cost_usd is never
        # reliably incremented — same fix applied to Empire-level costs).
        lt_ids_stmt = (
            select(Lieutenant.id).where(Lieutenant.empire_id == empire_id)
        )
        lt_ids = [r[0] for r in self.session.execute(lt_ids_stmt).all()]
        if lt_ids:
            total_cost = self.session.execute(
                select(func.coalesce(func.sum(BudgetLog.cost_usd), 0.0))
                .where(BudgetLog.lieutenant_id.in_(lt_ids))
            ).scalar()
            summary["total_cost_usd"] = float(total_cost or 0.0)

        return summary
