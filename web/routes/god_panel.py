"""God Panel — unified command interface across all empires."""

from __future__ import annotations

import logging
import threading
import time
from flask import Blueprint, render_template, jsonify, request, current_app

logger = logging.getLogger(__name__)
god_panel_bp = Blueprint("god_panel", __name__)


@god_panel_bp.route("/")
def god_panel():
    """The God Panel — one interface to command everything."""
    empire_id = current_app.config.get("EMPIRE_ID", "")

    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        from db.repositories.lieutenant import LieutenantRepository
        from db.repositories.directive import DirectiveRepository
        from core.routing.budget import BudgetManager
        from core.knowledge.graph import KnowledgeGraph
        from core.memory.manager import MemoryManager

        session = get_session()
        try:
            # All empires in the network
            empire_repo = EmpireRepository(session)
            empires = empire_repo.get_all()
            empire_list = [
                {
                    "id": e.id,
                    "name": e.name,
                    "domain": e.domain,
                    "status": e.status,
                    "tasks": e.total_tasks_completed,
                    "cost": e.total_cost_usd,
                    "knowledge": e.total_knowledge_entries,
                }
                for e in empires
            ]

            # Current empire stats
            lt_repo = LieutenantRepository(session)
            lts = lt_repo.get_by_empire(empire_id, status="active")
            fleet = [
                {
                    "id": lt.id,
                    "name": lt.name,
                    "domain": lt.domain,
                    "performance": lt.performance_score,
                    "tasks": lt.tasks_completed,
                    "cost": lt.total_cost_usd,
                }
                for lt in sorted(lts, key=lambda x: x.performance_score, reverse=True)
            ]

            # Recent directives
            dir_repo = DirectiveRepository(session)
            recent = dir_repo.get_completed(empire_id, days=7, limit=10)
            active = dir_repo.get_active(empire_id)
            directives = {
                "active": [{"id": d.id, "title": d.title, "status": d.status} for d in active],
                "recent": [
                    {"id": d.id, "title": d.title, "quality": d.quality_score, "cost": d.total_cost_usd}
                    for d in recent
                ],
            }

            # Budget
            bm = BudgetManager(empire_id)
            budget = bm.get_budget_report(days=30)

            # Knowledge stats
            graph = KnowledgeGraph(empire_id)
            kg_stats = graph.get_stats()

            # Memory stats
            mm = MemoryManager(empire_id)
            mem_stats = mm.get_stats()

            # Scheduler
            scheduler_info = {}
            daemon = current_app.config.get("_SCHEDULER_DAEMON")
            if daemon:
                status = daemon.get_status()
                scheduler_info = {
                    "running": status.running,
                    "ticks": status.total_ticks,
                    "jobs": status.jobs_active,
                    "errors": status.errors,
                }

            context = {
                "empires": empire_list,
                "fleet": fleet,
                "directives": directives,
                "budget": {
                    "daily": budget.daily_spend,
                    "monthly": budget.monthly_spend,
                    "daily_remaining": budget.daily_remaining,
                },
                "knowledge": {
                    "entities": kg_stats.entity_count,
                    "relations": kg_stats.relation_count,
                },
                "memory": {
                    "total": mem_stats.total_count,
                    "by_type": mem_stats.by_type,
                },
                "scheduler": scheduler_info,
            }

            return render_template("god_panel.html", **context)

        finally:
            session.close()

    except Exception as e:
        logger.error("God Panel error: %s", e)
        return render_template("god_panel.html", error=str(e))


