"""Knowledge graph routes."""

from __future__ import annotations

import logging
from flask import Blueprint, render_template, jsonify, request, current_app

logger = logging.getLogger(__name__)
knowledge_bp = Blueprint("knowledge", __name__)


@knowledge_bp.route("/")
def knowledge_overview():
    """Knowledge graph overview."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.knowledge.graph import KnowledgeGraph
        graph = KnowledgeGraph(empire_id)
        stats = graph.get_stats()
        central = graph.get_central_entities(limit=10)
        return render_template("knowledge/overview.html", stats=stats.__dict__,
                             central_entities=[{"name": n.name, "type": n.entity_type, "importance": n.importance} for n in central])
    except Exception as e:
        return render_template("knowledge/overview.html", stats={}, central_entities=[], error=str(e))


@knowledge_bp.route("/entities")
def list_entities():
    """List knowledge entities."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    entity_type = request.args.get("type")
    query = request.args.get("q", "")
    try:
        from core.knowledge.graph import KnowledgeGraph
        graph = KnowledgeGraph(empire_id)
        entities = graph.find_entities(query=query, entity_type=entity_type or "", limit=50)
        return render_template("knowledge/entities.html", entities=[
            {"id": e.entity_id, "name": e.name, "type": e.entity_type, "confidence": e.confidence, "importance": e.importance}
            for e in entities
        ])
    except Exception as e:
        return render_template("knowledge/entities.html", entities=[], error=str(e))


@knowledge_bp.route("/entity/<entity_name>")
def entity_detail(entity_name: str):
    """Entity detail with neighborhood graph."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.knowledge.graph import KnowledgeGraph
        graph = KnowledgeGraph(empire_id)
        neighbors = graph.get_neighbors(entity_name, max_depth=2)
        subgraph = graph.get_subgraph(entity_name, depth=2)
        return render_template("knowledge/entity.html", entity_name=entity_name,
                             neighbors=[{"name": n.name, "type": n.entity_type, "depth": n.depth} for n in neighbors],
                             subgraph={"nodes": len(subgraph.nodes), "edges": len(subgraph.edges)})
    except Exception as e:
        return str(e), 500


@knowledge_bp.route("/graph/export")
def export_graph():
    """Export knowledge graph."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.graph import KnowledgeGraph
    graph = KnowledgeGraph(empire_id)
    return jsonify(graph.export_graph())


@knowledge_bp.route("/maintenance", methods=["POST"])
def run_maintenance():
    """Run knowledge maintenance."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.maintenance import KnowledgeMaintainer
    maintainer = KnowledgeMaintainer(empire_id)
    report = maintainer.run_maintenance()
    return jsonify({"health_score": report.health_score, "entities": report.entity_count,
                    "recommendations": report.recommendations})


@knowledge_bp.route("/gaps")
def knowledge_gaps():
    """Get knowledge gaps."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.maintenance import KnowledgeMaintainer
    maintainer = KnowledgeMaintainer(empire_id)
    gaps = maintainer.suggest_gaps()
    return jsonify([{"topic": g.topic, "importance": g.importance, "queries": g.suggested_queries} for g in gaps])
