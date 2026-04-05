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
        from db.engine import repo_scope
        from db.repositories.directive import DirectiveRepository
        with repo_scope(DirectiveRepository) as repo:
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
        from db.engine import repo_scope
        from db.repositories.directive import DirectiveRepository
        with repo_scope(DirectiveRepository) as repo:
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
        from db.engine import repo_scope
        from db.repositories.directive import DirectiveRepository
        with repo_scope(DirectiveRepository) as repo:
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
        all_lts = lt_manager.list_lieutenants(status="active")  # Single DB call
        lt_map = {lt["id"]: lt for lt in all_lts}

        assigned = db_directive.assigned_lieutenants_json or []
        if not assigned:
            assigned = [lt["id"] for lt in all_lts[:3]]

        session = WarRoomSession(
            empire_id=self.empire_id,
            directive_id=directive_id,
            session_type="planning",
        )
        for lt_id in assigned:
            lt_info = lt_map.get(lt_id)
            if lt_info:
                session.add_participant(lt_id, lt_info.get("name", ""), lt_info.get("domain", ""))

        plan_result = session.run_planning_phase(db_directive.title, db_directive.description)

        # 2. Wave execution
        with repo_scope(DirectiveRepository) as repo:
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

        # If no waves from planning, use LLM to generate proper task breakdown
        if not waves:
            logger.warning("No waves from War Room — using LLM to generate task breakdown")
            waves = self._llm_task_breakdown(db_directive.title, db_directive.description)

        wave_results = []
        total_cost = 0.0

        for wave in waves:
            wave_num = wave.get("wave_number", 1)
            tasks = wave.get("tasks", [])
            with repo_scope(DirectiveRepository) as repo:
                repo.update(directive_id, current_wave=wave_num)
                repo.commit()

            wave_task_results = []
            task_records = []

            # Assign lieutenants to tasks before execution
            from core.ace.engine import TaskInput
            task_assignments = []

            # Fetch active lieutenants ONCE instead of per-task DB query
            from db.repositories.lieutenant import LieutenantRepository
            with repo_scope(LieutenantRepository) as repo_lt:
                active_lts = repo_lt.get_by_empire(lt_manager.empire_id, status="active")

            for task_data in tasks:
                desc_lower = task_data.get("description", "").lower()
                best_lt_db = None
                best_score = -1

                for db_lt in active_lts:
                    score = 0.0
                    if db_lt.domain and db_lt.domain.lower() in desc_lower:
                        score += 0.35
                    specs = db_lt.specializations_json or []
                    matched = sum(1 for s in specs if s.lower() in desc_lower)
                    score += min(0.3, matched * 0.1)
                    score += db_lt.performance_score * 0.1
                    if db_lt.current_task_id:
                        score -= 0.1
                    if score > best_score:
                        best_score = score
                        best_lt_db = db_lt

                if not best_lt_db:
                    if active_lts:
                        best_lt_db = active_lts[0]
                    else:
                        wave_task_results.append({
                            "title": task_data.get("title", ""),
                            "success": False,
                            "error": "No lieutenant available",
                            "quality_score": 0,
                            "cost_usd": 0,
                        })
                        continue

                lt = lt_manager.get_lieutenant(best_lt_db.id)
                if lt:
                    task_assignments.append((task_data, lt))

            # Execute tasks in parallel within the wave
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from config.settings import get_settings

            def _execute_one(task_data_and_lt):
                td, lt = task_data_and_lt
                try:
                    task = TaskInput(title=td.get("title", ""), description=td.get("description", ""))
                    result = lt.execute_task(task)
                    return td, lt, result
                except Exception:
                    raise

            max_workers = min(get_settings().ace.max_parallel_tasks, len(task_assignments) or 1)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_task = {
                    executor.submit(_execute_one, assignment): assignment[0]
                    for assignment in task_assignments
                }

                for future in as_completed(future_to_task):
                    orig_task_data = future_to_task[future]
                    try:
                        td, lt, result = future.result()
                        wave_task_results.append(result.to_dict())
                        total_cost += result.cost_usd
                        task_records.append({
                            "lt_id": lt.id,
                            "task_data": td,
                            "result": result,
                        })
                    except Exception as e:
                        logger.error("Task '%s' failed: %s", orig_task_data.get("title", "?")[:50], e)
                        wave_task_results.append({
                            "title": orig_task_data.get("title", ""),
                            "success": False,
                            "error": str(e),
                            "quality_score": 0,
                            "cost_usd": 0,
                        })

            # Batch insert all task records in ONE session per wave.
            # IMPORTANT: last_error MUST be set when status='failed', otherwise
            # the row is unactionable — this was the 27-tasks-NULL-error bug.
            try:
                from db.models import Task as TaskModel
                from db.engine import session_scope
                now_utc = datetime.now(timezone.utc)
                for item in task_records:
                    r = item["result"]
                    td = item["task_data"]
                    failed = not r.success
                    error_msg = (r.error or "").strip() or ("quality gate rejected" if failed else "")
                    with session_scope() as db_session:
                        try:
                            db_session.add(TaskModel(
                                directive_id=directive_id,
                                lieutenant_id=item["lt_id"],
                                title=td.get("title", "")[:256],
                                description=td.get("description", "")[:5000],
                                status="failed" if failed else "completed",
                                wave_number=wave_num,
                                cost_usd=r.cost_usd,
                                quality_score=r.quality_score,
                                model_used=r.model_used,
                                tokens_input=r.tokens_input,
                                tokens_output=r.tokens_output,
                                execution_time_seconds=r.execution_time_seconds,
                                output_json={"content": (r.content or "")[:5000]},
                                last_error=error_msg or None,
                                error_log_json=(
                                    [{
                                        "attempt": 1,
                                        "error": error_msg,
                                        "model": r.model_used,
                                        "timestamp": now_utc.isoformat(),
                                    }] if failed else None
                                ),
                                completed_at=now_utc,
                            ))
                        except Exception as row_err:
                            logger.error("Failed to persist task row (title=%r): %s",
                                         td.get("title", "")[:60], row_err)
            except Exception as e:
                logger.error("Failed to batch-record tasks: %s", e)

            wave_results.append({
                "wave_number": wave_num,
                "tasks": wave_task_results,
                "success_rate": sum(1 for t in wave_task_results if t.get("success")) / max(len(wave_task_results), 1),
            })

        # 3. Retrospective + War Room persistence
        retro_result = {}
        try:
            retro_result = session.run_retrospective({
                "directive": db_directive.title,
                "waves": wave_results,
                "total_cost": total_cost,
            })
        except Exception as e:
            logger.warning("Retrospective failed: %s", e)
        finally:
            try:
                session.close_session()
            except Exception as e:
                logger.warning("War Room close failed: %s", e)

        # 4. Complete
        with repo_scope(DirectiveRepository) as repo:
            repo.update(
                directive_id,
                status="completed",
                pipeline_stage="delivered",
                completed_at=datetime.now(timezone.utc),
                total_cost_usd=total_cost,
            )
            repo.commit()

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
        from db.engine import repo_scope
        from db.repositories.directive import DirectiveRepository
        with repo_scope(DirectiveRepository) as repo:
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
        from db.engine import repo_scope
        from db.repositories.directive import DirectiveRepository
        with repo_scope(DirectiveRepository) as repo:
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
        from db.engine import repo_scope
        from db.repositories.directive import DirectiveRepository
        with repo_scope(DirectiveRepository) as repo:
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
        from db.engine import repo_scope
        from db.repositories.directive import DirectiveRepository
        with repo_scope(DirectiveRepository) as repo:
            raw = repo.get_cost_summary(directive_id)
            return CostSummary(
                total_cost=raw.get("total_cost_usd", 0),
                by_model=raw.get("by_model", {}),
            )

    def cancel_directive(self, directive_id: str) -> bool:
        """Cancel a directive."""
        from db.engine import repo_scope
        from db.repositories.directive import DirectiveRepository
        with repo_scope(DirectiveRepository) as repo:
            result = repo.update(directive_id, status="cancelled", completed_at=datetime.now(timezone.utc))
            repo.commit()
            return result is not None

    def get_stats(self, days: int = 30) -> dict:
        """Get directive statistics."""
        from db.engine import repo_scope
        from db.repositories.directive import DirectiveRepository
        with repo_scope(DirectiveRepository) as repo:
            return repo.get_stats(self.empire_id, days)

    def _llm_task_breakdown(self, title: str, description: str) -> list[dict]:
        """Use LLM to generate a proper task breakdown when War Room produces no waves."""
        try:
            import json
            from llm.router import ModelRouter, TaskMetadata
            from llm.base import LLMRequest, LLMMessage

            router = ModelRouter(self.empire_id)

            prompt = (
                "Break down this directive into concrete research tasks organized in waves.\n"
                "Wave 1 should be foundational research. Wave 2 should build on Wave 1 findings.\n\n"
                f"Directive: {title}\n"
                f"Description: {description[:2000]}\n\n"
                "Respond with ONLY a JSON array of waves:\n"
                '[{"wave_number": 1, "tasks": [{"title": "...", "description": "..."}]}, '
                '{"wave_number": 2, "tasks": [{"title": "...", "description": "..."}]}]\n\n'
                "Generate 2-4 tasks per wave. Be specific and actionable."
            )

            response = router.execute(
                LLMRequest(
                    messages=[LLMMessage.user(prompt)],
                    max_tokens=600,
                    temperature=0.3,
                ),
                TaskMetadata(task_type="planning", complexity="moderate"),
            )

            text = response.content.strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                waves = json.loads(text[start:end])
                if isinstance(waves, list) and waves:
                    logger.info("LLM generated %d waves for directive fallback", len(waves))
                    return waves

        except Exception as e:
            logger.warning("LLM task breakdown failed: %s", e)

        # Ultimate fallback: single task
        return [{"wave_number": 1, "tasks": [{"title": title, "description": description}]}]
