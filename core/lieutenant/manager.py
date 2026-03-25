"""Lieutenant lifecycle manager — creates, manages, and coordinates lieutenants."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.ace.engine import ACEEngine
from core.lieutenant.base import Lieutenant, PerformanceStats
from core.lieutenant.persona import PersonaConfig, create_persona, PERSONA_TEMPLATES

logger = logging.getLogger(__name__)


@dataclass
class FleetStats:
    """Statistics about the lieutenant fleet."""
    total: int = 0
    active: int = 0
    inactive: int = 0
    by_domain: dict[str, int] = field(default_factory=dict)
    total_tasks: int = 0
    avg_performance: float = 0.0
    total_cost: float = 0.0


@dataclass
class DirectiveAssignment:
    """Assignment of a directive to lieutenants."""
    directive_id: str = ""
    lieutenant_ids: list[str] = field(default_factory=list)
    task_assignments: list[dict] = field(default_factory=list)


class LieutenantManager:
    """Creates, manages, and coordinates lieutenants.

    Handles lifecycle (create, activate, deactivate), task assignment,
    learning cycles, and fleet-level operations.
    """

    def __init__(self, empire_id: str = "", ace_engine: ACEEngine | None = None):
        self.empire_id = empire_id
        self.ace = ace_engine or ACEEngine()
        self._lieutenants: dict[str, Lieutenant] = {}  # In-memory cache
        self._repo = None

    def _get_repo(self):
        """Get a fresh repository with its own session."""
        from db.engine import get_session
        from db.repositories.lieutenant import LieutenantRepository
        return LieutenantRepository(get_session())

    def create_lieutenant(
        self,
        name: str,
        persona: PersonaConfig | None = None,
        template: str = "",
        domain: str = "",
        overrides: dict | None = None,
    ) -> Lieutenant:
        """Create a new lieutenant.

        Args:
            name: Lieutenant name.
            persona: Custom persona config.
            template: Persona template name (alternative to custom persona).
            domain: Domain specialization.
            overrides: Override persona template values.

        Returns:
            Created Lieutenant.
        """
        if persona is None:
            if template:
                persona = create_persona(template, overrides)
            else:
                persona = PersonaConfig(name=name, role="AI Assistant", domain=domain or "general")

        repo = self._get_repo()
        db_lt = repo.create(
            empire_id=self.empire_id,
            name=name,
            domain=domain or persona.domain,
            persona_json=persona.to_dict(),
            specializations_json=persona.expertise_areas,
            preferred_models_json=persona.preferred_models,
            status="active",
        )
        repo.commit()

        lt = Lieutenant(
            lieutenant_id=db_lt.id,
            name=name,
            empire_id=self.empire_id,
            persona=persona,
            domain=domain or persona.domain,
            ace_engine=self.ace,
        )
        self._lieutenants[db_lt.id] = lt

        logger.info("Created lieutenant: %s (domain=%s)", name, lt.domain)
        return lt

    def get_lieutenant(self, lieutenant_id: str) -> Lieutenant | None:
        """Get a lieutenant by ID."""
        if lieutenant_id in self._lieutenants:
            return self._lieutenants[lieutenant_id]

        repo = self._get_repo()
        db_lt = repo.get(lieutenant_id)
        if db_lt is None:
            return None

        persona = PersonaConfig.from_dict(db_lt.persona_json or {})
        lt = Lieutenant(
            lieutenant_id=db_lt.id,
            name=db_lt.name,
            empire_id=self.empire_id,
            persona=persona,
            domain=db_lt.domain,
            ace_engine=self.ace,
        )
        self._lieutenants[lieutenant_id] = lt
        return lt

    def list_lieutenants(
        self,
        status: str | None = None,
        domain: str | None = None,
    ) -> list[dict]:
        """List all lieutenants with optional filters."""
        repo = self._get_repo()
        db_lts = repo.get_by_empire(self.empire_id, status=status, domain=domain)

        return [
            {
                "id": lt.id,
                "name": lt.name,
                "domain": lt.domain,
                "status": lt.status,
                "performance_score": lt.performance_score,
                "tasks_completed": lt.tasks_completed,
                "tasks_failed": lt.tasks_failed,
                "total_cost": lt.total_cost_usd,
                "last_active": lt.last_active_at.isoformat() if lt.last_active_at else None,
            }
            for lt in db_lts
        ]

    def activate_lieutenant(self, lieutenant_id: str) -> bool:
        """Activate an inactive lieutenant."""
        repo = self._get_repo()
        result = repo.update(lieutenant_id, status="active")
        if result:
            repo.commit()
        return result is not None

    def deactivate_lieutenant(self, lieutenant_id: str) -> bool:
        """Deactivate a lieutenant."""
        repo = self._get_repo()
        result = repo.update(lieutenant_id, status="inactive")
        if result:
            repo.commit()
        if lieutenant_id in self._lieutenants:
            del self._lieutenants[lieutenant_id]
        return result is not None

    def delete_lieutenant(self, lieutenant_id: str) -> bool:
        """Delete a lieutenant permanently."""
        repo = self._get_repo()
        result = repo.delete(lieutenant_id)
        if result:
            repo.commit()
        if lieutenant_id in self._lieutenants:
            del self._lieutenants[lieutenant_id]
        return result

    def find_best_lieutenant(self, task_description: str, task_type: str = "") -> Lieutenant | None:
        """Find the best lieutenant for a task.

        Matches based on domain, specializations, and performance.
        """
        repo = self._get_repo()
        active_lts = repo.get_by_empire(self.empire_id, status="active")

        if not active_lts:
            return None

        best_score = -1
        best_lt = None

        for db_lt in active_lts:
            score = 0.0

            # Domain match
            desc_lower = task_description.lower()
            if db_lt.domain and db_lt.domain.lower() in desc_lower:
                score += 0.3

            # Specialization match
            specs = db_lt.specializations_json or []
            for spec in specs:
                if spec.lower() in desc_lower:
                    score += 0.15

            # Task type match
            if task_type:
                type_domain_map = {
                    "research": ["research", "data_science"],
                    "analysis": ["strategy", "finance", "data_science"],
                    "code": ["technology"],
                    "content": ["content"],
                    "security": ["security"],
                }
                matching_domains = type_domain_map.get(task_type, [])
                if db_lt.domain in matching_domains:
                    score += 0.2

            # Performance bonus
            score += db_lt.performance_score * 0.2

            # Workload penalty (if currently busy)
            if db_lt.current_task_id:
                score -= 0.1

            if score > best_score:
                best_score = score
                best_lt = db_lt

        if best_lt:
            return self.get_lieutenant(best_lt.id)
        return None

    def get_available_lieutenants(self, capabilities: list[str] | None = None) -> list[Lieutenant]:
        """Get all available (active and idle) lieutenants."""
        repo = self._get_repo()
        idle = repo.get_idle_lieutenants(self.empire_id)

        lieutenants = []
        for db_lt in idle:
            if capabilities:
                specs = set(db_lt.specializations_json or [])
                if not any(c in specs for c in capabilities):
                    continue
            lt = self.get_lieutenant(db_lt.id)
            if lt:
                lieutenants.append(lt)

        return lieutenants

    def run_all_learning_cycles(self) -> dict:
        """Run learning cycles for all lieutenants that need them."""
        repo = self._get_repo()
        due = repo.needs_learning(self.empire_id)

        results = {"lieutenants_processed": 0, "total_gaps": 0, "total_researched": 0}

        for db_lt in due:
            lt = self.get_lieutenant(db_lt.id)
            if lt:
                cycle_result = lt.run_learning_cycle()
                results["lieutenants_processed"] += 1
                results["total_gaps"] += cycle_result.get("gaps_found", 0)
                results["total_researched"] += cycle_result.get("researched", 0)

                repo.update(db_lt.id, last_learning_at=datetime.now(timezone.utc))

        repo.commit()
        logger.info("Learning cycles complete: %s", results)
        return results

    def get_fleet_stats(self) -> FleetStats:
        """Get fleet-level statistics."""
        repo = self._get_repo()
        summary = repo.get_fleet_summary(self.empire_id)

        return FleetStats(
            total=summary.get("total_lieutenants", 0),
            active=summary.get("by_status", {}).get("active", 0),
            inactive=summary.get("by_status", {}).get("inactive", 0),
            total_tasks=summary.get("total_tasks_completed", 0) + summary.get("total_tasks_failed", 0),
            avg_performance=summary.get("avg_performance", 0),
            total_cost=summary.get("total_cost_usd", 0),
        )

    def clone_lieutenant(
        self,
        lieutenant_id: str,
        new_name: str,
        target_empire_id: str = "",
    ) -> Lieutenant | None:
        """Clone a lieutenant (optionally to another empire).

        Args:
            lieutenant_id: Source lieutenant.
            new_name: Name for the clone.
            target_empire_id: Target empire (defaults to same).

        Returns:
            Cloned lieutenant.
        """
        source = self.get_lieutenant(lieutenant_id)
        if not source:
            return None

        target_empire = target_empire_id or self.empire_id
        manager = LieutenantManager(target_empire, self.ace) if target_empire != self.empire_id else self

        return manager.create_lieutenant(
            name=new_name,
            persona=source.persona,
            domain=source.domain,
        )

    def update_performance(
        self,
        lieutenant_id: str,
        task_succeeded: bool,
        quality_score: float | None = None,
        cost_usd: float = 0.0,
        execution_time: float = 0.0,
    ) -> None:
        """Update lieutenant performance after a task."""
        repo = self._get_repo()
        repo.update_performance(
            lieutenant_id=lieutenant_id,
            task_succeeded=task_succeeded,
            quality_score=quality_score,
            cost_usd=cost_usd,
            execution_time=execution_time,
        )
        repo.commit()
