"""Empire replication and network routes."""

from __future__ import annotations

import logging
from flask import Blueprint, render_template, jsonify, request, current_app

logger = logging.getLogger(__name__)
replication_bp = Blueprint("replication", __name__)


@replication_bp.route("/")
def network_overview():
    """Empire network overview."""
    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        session = get_session()
        try:
            repo = EmpireRepository(session)
            network = repo.get_network_stats()
            capability_map = repo.get_capability_map()

            return render_template("replication/network.html",
                network=network,
                capability_map=capability_map,
            )
        finally:
            session.close()
    except Exception as e:
        return render_template("replication/network.html", network={}, capability_map={}, error=str(e))


@replication_bp.route("/empires")
def list_empires():
    """List all empires in the network."""
    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        session = get_session()
        try:
            repo = EmpireRepository(session)
            empires = repo.get_active()
            return jsonify([
                {"id": e.id, "name": e.name, "domain": e.domain, "status": e.status,
                 "tasks": e.total_tasks_completed, "cost": e.total_cost_usd, "knowledge": e.total_knowledge_entries}
                for e in empires
            ])
        finally:
            session.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@replication_bp.route("/generate", methods=["POST"])
def generate_empire():
    """Generate a new empire from a template."""
    data = request.get_json()
    try:
        from core.replication.generator import EmpireGenerator
        gen = EmpireGenerator()
        result = gen.generate_empire(
            name=data.get("name", ""),
            template=data.get("template", ""),
            domain=data.get("domain", "general"),
            description=data.get("description", ""),
        )
        return jsonify({
            "empire_id": result.empire_id,
            "lieutenants": result.lieutenants_created,
            "ready": result.launch_ready,
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@replication_bp.route("/templates")
def list_templates():
    """List available empire templates."""
    from core.replication.generator import EmpireGenerator
    gen = EmpireGenerator()
    return jsonify(gen.get_templates())


@replication_bp.route("/clone", methods=["POST"])
def clone_empire():
    """Clone an existing empire."""
    data = request.get_json()
    try:
        from core.replication.generator import EmpireGenerator
        gen = EmpireGenerator()
        result = gen.clone_empire(
            source_empire_id=data.get("source_id", ""),
            new_name=data.get("name", ""),
        )
        return jsonify({"empire_id": result.empire_id, "lieutenants": result.lieutenants_created}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@replication_bp.route("/sync", methods=["POST"])
def sync_empires():
    """Trigger cross-empire knowledge sync."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json()
    target_id = data.get("target_empire_id", "")

    try:
        from core.knowledge.bridge import KnowledgeBridge
        bridge = KnowledgeBridge()
        result = bridge.sync_to(empire_id, target_id)
        return jsonify({
            "entities_synced": result.entities_synced,
            "relations_synced": result.relations_synced,
            "success": result.success,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@replication_bp.route("/sync-status")
def sync_status():
    """Get sync status with other empires."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.knowledge.bridge import KnowledgeBridge
        bridge = KnowledgeBridge()
        statuses = bridge.get_sync_status(empire_id)
        return jsonify([s.__dict__ for s in statuses])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
