"""Dashboard routes — main overview page."""

from __future__ import annotations

import logging

from flask import Blueprint, render_template, jsonify, current_app

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    """Main dashboard page."""
    empire_id = current_app.config.get("EMPIRE_ID", "")

    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        from db.repositories.directive import DirectiveRepository

        session = get_session()
        try:
            # Empire overview
            empire_repo = EmpireRepository(session)
            health = empire_repo.get_health_overview(empire_id)

            # Directives
            dir_repo = DirectiveRepository(session)
            active_directives = dir_repo.get_active(empire_id)
            recent_completed = dir_repo.get_completed(empire_id, days=30, limit=5)

            # Budget
            from core.routing.budget import BudgetManager
            bm = BudgetManager(empire_id)
            budget = bm.get_budget_report(days=30)

            # Latest research from memory
            latest_research = []
            try:
                from core.memory.manager import MemoryManager
                mm = MemoryManager(empire_id)
                research = mm.recall(
                    query="research synthesis",
                    memory_types=["semantic"],
                    limit=5,
                )
                latest_research = research
            except Exception:
                pass

            # Latest RSS feed entries
            latest_feeds = []
            try:
                from core.search.feeds import FeedReader
                reader = FeedReader(empire_id)
                entries = reader.fetch_latest(max_total=5, max_per_feed=2)
                latest_feeds = [
                    {"title": e.title, "url": e.url, "summary": e.summary, "source": e.source_feed}
                    for e in entries
                ]
            except Exception:
                pass

            # Knowledge graph highlights
            knowledge_highlights = []
            try:
                from core.knowledge.graph import KnowledgeGraph
                graph = KnowledgeGraph(empire_id)
                central = graph.get_central_entities(limit=9)
                knowledge_highlights = [
                    {"name": n.name, "type": n.entity_type, "confidence": n.confidence}
                    for n in central
                ]
            except Exception:
                pass

            # Recent discoveries from sweeps
            recent_discoveries = []
            try:
                from core.search.sweep import IntelligenceSweep
                sweep = IntelligenceSweep(empire_id)
                recent_discoveries = sweep.get_recent_discoveries(limit=5)
            except Exception:
                pass

            # Infrastructure stats (cache, circuits)
            infra_stats = {}
            try:
                from llm.cache import get_cache
                infra_stats["cache"] = get_cache().get_stats()
            except Exception:
                infra_stats["cache"] = {"enabled": False}

            try:
                from utils.circuit_breaker import get_all_circuit_stats
                infra_stats["circuits"] = get_all_circuit_stats()
            except Exception:
                infra_stats["circuits"] = {}

            # Scheduler status
            scheduler_info = {}
            try:
                daemon = current_app.config.get("_SCHEDULER_DAEMON")
                if daemon:
                    status = daemon.get_status()
                    scheduler_info = {
                        "running": status.running,
                        "total_ticks": status.total_ticks,
                        "total_jobs": status.total_job_runs,
                        "errors": status.errors,
                    }
            except Exception:
                pass

            # Fleet stats for performance bars
            fleet_stats = []
            try:
                from db.repositories.lieutenant import LieutenantRepository
                lt_repo = LieutenantRepository(session)
                lts = lt_repo.get_by_empire(empire_id, status="active")
                fleet_stats = [
                    {
                        "name": lt.name,
                        "domain": lt.domain,
                        "performance": lt.performance_score,
                        "tasks": lt.tasks_completed + lt.tasks_failed,
                        "cost": lt.total_cost_usd,
                    }
                    for lt in sorted(lts, key=lambda x: x.performance_score, reverse=True)
                ]
            except Exception:
                pass

            context = {
                "health": health,
                "scheduler": scheduler_info,
                "recent_discoveries": recent_discoveries,
                "fleet_stats": fleet_stats,
                "active_directives": [
                    {"id": d.id, "title": d.title, "status": d.status, "priority": d.priority}
                    for d in active_directives
                ],
                "recent_completed": [
                    {"id": d.id, "title": d.title, "quality": d.quality_score, "cost": d.total_cost_usd}
                    for d in recent_completed
                ],
                "budget": {
                    "daily_spend": budget.daily_spend,
                    "monthly_spend": budget.monthly_spend,
                    "daily_remaining": budget.daily_remaining,
                    "monthly_remaining": budget.monthly_remaining,
                    "alerts": [{"message": a.message, "severity": a.severity} for a in budget.alerts],
                },
                "latest_research": latest_research,
                "latest_feeds": latest_feeds,
                "knowledge_highlights": knowledge_highlights,
                "infra": infra_stats,
            }

            return render_template("dashboard.html", **context)
        finally:
            session.close()

    except Exception as e:
        logger.error("Dashboard error: %s", e)
        return render_template("dashboard.html", error=str(e))