@god_panel_bp.route("/command", methods=["POST"])
def execute_command():
    """Execute a single natural-language command across the empire network.

    The God Panel interprets the command, routes it to the right lieutenants,
    and returns results.
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json(silent=True) or {}
    command = data.get("command", "").strip()

    if not command:
        return jsonify({"error": "No command provided"}), 400

    try:
        from llm.router import ModelRouter, TaskMetadata
        from llm.base import LLMRequest, LLMMessage
        router = ModelRouter()

        # Step 1: Classify the command
        classify_prompt = (
            "You are the God Panel of an autonomous AI research system called Empire.\n"
            "Empire has 6 lieutenants: Model Intelligence (models), Research Scout (research), "
            "Agent Systems (agents), Tooling & Infra (tooling), Industry & Strategy (industry), "
            "Open Source (open_source).\n\n"
            "Available actions:\n"
            "- RESEARCH: Research a topic (routes to /api/research)\n"
            "- DIRECTIVE: Create and execute a multi-lieutenant directive\n"
            "- WARROOM: Start a multi-lieutenant debate on a topic\n"
            "- SWEEP: Run an intelligence sweep for new discoveries\n"
            "- EVOLVE: Trigger an evolution cycle\n"
            "- AUDIT: Run a knowledge graph audit\n"
            "- STATUS: Report system status\n"
            "- CONTENT: Generate a report on a topic\n\n"
            f'User command: "{command}"\n\n'
            "Respond with EXACTLY this JSON format:\n"
            '{"action": "ACTION_TYPE", "topic": "the refined topic/title", '
            '"description": "detailed description of what to do", '
            '"lieutenants": ["domain1", "domain2"], "priority": 1-10}'
        )

        response = router.execute(
            LLMRequest(
                messages=[LLMMessage.user(classify_prompt)],
                max_tokens=300,
                temperature=0.2,
            ),
            TaskMetadata(task_type="classification", complexity="simple"),
        )

        # Parse the classification
        import json
        try:
            # Extract JSON from response
            text = response.content
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                plan = json.loads(text[start:end])
            else:
                plan = {"action": "RESEARCH", "topic": command, "description": command}
        except (json.JSONDecodeError, ValueError):
            plan = {"action": "RESEARCH", "topic": command, "description": command}

        action = plan.get("action", "RESEARCH").upper()
        topic = plan.get("topic", command)
        description = plan.get("description", command)
        priority = plan.get("priority", 5)

        result = {"command": command, "action": action, "plan": plan}

        # Step 2: Execute the action
        if action == "RESEARCH":
            from core.search.web import WebSearcher
            searcher = WebSearcher(empire_id)
            search_result = searcher.research_topic(topic, depth="deep")
            result["status"] = "completed"
            result["research"] = {
                "success": search_result.get("success", False),
                "sources": search_result.get("source_count", 0),
                "cost": search_result.get("cost_usd", 0),
            }
            if search_result.get("synthesis"):
                result["synthesis"] = search_result["synthesis"][:1000]

        elif action == "DIRECTIVE":
            from core.directives.manager import DirectiveManager
            dm = DirectiveManager(empire_id)
            directive = dm.create_directive(
                title=topic,
                description=description,
                priority=priority,
                source="god_panel",
            )
            # Execute in background
            directive_id = directive.get("id", "")
            if directive_id:
                def run_bg():
                    dm2 = DirectiveManager(empire_id)
                    dm2.execute_directive(directive_id)
                threading.Thread(target=run_bg, daemon=True).start()

            result["status"] = "executing"
            result["directive_id"] = directive_id
            result["message"] = "Directive created and executing in background"

        elif action == "WARROOM":
            from core.directives.manager import DirectiveManager
            dm = DirectiveManager(empire_id)
            directive = dm.create_directive(
                title=f"Debate: {topic}",
                description=f"War Room debate: {description}. Each lieutenant argues from their domain perspective. Synthesize into a unified assessment.",
                priority=priority,
                source="god_panel",
            )
            directive_id = directive.get("id", "")
            if directive_id:
                def run_bg():
                    dm2 = DirectiveManager(empire_id)
                    dm2.execute_directive(directive_id)
                threading.Thread(target=run_bg, daemon=True).start()

            result["status"] = "debating"
            result["directive_id"] = directive_id

        elif action == "SWEEP":
            try:
                from core.search.sweep import IntelligenceSweep
                sweep = IntelligenceSweep(empire_id)
                discoveries = sweep.run_sweep()
                result["status"] = "completed"
                result["discoveries"] = len(discoveries) if isinstance(discoveries, list) else 0
            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)

        elif action == "EVOLVE":
            from core.evolution.cycle import EvolutionCycleManager
            ecm = EvolutionCycleManager(empire_id)
            evo_result = ecm.run_full_cycle()
            result["status"] = "completed"
            result["proposals"] = evo_result.proposals_collected
            result["applied"] = evo_result.applied

        elif action == "AUDIT":
            from core.knowledge.maintenance import KnowledgeMaintainer
            maintainer = KnowledgeMaintainer(empire_id)
            audit = maintainer.deep_llm_audit(batch_size=20)
            result["status"] = "completed"
            result["audit"] = audit

        elif action == "STATUS":
            from core.scheduler.health import HealthChecker
            checker = HealthChecker(empire_id)
            result["status"] = "completed"
            result["health"] = checker.run_all_checks()

        elif action == "CONTENT":
            from core.content.generator import ContentGenerator
            gen = ContentGenerator(empire_id)
            report = gen.generate_topic_report(topic)
            result["status"] = "completed"
            result["report"] = report

        else:
            # Default to research
            from core.search.web import WebSearcher
            searcher = WebSearcher(empire_id)
            search_result = searcher.research_topic(topic, depth="deep")
            result["status"] = "completed"
            result["research"] = {"sources": search_result.get("source_count", 0)}

        result["cost"] = response.cost_usd
        return jsonify(result)

    except Exception as e:
        logger.error("God Panel command failed: %s", e)
        return jsonify({"error": str(e), "command": command}), 500


@god_panel_bp.route("/network/status")
def network_status():
    """Get status of all empires in the network."""
    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        session = get_session()
        try:
            repo = EmpireRepository(session)
            empires = repo.get_all()
            return jsonify([
                {
                    "id": e.id, "name": e.name, "domain": e.domain,
                    "status": e.status, "tasks": e.total_tasks_completed,
                    "cost": e.total_cost_usd, "knowledge": e.total_knowledge_entries,
                }
                for e in empires
            ])
        finally:
            session.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
