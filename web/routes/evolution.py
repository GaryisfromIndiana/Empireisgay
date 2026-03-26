"""Evolution system routes."""

from __future__ import annotations

import logging
from flask import Blueprint, render_template, jsonify, request, current_app

logger = logging.getLogger(__name__)
evolution_bp = Blueprint("evolution", __name__)


@evolution_bp.route("/")
def evolution_overview():
    """Evolution overview page."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.evolution.cycle import EvolutionCycleManager
        ecm = EvolutionCycleManager(empire_id)
        history = ecm.get_cycle_history()
        stats = ecm.get_stats()
        return render_template("evolution/overview.html", history=history, stats=stats.__dict__)
    except Exception as e:
        return render_template("evolution/overview.html", history=[], stats={}, error=str(e))


@evolution_bp.route("/proposals")
def list_proposals():
    """List evolution proposals."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    status_filter = request.args.get("status")
    try:
        from db.engine import get_session
        from db.repositories.evolution import EvolutionRepository
        session = get_session()
        try:
            repo = EvolutionRepository(session)
            proposals = repo.get_by_empire(empire_id, status=status_filter)
            return render_template("evolution/proposals.html", proposals=[
                {"id": p.id, "title": p.title, "type": p.proposal_type, "status": p.review_status,
                 "confidence": p.confidence_score, "lieutenant_id": p.lieutenant_id,
                 "created_at": p.created_at.isoformat() if p.created_at else None}
                for p in proposals
            ])
        finally:
            session.close()
    except Exception as e:
        return render_template("evolution/proposals.html", proposals=[], error=str(e))


@evolution_bp.route("/run-cycle", methods=["POST"])
def run_cycle():
    """Manually trigger an evolution cycle."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.evolution.cycle import EvolutionCycleManager
        ecm = EvolutionCycleManager(empire_id)
        if not ecm.should_run_cycle():
            return jsonify({"error": "Cycle cooldown active"}), 429
        result = ecm.run_full_cycle()
        return jsonify({
            "cycle_id": result.cycle_id, "proposals": result.proposals_collected,
            "approved": result.approved, "applied": result.applied,
            "learnings": result.learnings,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@evolution_bp.route("/stats")
def evolution_stats():
    """Get evolution statistics."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.evolution.cycle import EvolutionCycleManager
    ecm = EvolutionCycleManager(empire_id)
    stats = ecm.get_stats()
    return jsonify(stats.__dict__)


@evolution_bp.route("/trend")
def evolution_trend():
    """Get improvement trend data."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from db.engine import get_session
        from db.repositories.evolution import EvolutionRepository
        session = get_session()
        try:
            repo = EvolutionRepository(session)
            trend = repo.get_improvement_trend(empire_id)
            return jsonify(trend)
        finally:
            session.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