@dashboard_bp.route("/api/dashboard/stats")
def dashboard_stats():
    """Full dashboard stats as JSON for live refresh."""
    empire_id = current_app.config.get("EMPIRE_ID", "")

    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        from db.repositories.directive import DirectiveRepository

        session = get_session()
        try:
            # Empire overview
            empire_repo = EmpireRepository(session)
            health = empire_repo.get_health_overview(empire_id)

            # Directives
            dir_repo = DirectiveRepository(session)
            active_directives = [
                {"id": d.id, "title": d.title, "status": d.status, "priority": d.priority}
                for d in dir_repo.get_active(empire_id)
            ]
            recent_completed = [
                {"id": d.id, "title": d.title, "quality": d.quality_score, "cost": d.total_cost_usd}
                for d in dir_repo.get_completed(empire_id, days=30, limit=5)
            ]

            # Budget
            budget_data = {}
            try:
                from core.routing.budget import BudgetManager
                bm = BudgetManager(empire_id)
                budget = bm.get_budget_report(days=30)
                budget_data = {
                    "daily_spend": budget.daily_spend,
                    "monthly_spend": budget.monthly_spend,
                    "daily_remaining": budget.daily_remaining,
                    "monthly_remaining": budget.monthly_remaining,
                    "alerts": [{"message": a.message, "severity": a.severity} for a in budget.alerts],
                }
            except Exception:
                pass

            # Fleet stats
            fleet_stats = []
            try:
                from db.repositories.lieutenant import LieutenantRepository
                lt_repo = LieutenantRepository(session)
                lts = lt_repo.get_by_empire(empire_id, status="active")
                fleet_stats = [
                    {
                        "name": lt.name,
                        "domain": lt.domain,
                        "performance": lt.performance_score,
                        "tasks": lt.tasks_completed + lt.tasks_failed,
                        "cost": lt.total_cost_usd,
                    }
                    for lt in sorted(lts, key=lambda x: x.performance_score, reverse=True)
                ]
            except Exception:
                pass

            # Latest research from memory
            latest_research = []
            try:
                from core.memory.manager import MemoryManager
                mm = MemoryManager(empire_id)
                research = mm.recall(query="research synthesis", memory_types=["semantic"], limit=5)
                latest_research = [
                    {
                        "title": getattr(r, "title", "") or getattr(r, "content", "")[:55],
                        "content": getattr(r, "content", ""),
                        "created_at": str(getattr(r, "created_at", "")),
                    }
                    for r in research
                ]
            except Exception:
                pass

            # Knowledge highlights
            knowledge_highlights = []
            try:
                from core.knowledge.graph import KnowledgeGraph
                graph = KnowledgeGraph(empire_id)
                central = graph.get_central_entities(limit=9)
                knowledge_highlights = [
                    {"name": n.name, "type": n.entity_type, "confidence": n.confidence}
                    for n in central
                ]
            except Exception:
                pass

            # Scheduler
            scheduler_info = {}
            try:
                daemon = current_app.config.get("_SCHEDULER_DAEMON")
                if daemon:
                    status = daemon.get_status()
                    scheduler_info = {
                        "running": status.running,
                        "total_ticks": status.total_ticks,
                        "total_jobs": status.total_job_runs,
                        "errors": status.errors,
                    }
            except Exception:
                pass

            # Infrastructure
            infra_stats = {}
            try:
                from llm.cache import get_cache
                infra_stats["cache"] = get_cache().get_stats()
            except Exception:
                infra_stats["cache"] = {"enabled": False}
            try:
                from utils.circuit_breaker import get_all_circuit_stats
                infra_stats["circuits"] = get_all_circuit_stats()
            except Exception:
                infra_stats["circuits"] = {}

            return jsonify({
                "health": health,
                "scheduler": scheduler_info,
                "fleet_stats": fleet_stats,
                "active_directives": active_directives,
                "recent_completed": recent_completed,
                "budget": budget_data,
                "latest_research": latest_research,
                "knowledge_highlights": knowledge_highlights,
                "infra": infra_stats,
            })
        finally:
            session.close()

    except Exception as e:
        return jsonify({"error": str(e)}), 500
