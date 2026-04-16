"""Dashboard routes — main overview page."""

from __future__ import annotations

import logging
from datetime import UTC

from flask import Blueprint, current_app, jsonify, render_template
from sqlalchemy import and_, func, select

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)


def _fetch_dashboard_data(empire_id: str) -> dict:
    """Collect all dashboard data. Shared by HTML and JSON endpoints."""
    from db.engine import read_session
    from db.repositories.directive import DirectiveRepository
    from db.repositories.empire import EmpireRepository

    with read_session() as session:
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
        except Exception as e:
            logger.debug("Dashboard budget fetch failed: %s", e)

        # Fleet stats
        fleet_stats = []
        try:
            from db.repositories.lieutenant import LieutenantRepository
            lt_repo = LieutenantRepository(session)
            lts = lt_repo.get_by_empire(empire_id, status="active")
            real_costs = lt_repo.get_real_costs_bulk([lt.id for lt in lts])
            fleet_stats = [
                {
                    "name": lt.name,
                    "domain": lt.domain,
                    "performance": lt.performance_score,
                    "tasks": lt.tasks_completed + lt.tasks_failed,
                    "cost": real_costs.get(lt.id, 0.0),
                }
                for lt in sorted(lts, key=lambda x: x.performance_score, reverse=True)
            ]
        except Exception as e:
            logger.debug("Dashboard fleet stats failed: %s", e)

        # Latest research from memory — cheap DB query, not vector recall.
        # Dashboard is polled every 30s by the browser; the old mm.recall call
        # hit _vector_search_fallback which loaded hundreds of embedded rows
        # per hit. That was the single biggest contributor to OOM kills.
        latest_research = []
        latest_feeds = []
        recent_discoveries = []
        try:
            from db.models import MemoryEntry
            stmt = (
                select(MemoryEntry)
                .where(and_(
                    MemoryEntry.empire_id == empire_id,
                    MemoryEntry.memory_type == "semantic",
                    MemoryEntry.category.in_(["research_pipeline", "synthesis", "research"]),
                ))
                .order_by(MemoryEntry.created_at.desc())
                .limit(5)
            )
            rows = session.execute(stmt).scalars().all()
            latest_research = [
                {
                    "id": m.id,
                    "title": m.title,
                    "content": (m.content or "")[:500],
                    "category": m.category,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in rows
            ]

            # Keep dashboard render local/read-only.
            # Feed and discovery panels should reflect stored state instead of
            # triggering live fetches during page load or polling.
            feed_rows = session.execute(
                select(MemoryEntry)
                .where(and_(
                    MemoryEntry.empire_id == empire_id,
                    MemoryEntry.memory_type == "semantic",
                    MemoryEntry.title.like("Feed:%"),
                ))
                .order_by(MemoryEntry.created_at.desc())
                .limit(5)
            ).scalars().all()
            latest_feeds = [
                {
                    "title": (m.title or "Feed entry").removeprefix("Feed: ").strip(),
                    "url": (m.metadata_json or {}).get("url", ""),
                    "summary": (m.content or "")[:300],
                    "source": (m.metadata_json or {}).get("source_feed", "stored"),
                }
                for m in feed_rows
            ]

            discovery_rows = session.execute(
                select(MemoryEntry)
                .where(and_(
                    MemoryEntry.empire_id == empire_id,
                    MemoryEntry.memory_type == "semantic",
                    MemoryEntry.title.like("Discovery:%"),
                ))
                .order_by(MemoryEntry.created_at.desc())
                .limit(5)
            ).scalars().all()
            recent_discoveries = [
                {
                    "id": m.id,
                    "title": m.title,
                    "content": (m.content or "")[:500],
                    "category": m.category,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in discovery_rows
            ]
        except Exception as e:
            logger.debug("Dashboard memory fetch failed: %s", e)

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
        except Exception as e:
            logger.debug("Dashboard knowledge fetch failed: %s", e)

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
            if not scheduler_info.get("total_ticks"):
                try:
                    from datetime import datetime, timedelta

                    from db.models import Task, WarRoom
                    one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
                    tick_check = session.execute(select(func.count(WarRoom.id)).where(
                        WarRoom.created_at > one_hour_ago
                    )).scalar() or 0
                    task_check = session.execute(select(func.count(Task.id)).where(
                        Task.created_at > one_hour_ago
                    )).scalar() or 0
                    if tick_check or task_check:
                        scheduler_info["running"] = True
                        scheduler_info["note"] = "Activity detected (stats from another worker)"
                        scheduler_info["recent_war_rooms"] = tick_check
                        scheduler_info["recent_tasks"] = task_check
                except Exception as e:
                    logger.debug("Dashboard tick check failed: %s", e)
        except Exception as e:
            logger.debug("Dashboard scheduler fetch failed: %s", e)

        # Infrastructure stats
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

    return {
        "health": health,
        "scheduler": scheduler_info,
        "fleet_stats": fleet_stats,
        "active_directives": active_directives,
        "recent_completed": recent_completed,
        "budget": budget_data,
        "latest_research": latest_research,
        "latest_feeds": latest_feeds,
        "recent_discoveries": recent_discoveries,
        "knowledge_highlights": knowledge_highlights,
        "infra": infra_stats,
    }


@dashboard_bp.route("/")
def index():
    """Main dashboard page."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        data = _fetch_dashboard_data(empire_id)
        return render_template("dashboard.html", **data)

    except Exception as e:
        logger.error("Dashboard error: %s", e)
        return render_template("dashboard.html", error=str(e))


@dashboard_bp.route("/api/dashboard/stats")
def dashboard_stats():
    """Full dashboard stats as JSON for live refresh."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        return jsonify(_fetch_dashboard_data(empire_id))
    except Exception as e:
        logger.error("API error: %s", e)
        return jsonify({"error": "Internal server error"}), 500
