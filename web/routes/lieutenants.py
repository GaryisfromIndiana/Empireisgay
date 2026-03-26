"""Lieutenant management routes."""

from __future__ import annotations

import logging

from flask import Blueprint, render_template, jsonify, request, current_app

logger = logging.getLogger(__name__)

lieutenants_bp = Blueprint("lieutenants", __name__)


@lieutenants_bp.route("/")
def list_lieutenants():
    """List all lieutenants."""
    empire_id = current_app.config.get("EMPIRE_ID", "")

    try:
        from core.lieutenant.manager import LieutenantManager
        manager = LieutenantManager(empire_id)

        status_filter = request.args.get("status")
        domain_filter = request.args.get("domain")

        lieutenants = manager.list_lieutenants(status=status_filter, domain=domain_filter)
        fleet_stats = manager.get_fleet_stats()

        return render_template(
            "lieutenants/list.html",
            lieutenants=lieutenants,
            fleet_stats=fleet_stats.__dict__,
        )
    except Exception as e:
        logger.error("Lieutenant list error: %s", e)
        return render_template("lieutenants/list.html", lieutenants=[], error=str(e))


@lieutenants_bp.route("/<lieutenant_id>")
def lieutenant_detail(lieutenant_id: str):
    """Lieutenant detail page."""
    empire_id = current_app.config.get("EMPIRE_ID", "")

    try:
        from core.lieutenant.manager import LieutenantManager
        from db.engine import get_session
        from db.repositories.lieutenant import LieutenantRepository

        session = get_session()
        try:
            repo = LieutenantRepository(session)

            lt = repo.get(lieutenant_id)
            if not lt:
                return "Lieutenant not found", 404

            task_stats = repo.get_task_stats(lieutenant_id)
            cost_breakdown = repo.get_cost_breakdown(lieutenant_id)

            return render_template(
                "lieutenants/detail.html",
                lieutenant={
                    "id": lt.id, "name": lt.name, "domain": lt.domain,
                    "status": lt.status, "performance": lt.performance_score,
                    "tasks_completed": lt.tasks_completed, "tasks_failed": lt.tasks_failed,
                    "total_cost": lt.total_cost_usd, "avg_quality": lt.avg_quality_score,
                    "persona": lt.persona_json,
                    "specializations": lt.specializations_json,
                    "last_active": lt.last_active_at.isoformat() if lt.last_active_at else None,
                },
                task_stats=task_stats,
                cost_breakdown=cost_breakdown,
            )
        finally:
            session.close()
    except Exception as e:
        logger.error("Lieutenant detail error: %s", e)
        return str(e), 500


@lieutenants_bp.route("/create", methods=["POST"])
def create_lieutenant():
    """Create a new lieutenant."""
    empire_id = current_app.config.get("EMPIRE_ID", "")

    try:
        data = request.get_json()
        from core.lieutenant.manager import LieutenantManager
        manager = LieutenantManager(empire_id)

        lt = manager.create_lieutenant(
            name=data.get("name", ""),
            template=data.get("template", ""),
            domain=data.get("domain", ""),
        )

        return jsonify({"id": lt.id, "name": lt.name, "domain": lt.domain}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@lieutenants_bp.route("/<lieutenant_id>/activate", methods=["POST"])
def activate_lieutenant(lieutenant_id: str):
    """Activate a lieutenant."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.lieutenant.manager import LieutenantManager
    manager = LieutenantManager(empire_id)
    success = manager.activate_lieutenant(lieutenant_id)
    return jsonify({"success": success})


@lieutenants_bp.route("/<lieutenant_id>/deactivate", methods=["POST"])
def deactivate_lieutenant(lieutenant_id: str):
    """Deactivate a lieutenant."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.lieutenant.manager import LieutenantManager
    manager = LieutenantManager(empire_id)
    success = manager.deactivate_lieutenant(lieutenant_id)
    return jsonify({"success": success})


@lieutenants_bp.route("/<lieutenant_id>/delete", methods=["DELETE"])
def delete_lieutenant(lieutenant_id: str):
    """Delete a lieutenant."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.lieutenant.manager import LieutenantManager
    manager = LieutenantManager(empire_id)
    success = manager.delete_lieutenant(lieutenant_id)
    return jsonify({"success": success})


@lieutenants_bp.route("/<lieutenant_id>/research", methods=["POST"])
def lieutenant_research(lieutenant_id: str):
    """Trigger research for a lieutenant."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json()
    topic = data.get("topic", "")

    if not topic:
        return jsonify({"error": "Topic required"}), 400

    try:
        from core.lieutenant.manager import LieutenantManager
        manager = LieutenantManager(empire_id)
        lt = manager.get_lieutenant(lieutenant_id)

        if not lt:
            return jsonify({"error": "Lieutenant not found"}), 404

        result = lt.research(topic, depth=data.get("depth", "standard"))
        return jsonify(result.to_dict())

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@lieutenants_bp.route("/templates")
def persona_templates():
    """Get available persona templates."""
    from core.lieutenant.persona import list_persona_templates, PERSONA_TEMPLATES
    templates = []
    for name in list_persona_templates():
        t = PERSONA_TEMPLATES[name]
        templates.append({
            "key": name,
            "name": t.name,
            "role": t.role,
            "domain": t.domain,
            "expertise": t.expertise_areas,
            "style": t.communication_style,
        })
    return jsonify(templates)
