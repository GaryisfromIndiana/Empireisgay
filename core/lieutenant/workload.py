"""Workload balancing — distributes tasks across lieutenants efficiently."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorkloadState:
    """Current workload state for a lieutenant."""
    lieutenant_id: str
    name: str = ""
    domain: str = ""
    status: str = "active"
    current_task: bool = False
    tasks_in_queue: int = 0
    tasks_today: int = 0
    cost_today: float = 0.0
    avg_task_duration: float = 0.0
    performance_score: float = 0.5
    load_score: float = 0.0  # 0 = idle, 1 = fully loaded


@dataclass
class WorkloadReport:
    """Report on fleet workload distribution."""
    total_lieutenants: int = 0
    active_lieutenants: int = 0
    idle_lieutenants: int = 0
    overloaded_lieutenants: int = 0
    avg_load: float = 0.0
    load_distribution: dict[str, float] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class TaskAssignment:
    """Optimal assignment of a task to a lieutenant."""
    lieutenant_id: str
    lieutenant_name: str = ""
    score: float = 0.0
    reasoning: str = ""
    alternatives: list[dict] = field(default_factory=list)


@dataclass
class RebalanceAction:
    """An action to rebalance workload."""
    action_type: str = "reassign"  # reassign, defer, split
    description: str = ""
    from_lieutenant: str = ""
    to_lieutenant: str = ""
    task_id: str = ""


class WorkloadBalancer:
    """Distributes tasks across lieutenants based on capability, load, and performance.

    Monitors workload distribution and suggests rebalancing when
    some lieutenants are overloaded while others are idle.
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self._overload_threshold = 0.8
        self._idle_threshold = 0.2

    def get_workload_state(self) -> list[WorkloadState]:
        """Get current workload state for all lieutenants."""
        try:
            from db.engine import get_session
            from db.repositories.lieutenant import LieutenantRepository
            from db.repositories.task import TaskRepository

            session = get_session()
            lt_repo = LieutenantRepository(session)
            task_repo = TaskRepository(session)

            active_lts = lt_repo.get_by_empire(self.empire_id, status="active")
            real_costs = lt_repo.get_real_costs_bulk([lt.id for lt in active_lts])
            states = []

            for lt in active_lts:
                # Count today's tasks
                today_tasks = task_repo.find(
                    filters={"lieutenant_id": lt.id, "status": ["completed", "failed", "executing"]},
                    limit=100,
                )
                tasks_today = len([t for t in today_tasks if t.created_at and t.created_at.date() == datetime.now(timezone.utc).date()])

                # Calculate load score
                has_current = lt.current_task_id is not None
                load = 0.0
                if has_current:
                    load += 0.5
                load += min(0.5, tasks_today * 0.05)  # Each task adds 5% load

                states.append(WorkloadState(
                    lieutenant_id=lt.id,
                    name=lt.name,
                    domain=lt.domain,
                    status=lt.status,
                    current_task=has_current,
                    tasks_today=tasks_today,
                    cost_today=real_costs.get(lt.id, 0.0),
                    avg_task_duration=lt.avg_execution_time,
                    performance_score=lt.performance_score,
                    load_score=load,
                ))

            return states

        except Exception as e:
            logger.error("Failed to get workload state: %s", e)
            return []

    def get_workload_report(self) -> WorkloadReport:
        """Get a comprehensive workload report."""
        states = self.get_workload_state()

        if not states:
            return WorkloadReport()

        active = [s for s in states if s.status == "active"]
        idle = [s for s in active if s.load_score < self._idle_threshold]
        overloaded = [s for s in active if s.load_score > self._overload_threshold]
        avg_load = sum(s.load_score for s in active) / len(active) if active else 0

        recommendations = []
        if overloaded:
            overloaded_names = [s.name for s in overloaded]
            recommendations.append(f"Overloaded lieutenants: {', '.join(overloaded_names)}. Consider redistributing tasks.")
        if idle and overloaded:
            idle_names = [s.name for s in idle]
            recommendations.append(f"Idle lieutenants available: {', '.join(idle_names)}. Route new tasks to them.")
        if avg_load > 0.7:
            recommendations.append("Overall fleet load is high. Consider adding more lieutenants.")
        if avg_load < 0.1 and len(active) > 2:
            recommendations.append("Fleet is largely idle. May be able to deactivate some lieutenants to save costs.")

        return WorkloadReport(
            total_lieutenants=len(states),
            active_lieutenants=len(active),
            idle_lieutenants=len(idle),
            overloaded_lieutenants=len(overloaded),
            avg_load=avg_load,
            load_distribution={s.name: s.load_score for s in active},
            recommendations=recommendations,
        )

    def assign_task(
        self,
        task_description: str,
        task_type: str = "general",
        required_domain: str = "",
        required_capabilities: list[str] | None = None,
    ) -> TaskAssignment:
        """Find the best lieutenant for a task considering workload.

        Args:
            task_description: Task description.
            task_type: Task type.
            required_domain: Required domain expertise.
            required_capabilities: Required capabilities.

        Returns:
            TaskAssignment with best match.
        """
        states = self.get_workload_state()
        active = [s for s in states if s.status == "active"]

        if not active:
            return TaskAssignment(lieutenant_id="", reasoning="No active lieutenants")

        candidates = []
        desc_lower = task_description.lower()

        for state in active:
            score = 0.0
            reasons = []

            # Domain match
            if required_domain and state.domain == required_domain:
                score += 0.3
                reasons.append(f"domain match ({state.domain})")
            elif state.domain and state.domain.lower() in desc_lower:
                score += 0.2
                reasons.append(f"domain keyword match")

            # Performance
            score += state.performance_score * 0.25
            reasons.append(f"performance {state.performance_score:.2f}")

            # Load (prefer less loaded)
            load_bonus = (1.0 - state.load_score) * 0.25
            score += load_bonus
            if state.load_score < 0.3:
                reasons.append("idle")
            elif state.load_score > 0.7:
                reasons.append("busy")
                score -= 0.1

            # Currently working (penalty)
            if state.current_task:
                score -= 0.15
                reasons.append("has active task")

            candidates.append({
                "lieutenant_id": state.lieutenant_id,
                "name": state.name,
                "score": max(0, score),
                "reasoning": "; ".join(reasons),
            })

        candidates.sort(key=lambda c: c["score"], reverse=True)

        if not candidates:
            return TaskAssignment(lieutenant_id="", reasoning="No suitable candidates")

        best = candidates[0]
        alternatives = candidates[1:3]

        return TaskAssignment(
            lieutenant_id=best["lieutenant_id"],
            lieutenant_name=best["name"],
            score=best["score"],
            reasoning=best["reasoning"],
            alternatives=alternatives,
        )

    def suggest_rebalance(self) -> list[RebalanceAction]:
        """Suggest rebalancing actions for the fleet."""
        states = self.get_workload_state()
        active = [s for s in states if s.status == "active"]

        overloaded = [s for s in active if s.load_score > self._overload_threshold]
        idle = [s for s in active if s.load_score < self._idle_threshold]

        actions = []

        for over in overloaded:
            if idle:
                best_idle = max(idle, key=lambda s: s.performance_score)
                actions.append(RebalanceAction(
                    action_type="reassign",
                    description=f"Move tasks from {over.name} (load: {over.load_score:.2f}) to {best_idle.name} (load: {best_idle.load_score:.2f})",
                    from_lieutenant=over.lieutenant_id,
                    to_lieutenant=best_idle.lieutenant_id,
                ))
            else:
                actions.append(RebalanceAction(
                    action_type="defer",
                    description=f"{over.name} is overloaded ({over.load_score:.2f}) but no idle lieutenants available. Consider deferring low-priority tasks.",
                    from_lieutenant=over.lieutenant_id,
                ))

        return actions

    def get_optimal_batch_assignment(
        self,
        tasks: list[dict],
    ) -> list[dict]:
        """Optimally assign a batch of tasks across lieutenants.

        Args:
            tasks: List of task dicts with description, type, priority.

        Returns:
            List of {task, assignment} dicts.
        """
        assignments = []

        # Sort tasks by priority (highest first)
        sorted_tasks = sorted(tasks, key=lambda t: t.get("priority", 5))

        for task in sorted_tasks:
            assignment = self.assign_task(
                task_description=task.get("description", ""),
                task_type=task.get("task_type", "general"),
                required_domain=task.get("domain", ""),
            )

            assignments.append({
                "task": task,
                "assignment": {
                    "lieutenant_id": assignment.lieutenant_id,
                    "lieutenant_name": assignment.lieutenant_name,
                    "score": assignment.score,
                    "reasoning": assignment.reasoning,
                },
            })

        return assignments
