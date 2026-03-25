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

        context = {
            "health": health,
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
        }

        return render_template("dashboard.html", **context)

    except Exception as e:
        logger.error("Dashboard error: %s", e)
        return render_template("dashboard.html", error=str(e))


@dashboard_bp.route("/api/dashboard/stats")
def dashboard_stats():
    """Dashboard stats API endpoint."""
    empire_id = current_app.config.get("EMPIRE_ID", "")

    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        session = get_session()
        repo = EmpireRepository(session)

        health = repo.get_health_overview(empire_id)
        network = repo.get_network_stats()

        return jsonify({
            "health": health,
            "network": network,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
