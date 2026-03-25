"""Directive lifecycle management — creates and manages directives end-to-end."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class DirectiveProgress:
    """Progress tracking for a directive."""
    directive_id: str = ""
    total_tasks: int = 0
    completed: int = 0
    failed: int = 0
    in_progress: int = 0
    pending: int = 0
    current_wave: int = 0
    total_waves: int = 0
    completion_percent: float = 0.0
    estimated_remaining_cost: float = 0.0


@dataclass
class DirectiveReport:
    """Comprehensive report for a directive."""
    directive_id: str = ""
    title: str = ""
    status: str = ""
    summary: str = ""
    task_count: int = 0
    success_rate: float = 0.0
    quality_score: float = 0.0
    total_cost: float = 0.0
    duration_seconds: float = 0.0
    wave_summaries: list[dict] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)


@dataclass
class CostSummary:
    """Cost summary for a directive."""
    total_cost: float = 0.0
    by_model: dict[str, float] = field(default_factory=dict)
    by_lieutenant: dict[str, float] = field(default_factory=dict)
    by_wave: dict[int, float] = field(default_factory=dict)


class DirectiveManager:
    """Creates and manages directives through their full lifecycle.

    A directive is a high-level goal that flows through the pipeline:
    intake → planning (War Room) → execution (waves) → review → retrospective → delivery
    """

    def __init__(self, empire_id: str = ""):
        self.empire_id = empire_id
        self._repo = None

    def _get_repo(self):
        """Get a fresh repository with its own session."""
        from db.engine import get_session
        from db.repositories.directive import DirectiveRepository
        return DirectiveRepository(get_session())

    def create_directive(
        self,
        title: str,
        description: str,
        priority: int = 5,
        source: str = "human",
        lieutenant_ids: list[str] | None = None,
    ) -> dict:
        """Create a new directive.

        Args:
            title: Directive title.
            description: Detailed description.
            priority: Priority (1=highest, 10=lowest).
            source: Source (human, evolution, autonomous).
            lieutenant_ids: Pre-assigned lieutenants.

        Returns:
            Created directive info.
        """
        repo = self._get_repo()
        directive = repo.create(
            empire_id=self.empire_id,
            title=title,
            description=description,
            priority=priority,
            source=source,
            assigned_lieutenants_json=lieutenant_ids or [],
        )
        repo.commit()

        logger.info("Created directive: %s (priority=%d, source=%s)", title, priority, source)
        return {
            "id": directive.id,
            "title": title,
            "status": "pending",
            "priority": priority,
        }

    def start_directive(self, directive_id: str) -> dict:
        """Start executing a directive."""
        repo = self._get_repo()
        directive = repo.start_directive(directive_id)
        repo.commit()

        if directive:
            return {"id": directive_id, "status": "planning", "started": True}
        return {"id": directive_id, "started": False, "error": "Directive not found"}

    def execute_directive(self, directive_id: str) -> dict:
        """Execute a directive through the full pipeline.

        This is the main entry point for directive execution:
        1. Planning (War Room)
        2. Wave execution
        3. Quality review
        4. Retrospective

        Args:
            directive_id: Directive to execute.

        Returns:
            Execution results.
        """
        repo = self._get_repo()
        db_directive = repo.get(directive_id)
        if not db_directive:
            return {"error": "Directive not found"}

        start_time = time.time()
        repo.start_directive(directive_id)
        repo.commit()

        logger.info("Executing directive: %s", db_directive.title)

        # 1. Planning phase (War Room)
        from core.warroom.session import WarRoomSession
        from core.lieutenant.manager import LieutenantManager

        lt_manager = LieutenantManager(self.empire_id)
        assigned = db_directive.assigned_lieutenants_json or []

        # If no lieutenants assigned, pick the 3 most relevant
        if not assigned:
            available = lt_manager.list_lieutenants(status="active")
            assigned = [lt["id"] for lt in available[:3]]

        session = WarRoomSession(
            empire_id=self.empire_id,
            directive_id=directive_id,
            session_type="planning",
        )
        for lt_id in assigned:
            lt_info = next((lt for lt in lt_manager.list_lieutenants() if lt["id"] == lt_id), None)
            if lt_info:
                session.add_participant(lt_id, lt_info.get("name", ""), lt_info.get("domain", ""))

        plan_result = session.run_planning_phase(db_directive.title, db_directive.description)

        # 2. Wave execution
        repo.update(directive_id, status="executing", pipeline_stage="executing")
        repo.commit()

        unified_plan = plan_result.get("unified_plan", {})

        # Parse waves — handle string-wrapped JSON from LLM
        waves = unified_plan.get("waves", [])
        if isinstance(waves, str):
            import json as _json
            try:
                waves = _json.loads(waves)
            except Exception:
                waves = []

        # If no waves from planning, build default waves from the directive
        if not waves:
            logger.warning("No waves from War Room — building default task set")
            description_parts = db_directive.description.split(",")
            default_tasks = []
            for i, part in enumerate(description_parts[:6]):
                part = part.strip().strip("()")
                if len(part) > 10:
                    default_tasks.append({"title": part[:100], "description": f"Research and analyze: {part}"})

            if not default_tasks:
                default_tasks = [{"title": db_directive.title, "description": db_directive.description}]

            # Split into 2 waves
            mid = max(1, len(default_tasks) // 2)
            waves = [
                {"wave_number": 1, "tasks": default_tasks[:mid]},
                {"wave_number": 2, "tasks": default_tasks[mid:]},
            ]

        wave_results = []
        total_cost = 0.0

        for wave in waves:
            wave_num = wave.get("wave_number", 1)
            tasks = wave.get("tasks", [])
            repo.update(directive_id, current_wave=wave_num)
            repo.commit()

            wave_task_results = []
            for task_data in tasks:
                assigned_lt = task_data.get("assigned_to", "")
                lt = lt_manager.find_best_lieutenant(task_data.get("description", ""))

                if lt:
                    from core.ace.engine import TaskInput
                    task = TaskInput(
                        title=task_data.get("title", ""),
                        description=task_data.get("description", ""),
                    )
                    result = lt.execute_task(task)
                    wave_task_results.append(result.to_dict())
                    total_cost += result.cost_usd

                    # Record task in DB (best-effort)
                    try:
                        from db.models import Task as TaskModel
                        from db.engine import session_scope
                        with session_scope() as db_session:
                            db_task = TaskModel(
                                directive_id=directive_id,
                                lieutenant_id=lt.id,
                                title=task_data.get("title", "")[:256],
                                description=task_data.get("description", "")[:5000],
                                status="completed" if result.success else "failed",
                                wave_number=wave_num,
                                cost_usd=result.cost_usd,
                                quality_score=result.quality_score,
                                model_used=result.model_used,
                                tokens_input=result.tokens_input,
                                tokens_output=result.tokens_output,
                                execution_time_seconds=result.execution_time_seconds,
                                output_json={"content": result.content[:5000]},
                            )
                            db_session.add(db_task)
                    except Exception as e:
                        logger.warning("Failed to record task in DB: %s", e)

            wave_results.append({
                "wave_number": wave_num,
                "tasks": wave_task_results,
                "success_rate": sum(1 for t in wave_task_results if t.get("success")) / max(len(wave_task_results), 1),
            })

        # 3. Complete
        repo.update(
            directive_id,
            status="completed",
            pipeline_stage="delivered",
            completed_at=datetime.now(timezone.utc),
            total_cost_usd=total_cost,
        )
        repo.commit()

        # 4. Retrospective
        retro_result = session.run_retrospective({
            "directive": db_directive.title,
            "waves": wave_results,
            "total_cost": total_cost,
        })
        session.close_session()

        duration = time.time() - start_time
        logger.info("Directive completed: %s (cost=$%.4f, duration=%.1fs)", db_directive.title, total_cost, duration)

        return {
            "directive_id": directive_id,
            "status": "completed",
            "wave_results": wave_results,
            "retrospective": retro_result,
            "total_cost": total_cost,
            "duration_seconds": duration,
        }

    def get_directive(self, directive_id: str) -> dict | None:
        """Get directive details."""
        repo = self._get_repo()
        d = repo.get(directive_id)
        if not d:
            return None
        return {
            "id": d.id, "title": d.title, "description": d.description,
            "status": d.status, "priority": d.priority, "source": d.source,
            "current_wave": d.current_wave, "total_cost": d.total_cost_usd,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }

    def list_directives(self, status: str | None = None, limit: int = 50) -> list[dict]:
        """List directives with optional status filter."""
        repo = self._get_repo()
        directives = repo.get_by_empire(self.empire_id, status=status, limit=limit)
        return [
            {
                "id": d.id, "title": d.title, "status": d.status,
                "priority": d.priority, "source": d.source,
                "total_cost": d.total_cost_usd,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in directives
        ]

    def get_progress(self, directive_id: str) -> DirectiveProgress:
        """Get directive execution progress."""
        repo = self._get_repo()
        progress = repo.get_progress(directive_id)
        return DirectiveProgress(
            directive_id=directive_id,
            total_tasks=progress.get("total_tasks", 0),
            completed=progress.get("completed", 0),
            failed=progress.get("failed", 0),
            in_progress=progress.get("in_progress", 0),
            pending=progress.get("pending", 0),
            completion_percent=progress.get("completion_percent", 0),
        )

    def get_cost_summary(self, directive_id: str) -> CostSummary:
        """Get cost summary for a directive."""
        repo = self._get_repo()
        raw = repo.get_cost_summary(directive_id)
        return CostSummary(
            total_cost=raw.get("total_cost_usd", 0),
            by_model=raw.get("by_model", {}),
        )

    def cancel_directive(self, directive_id: str) -> bool:
        """Cancel a directive."""
        repo = self._get_repo()
        result = repo.update(directive_id, status="cancelled", completed_at=datetime.now(timezone.utc))
        repo.commit()
        return result is not None

    def get_stats(self, days: int = 30) -> dict:
        """Get directive statistics."""
        repo = self._get_repo()
        return repo.get_stats(self.empire_id, days)
