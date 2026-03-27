"""REST API routes for programmatic access to Empire."""

from __future__ import annotations

import logging
import time
import json
import urllib.request
from flask import Blueprint, jsonify, request, current_app
from web.middleware.rate_limit import rate_limit

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__)


def _dbg_emit(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "b41917",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        req = urllib.request.Request(
            "http://127.0.0.1:7339/ingest/2b050dc4-4b68-4382-a7fb-1f2a2fa0d88e",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Debug-Session-Id": "b41917"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=1.0).read()
    except Exception:
        pass
    # #endregion


def _get_json_or_400() -> dict:
    """Get JSON body or abort with 400."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        from flask import abort
        abort(400, description="Request body must be valid JSON")
    return data


# ── Empire ─────────────────────────────────────────────────────────────

@api_bp.route("/empire")
def get_empire():
    """Get current empire info."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    _dbg_emit(
        run_id="runtime-3",
        hypothesis_id="H7",
        location="web/routes/api.py:get_empire",
        message="api empire endpoint hit",
        data={"empire_id": empire_id},
    )
    # #region agent log
    try:
        import json as _json, time as _time, os as _os
        _os.makedirs("/Users/asd/Downloads/Empireisgay-main/.cursor", exist_ok=True)
        with open("/Users/asd/Downloads/Empireisgay-main/.cursor/debug-b41917.log", "a", encoding="utf-8") as _f:
            _f.write(_json.dumps({
                "sessionId": "b41917",
                "runId": "runtime-2",
                "hypothesisId": "H7",
                "location": "web/routes/api.py:get_empire",
                "message": "api empire endpoint hit",
                "data": {"empire_id": empire_id},
                "timestamp": int(_time.time() * 1000),
            }) + "\n")
    except Exception:
        pass
    # #endregion
    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        session = get_session()
        try:
            repo = EmpireRepository(session)
            health = repo.get_health_overview(empire_id)
            return jsonify(health)
        finally:
            session.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/empire/network")
def get_network():
    """Get network stats across all empires."""
    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        session = get_session()
        try:
            repo = EmpireRepository(session)
            return jsonify(repo.get_network_stats())
        finally:
            session.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Lieutenants ────────────────────────────────────────────────────────

@api_bp.route("/lieutenants")
def api_list_lieutenants():
    """List all lieutenants."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.lieutenant.manager import LieutenantManager
    manager = LieutenantManager(empire_id)
    return jsonify(manager.list_lieutenants(
        status=request.args.get("status"),
        domain=request.args.get("domain"),
    ))


@api_bp.route("/lieutenants/gaps")
def api_lieutenant_gaps():
    """Detect topic clusters that need new specialist lieutenants."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.maintenance import KnowledgeMaintainer
    maintainer = KnowledgeMaintainer(empire_id)
    gaps = maintainer.detect_lieutenant_gaps(min_cluster_size=5)
    return jsonify({"gaps": gaps, "count": len(gaps)})


@api_bp.route("/lieutenants/auto-spawn", methods=["POST"])
@rate_limit(requests_per_minute=2, requests_per_hour=5)
def api_auto_spawn():
    """Auto-spawn lieutenants for uncovered topic clusters."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    max_spawns = data.get("max_spawns", 2)
    from core.knowledge.maintenance import KnowledgeMaintainer
    maintainer = KnowledgeMaintainer(empire_id)
    spawned = maintainer.auto_spawn_lieutenants(max_spawns=min(max_spawns, 5))
    return jsonify({"spawned": spawned, "count": len(spawned)})


@api_bp.route("/lieutenants", methods=["POST"])
def api_create_lieutenant():
    """Create a lieutenant."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    from core.lieutenant.manager import LieutenantManager
    manager = LieutenantManager(empire_id)
    lt = manager.create_lieutenant(
        name=data.get("name", ""),
        template=data.get("template", ""),
        domain=data.get("domain", ""),
    )
    return jsonify({"id": lt.id, "name": lt.name, "domain": lt.domain}), 201


@api_bp.route("/lieutenants/<lt_id>/task", methods=["POST"])
def api_lieutenant_task(lt_id: str):
    """Submit a task to a lieutenant."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    from core.lieutenant.manager import LieutenantManager
    from core.ace.engine import TaskInput
    manager = LieutenantManager(empire_id)
    lt = manager.get_lieutenant(lt_id)
    if not lt:
        return jsonify({"error": "Lieutenant not found"}), 404
    task = TaskInput(title=data.get("title", ""), description=data.get("description", ""), task_type=data.get("type", "general"))
    result = lt.execute_task(task)
    return jsonify(result.to_dict())


# ── Directives ─────────────────────────────────────────────────────────

@api_bp.route("/directives")
def api_list_directives():
    """List directives."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.directives.manager import DirectiveManager
    dm = DirectiveManager(empire_id)
    return jsonify(dm.list_directives(status=request.args.get("status")))


@api_bp.route("/directives", methods=["POST"])
def api_create_directive():
    """Create a directive."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    from core.directives.manager import DirectiveManager
    dm = DirectiveManager(empire_id)
    result = dm.create_directive(
        title=data.get("title", ""),
        description=data.get("description", ""),
        priority=data.get("priority", 5),
    )
    return jsonify(result), 201


@api_bp.route("/directives/<directive_id>/execute", methods=["POST"])
@rate_limit(requests_per_minute=5, requests_per_hour=50)
def api_execute_directive(directive_id: str):
    """Execute a directive in a background thread.

    Returns immediately with status. Poll /directives/<id>/progress for updates.
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    app = current_app._get_current_object()
    import threading
    _dbg_emit(
        run_id="runtime-3",
        hypothesis_id="H10",
        location="web/routes/api.py:api_execute_directive:entry",
        message="execute directive endpoint hit",
        data={"directive_id": directive_id, "empire_id": empire_id},
    )

    def run_directive(app_ref, eid, did):
        with app_ref.app_context():
            from core.directives.manager import DirectiveManager
            dm = DirectiveManager(eid)
            _dbg_emit(
                run_id="runtime-3",
                hypothesis_id="H5",
                location="web/routes/api.py:api_execute_directive:thread_start",
                message="background directive thread started",
                data={"directive_id": did, "empire_id": eid},
            )
            # #region agent log
            try:
                import json as _json, time as _time
                __import__("os").makedirs("/Users/asd/Downloads/Empireisgay-main/.cursor", exist_ok=True)
                with open("/Users/asd/Downloads/Empireisgay-main/.cursor/debug-b41917.log", "a", encoding="utf-8") as _f:
                    _f.write(_json.dumps({
                        "sessionId": "b41917",
                        "runId": "runtime-1",
                        "hypothesisId": "H5",
                        "location": "web/routes/api.py:api_execute_directive:thread_start",
                        "message": "background directive thread started",
                        "data": {"directive_id": did, "empire_id": eid},
                        "timestamp": int(_time.time() * 1000),
                    }) + "\n")
            except Exception:
                pass
            # #endregion
            try:
                dm.execute_directive(did)
                _dbg_emit(
                    run_id="runtime-3",
                    hypothesis_id="H5",
                    location="web/routes/api.py:api_execute_directive:thread_done",
                    message="background directive thread completed",
                    data={"directive_id": did},
                )
                # #region agent log
                try:
                    import json as _json, time as _time
                    __import__("os").makedirs("/Users/asd/Downloads/Empireisgay-main/.cursor", exist_ok=True)
                    with open("/Users/asd/Downloads/Empireisgay-main/.cursor/debug-b41917.log", "a", encoding="utf-8") as _f:
                        _f.write(_json.dumps({
                            "sessionId": "b41917",
                            "runId": "runtime-1",
                            "hypothesisId": "H5",
                            "location": "web/routes/api.py:api_execute_directive:thread_done",
                            "message": "background directive thread completed",
                            "data": {"directive_id": did},
                            "timestamp": int(_time.time() * 1000),
                        }) + "\n")
                except Exception:
                    pass
                # #endregion
            except Exception as e:
                import logging
                logging.getLogger(__name__).error("Directive execution failed: %s", e)
                _dbg_emit(
                    run_id="runtime-3",
                    hypothesis_id="H5",
                    location="web/routes/api.py:api_execute_directive:thread_error",
                    message="background directive thread failed",
                    data={"directive_id": did, "error": str(e)[:240]},
                )
                # #region agent log
                try:
                    import json as _json, time as _time
                    __import__("os").makedirs("/Users/asd/Downloads/Empireisgay-main/.cursor", exist_ok=True)
                    with open("/Users/asd/Downloads/Empireisgay-main/.cursor/debug-b41917.log", "a", encoding="utf-8") as _f:
                        _f.write(_json.dumps({
                            "sessionId": "b41917",
                            "runId": "runtime-1",
                            "hypothesisId": "H5",
                            "location": "web/routes/api.py:api_execute_directive:thread_error",
                            "message": "background directive thread failed",
                            "data": {"directive_id": did, "error": str(e)[:240]},
                            "timestamp": int(_time.time() * 1000),
                        }) + "\n")
                except Exception:
                    pass
                # #endregion

    thread = threading.Thread(
        target=run_directive,
        args=(app, empire_id, directive_id),
        daemon=True,
        name=f"directive-{directive_id[:8]}"
    )
    thread.start()

    return jsonify({"directive_id": directive_id, "status": "started", "message": "Executing in background. Poll /api/directives/{id}/progress for updates."}), 202


@api_bp.route("/directives/<directive_id>/progress")
def api_directive_progress(directive_id: str):
    """Get directive progress."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.directives.manager import DirectiveManager
    dm = DirectiveManager(empire_id)
    return jsonify(dm.get_progress(directive_id).__dict__)


@api_bp.route("/directives/<directive_id>/report")
def api_directive_report(directive_id: str):
    """Get the full output/report from a completed directive."""
    try:
        from db.engine import get_session
        from db.repositories.directive import DirectiveRepository
        from db.repositories.task import TaskRepository

        session = get_session()
        try:
            dir_repo = DirectiveRepository(session)
            task_repo = TaskRepository(session)

            directive = dir_repo.get(directive_id)
            if not directive:
                return jsonify({"error": "Directive not found"}), 404

            # Get all tasks with their output
            tasks = task_repo.get_by_directive(directive_id)

            # Build report
            report_sections = []
            for task in tasks:
                output = task.output_json or {}
                content = output.get("content", "")
                if content:
                    report_sections.append({
                        "title": task.title,
                        "wave": task.wave_number,
                        "lieutenant": task.lieutenant_id,
                        "status": task.status,
                        "quality_score": task.quality_score,
                        "cost_usd": task.cost_usd,
                        "content": content,
                    })

            # Get war room synthesis
            from db.models import WarRoom
            from sqlalchemy import select, desc
            war_rooms = list(session.execute(
                select(WarRoom).where(WarRoom.directive_id == directive_id).order_by(desc(WarRoom.created_at))
            ).scalars().all())

            synthesis = {}
            if war_rooms:
                synthesis = war_rooms[0].synthesis_json or {}

            return jsonify({
                "directive": {
                    "id": directive.id,
                    "title": directive.title,
                    "description": directive.description,
                    "status": directive.status,
                    "total_cost": directive.total_cost_usd,
                    "quality_score": directive.quality_score,
                    "created_at": directive.created_at.isoformat() if directive.created_at else None,
                    "completed_at": directive.completed_at.isoformat() if directive.completed_at else None,
                },
                "sections": report_sections,
                "total_sections": len(report_sections),
                "war_room_synthesis": synthesis,
            })
        finally:
            session.close()

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/reports/latest")
def api_latest_reports():
    """Get the latest research reports."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from db.engine import get_session
        from db.repositories.directive import DirectiveRepository
        session = get_session()
        try:
            repo = DirectiveRepository(session)
            completed = repo.get_completed(empire_id, days=30, limit=10)

            reports = []
            for d in completed:
                reports.append({
                    "id": d.id,
                    "title": d.title,
                    "status": d.status,
                    "quality_score": d.quality_score,
                    "total_cost": d.total_cost_usd,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "completed_at": d.completed_at.isoformat() if d.completed_at else None,
                    "report_url": f"/api/directives/{d.id}/report",
                })
        finally:
            session.close()

        # Also include recent research from memory
        from core.memory.manager import MemoryManager
        mm = MemoryManager(empire_id)
        research_memories = mm.recall(
            query="research synthesis",
            memory_types=["semantic"],
            limit=10,
        )

        return jsonify({
            "directive_reports": reports,
            "research_entries": research_memories,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Knowledge ──────────────────────────────────────────────────────────

@api_bp.route("/knowledge/stats")
def api_knowledge_stats():
    """Get knowledge graph stats."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.graph import KnowledgeGraph
    graph = KnowledgeGraph(empire_id)
    return jsonify(graph.get_stats().__dict__)


@api_bp.route("/knowledge/entities")
def api_knowledge_entities():
    """Search knowledge entities."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.graph import KnowledgeGraph
    graph = KnowledgeGraph(empire_id)
    entities = graph.find_entities(
        query=request.args.get("q", ""),
        entity_type=request.args.get("type", ""),
        limit=request.args.get("limit", 20, type=int),
    )
    return jsonify([{"name": e.name, "type": e.entity_type, "confidence": e.confidence, "importance": e.importance} for e in entities])


@api_bp.route("/knowledge/entity/<entity_name>/neighbors")
def api_entity_neighbors(entity_name: str):
    """Get entity neighbors."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.graph import KnowledgeGraph
    graph = KnowledgeGraph(empire_id)
    neighbors = graph.get_neighbors(entity_name, max_depth=request.args.get("depth", 2, type=int))
    return jsonify([{"name": n.name, "type": n.entity_type, "depth": n.depth} for n in neighbors])


@api_bp.route("/knowledge/ask")
def api_knowledge_ask():
    """Ask the knowledge graph a question."""
    question = request.args.get("q", "")
    _dbg_emit(
        run_id="runtime-3",
        hypothesis_id="H10",
        location="web/routes/api.py:api_knowledge_ask:entry",
        message="knowledge ask endpoint hit",
        data={"question_len": len(question)},
    )
    if not question:
        return jsonify({"error": "Query parameter 'q' required"}), 400
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.query import KnowledgeQuerier
    querier = KnowledgeQuerier(empire_id)
    answer = querier.ask(question)
    return jsonify({
        "query": answer.query,
        "entity": answer.entity_name,
        "type": answer.entity_type,
        "description": answer.description,
        "attributes": {k: v for k, v in (answer.attributes or {}).items() if not str(k).startswith("_")},
        "relations": answer.relations[:15],
        "related_entities": answer.related_entities[:10],
        "facts": [f.get("content", "")[:300] for f in answer.facts_from_memory[:5]],
        "quality_score": answer.quality_score,
        "confidence": answer.confidence,
        "sources": answer.sources,
    })


@api_bp.route("/knowledge/profile/<entity_name>")
def api_knowledge_profile(entity_name: str):
    """Get structured knowledge profile for an entity."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.query import KnowledgeQuerier
    return jsonify(KnowledgeQuerier(empire_id).ask_structured(entity_name))


@api_bp.route("/knowledge/compare")
def api_knowledge_compare():
    """Compare two entities."""
    a = request.args.get("a", "")
    b = request.args.get("b", "")
    if not a or not b:
        return jsonify({"error": "Parameters 'a' and 'b' required"}), 400
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.query import KnowledgeQuerier
    return jsonify(KnowledgeQuerier(empire_id).compare(a, b))


@api_bp.route("/knowledge/schemas")
def api_knowledge_schemas():
    """List all entity type schemas."""
    from core.knowledge.schemas import list_schemas
    return jsonify(list_schemas())


@api_bp.route("/knowledge/quality")
def api_knowledge_quality():
    """Get quality scores for knowledge entities."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.quality import EntityQualityScorer
    scorer = EntityQualityScorer(empire_id)
    stats = scorer.get_quality_stats()
    return jsonify(stats)


@api_bp.route("/knowledge/audit", methods=["POST"])
@rate_limit(requests_per_minute=2, requests_per_hour=10)
def api_knowledge_audit():
    """Deep LLM audit for contaminated/hallucinated entities."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    batch_size = data.get("batch_size", 20)
    from core.knowledge.maintenance import KnowledgeMaintainer
    maintainer = KnowledgeMaintainer(empire_id)
    result = maintainer.deep_llm_audit(batch_size=min(batch_size, 50))
    return jsonify(result)


@api_bp.route("/knowledge/duplicates")
def api_knowledge_duplicates():
    """Find duplicate entities."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.resolution import EntityResolver
    resolver = EntityResolver(empire_id)
    groups = resolver.find_duplicates()
    return jsonify([
        {"entities": group, "count": len(group)}
        for group in groups
    ])


@api_bp.route("/knowledge/merge-duplicates", methods=["POST"])
def api_merge_duplicates():
    """Find and merge all duplicate entities."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.resolution import EntityResolver
    resolver = EntityResolver(empire_id)
    merged = resolver.merge_duplicates()
    return jsonify({"merged": merged})


# ── Memory ─────────────────────────────────────────────────────────────

@api_bp.route("/memory/stats")
def api_memory_stats():
    """Get memory stats."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.memory.manager import MemoryManager
    mm = MemoryManager(empire_id)
    return jsonify(mm.get_stats().__dict__)


@api_bp.route("/memory/compress", methods=["POST"])
def api_compress_memories():
    """Run memory compression — distill clusters into concise knowledge."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.memory.compression import MemoryCompressor
    compressor = MemoryCompressor(empire_id)
    result = compressor.run_compression()
    return jsonify({
        "clusters_found": result.clusters_found,
        "clusters_compressed": result.clusters_compressed,
        "memories_consumed": result.memories_consumed,
        "summaries_created": result.summaries_created,
        "compression_ratio": f"{result.compression_ratio:.0%}",
        "cost_usd": result.cost_usd,
    })


@api_bp.route("/memory/compress/topic", methods=["POST"])
def api_compress_topic():
    """Compress all memories about a specific topic."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "Topic required"}), 400
    from core.memory.compression import MemoryCompressor
    compressor = MemoryCompressor(empire_id)
    result = compressor.compress_by_topic(topic)
    if result:
        return jsonify(result)
    return jsonify({"error": f"Not enough memories about '{topic}' to compress (need 3+)"})


@api_bp.route("/memory/compress/stats")
def api_compression_stats():
    """Get compression statistics."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.memory.compression import MemoryCompressor
    compressor = MemoryCompressor(empire_id)
    return jsonify(compressor.get_compression_stats())


@api_bp.route("/memory/temporal/store", methods=["POST"])
def api_store_temporal():
    """Store a bi-temporal fact."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    from core.memory.bitemporal import BiTemporalMemory
    bt = BiTemporalMemory(empire_id)
    fact = bt.store_fact(
        content=data.get("content", ""),
        title=data.get("title", ""),
        category=data.get("category", ""),
        valid_from=data.get("valid_from"),
        valid_to=data.get("valid_to"),
        confidence=data.get("confidence", 0.8),
        importance=data.get("importance", 0.6),
        source=data.get("source", ""),
        source_url=data.get("source_url", ""),
        tags=data.get("tags", []),
        entity_refs=data.get("entity_refs", []),
    )
    return jsonify({
        "id": fact.id, "title": fact.title, "version": fact.version,
        "valid_from": fact.valid_from, "valid_to": fact.valid_to,
        "recorded_at": fact.recorded_at,
    }), 201


@api_bp.route("/memory/temporal/query")
def api_temporal_query():
    """Query bi-temporal memory."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.memory.bitemporal import BiTemporalMemory, TemporalQuery
    bt = BiTemporalMemory(empire_id)
    tq = TemporalQuery(
        query=request.args.get("q", ""),
        as_of_valid=request.args.get("as_of_valid"),
        as_of_recorded=request.args.get("as_of_recorded"),
        include_superseded=request.args.get("include_superseded", "false").lower() == "true",
        limit=request.args.get("limit", 20, type=int),
    )
    facts = bt.query(tq)
    return jsonify([{
        "id": f.id, "title": f.title, "content": f.content[:500],
        "valid_from": f.valid_from, "valid_to": f.valid_to,
        "recorded_at": f.recorded_at, "superseded_at": f.superseded_at,
        "version": f.version, "confidence": f.confidence,
        "source": f.source, "tags": f.tags,
    } for f in facts])


@api_bp.route("/memory/temporal/timeline")
def api_fact_timeline():
    """Get version history of a fact."""
    title = request.args.get("title", "")
    if not title:
        return jsonify({"error": "title parameter required"}), 400
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.memory.bitemporal import BiTemporalMemory
    bt = BiTemporalMemory(empire_id)
    timeline = bt.get_fact_timeline(title)
    return jsonify({
        "topic": timeline.topic,
        "current_version": timeline.current_version,
        "first_recorded": timeline.first_recorded,
        "last_updated": timeline.last_updated,
        "versions": [
            {"version": v.version, "content": v.content, "recorded_at": v.recorded_at,
             "superseded_at": v.superseded_at, "confidence": v.confidence, "source": v.source}
            for v in timeline.versions
        ],
    })


@api_bp.route("/memory/temporal/snapshot")
def api_temporal_snapshot():
    """Get what Empire knew at a point in time."""
    as_of = request.args.get("as_of", "")
    if not as_of:
        return jsonify({"error": "as_of parameter required (ISO datetime)"}), 400
    time_type = request.args.get("type", "recorded")
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.memory.bitemporal import BiTemporalMemory
    bt = BiTemporalMemory(empire_id)
    snapshot = bt.get_snapshot(as_of, time_type)
    return jsonify({
        "as_of": snapshot.as_of,
        "type": snapshot.snapshot_type,
        "total_facts": snapshot.total_facts,
        "facts": [{"title": f.title, "content": f.content[:300], "version": f.version} for f in snapshot.facts[:20]],
    })


@api_bp.route("/memory/temporal/stats")
def api_temporal_stats():
    """Get bi-temporal memory statistics."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.memory.bitemporal import BiTemporalMemory
    bt = BiTemporalMemory(empire_id)
    return jsonify(bt.get_temporal_stats())


@api_bp.route("/memory/search")
def api_memory_search():
    """Search memories."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.memory.manager import MemoryManager
    mm = MemoryManager(empire_id)
    return jsonify(mm.search(
        query=request.args.get("q", ""),
        memory_types=request.args.getlist("type") or None,
        limit=request.args.get("limit", 20, type=int),
    ))


@api_bp.route("/memory/purge", methods=["POST"])
@rate_limit(requests_per_minute=5, requests_per_hour=20)
def api_memory_purge():
    """Purge bad/invalid memories matching a pattern.

    Body: {"pattern": "Invalid command", "dry_run": true}
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json(silent=True) or {}
    pattern = data.get("pattern", "").strip()
    dry_run = data.get("dry_run", False)

    if not pattern or len(pattern) < 3:
        return jsonify({"error": "Pattern must be at least 3 characters"}), 400

    try:
        from db.engine import get_session
        from sqlalchemy import text

        session = get_session()
        try:
            # Find matching memories
            result = session.execute(text(
                "SELECT id, title, content FROM memory_entries "
                "WHERE empire_id = :eid AND (title LIKE :pat OR content LIKE :pat)"
            ), {"eid": empire_id, "pat": f"%{pattern}%"})
            matches = [{"id": r[0], "title": (r[1] or "")[:80], "preview": (r[2] or "")[:100]} for r in result]

            if dry_run:
                return jsonify({"matches": len(matches), "entries": matches, "dry_run": True})

            # Delete matching memories
            if matches:
                ids = [m["id"] for m in matches]
                placeholders = ", ".join(f":id_{i}" for i in range(len(ids)))
                params = {f"id_{i}": uid for i, uid in enumerate(ids)}
                session.execute(text(
                    f"DELETE FROM memory_entries WHERE id IN ({placeholders})"
                ), params)
                session.commit()

            return jsonify({"purged": len(matches), "entries": matches})
        finally:
            session.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/knowledge/purge", methods=["POST"])
@rate_limit(requests_per_minute=5, requests_per_hour=20)
def api_knowledge_purge():
    """Purge bad/invalid KG entities matching a pattern.

    Body: {"pattern": "Invalid", "dry_run": true}
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json(silent=True) or {}
    pattern = data.get("pattern", "").strip()
    dry_run = data.get("dry_run", False)

    if not pattern or len(pattern) < 3:
        return jsonify({"error": "Pattern must be at least 3 characters"}), 400

    try:
        from db.engine import get_session
        from sqlalchemy import text

        session = get_session()
        try:
            result = session.execute(text(
                "SELECT id, name, entity_type, description FROM knowledge_entities "
                "WHERE empire_id = :eid AND (name LIKE :pat OR description LIKE :pat)"
            ), {"eid": empire_id, "pat": f"%{pattern}%"})
            matches = [{"id": r[0], "name": r[1], "type": r[2], "desc": (r[3] or "")[:80]} for r in result]

            if dry_run:
                return jsonify({"matches": len(matches), "entities": matches, "dry_run": True})

            if matches:
                ids = [m["id"] for m in matches]
                placeholders = ", ".join(f":id_{i}" for i in range(len(ids)))
                params = {f"id_{i}": uid for i, uid in enumerate(ids)}
                # Delete relations first (FK)
                session.execute(text(
                    f"DELETE FROM knowledge_relations WHERE source_entity_id IN ({placeholders}) OR target_entity_id IN ({placeholders})"
                ), params)
                session.execute(text(
                    f"DELETE FROM knowledge_entities WHERE id IN ({placeholders})"
                ), params)
                session.commit()

            return jsonify({"purged": len(matches), "entities": matches})
        finally:
            session.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Evolution ──────────────────────────────────────────────────────────

@api_bp.route("/evolution/stats")
def api_evolution_stats():
    """Get evolution stats."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.evolution.cycle import EvolutionCycleManager
    ecm = EvolutionCycleManager(empire_id)
    return jsonify(ecm.get_stats().__dict__)


@api_bp.route("/evolution/run", methods=["POST"])
def api_run_evolution():
    """Run evolution cycle."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.evolution.cycle import EvolutionCycleManager
    ecm = EvolutionCycleManager(empire_id)
    result = ecm.run_full_cycle()
    return jsonify({"proposals": result.proposals_collected, "approved": result.approved, "applied": result.applied, "learnings": result.learnings})


@api_bp.route("/evolution/evolve-prompts", methods=["POST"])
def api_evolve_prompts():
    """Evolve lieutenant system prompts based on performance."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.evolution.prompt_evolution import PromptEvolver
    evolver = PromptEvolver(empire_id)
    evolved = evolver.evolve_all()
    return jsonify({
        "evolved_count": len(evolved),
        "lieutenants": [
            {"name": e.lieutenant_name, "confidence": e.confidence, "reasoning": e.reasoning[:200]}
            for e in evolved
        ],
    })


# ── Budget ─────────────────────────────────────────────────────────────

@api_bp.route("/budget")
def api_budget():
    """Get budget summary."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.routing.budget import BudgetManager
    bm = BudgetManager(empire_id)
    report = bm.get_budget_report()
    return jsonify({
        "daily_spend": report.daily_spend, "monthly_spend": report.monthly_spend,
        "daily_remaining": report.daily_remaining, "monthly_remaining": report.monthly_remaining,
        "alerts": [{"message": a.message, "severity": a.severity} for a in report.alerts],
    })


# ── Health ─────────────────────────────────────────────────────────────

@api_bp.route("/health/debug")
def api_health_debug():
    """Debug endpoint — shows env vars, LLM connectivity, scheduler state."""
    import os
    import traceback

    result = {
        "redis_url_set": bool(os.environ.get("REDIS_URL")),
        "redis_url_prefix": (os.environ.get("REDIS_URL", "")[:25] + "...") if os.environ.get("REDIS_URL") else "not set",
        "anthropic_key_set": bool(os.environ.get("EMPIRE_ANTHROPIC_API_KEY")),
        "anthropic_key_prefix": os.environ.get("EMPIRE_ANTHROPIC_API_KEY", "")[:15] + "..." if os.environ.get("EMPIRE_ANTHROPIC_API_KEY") else "not set",
        "db_url_set": bool(os.environ.get("EMPIRE_DB_URL")),
        "db_url_prefix": (os.environ.get("EMPIRE_DB_URL", "")[:30] + "...") if os.environ.get("EMPIRE_DB_URL") else "not set",
    }

    # Check LLM connectivity
    try:
        from config.settings import get_settings
        settings = get_settings()
        result["settings_anthropic_key_set"] = bool(settings.anthropic_api_key)
        result["settings_anthropic_key_prefix"] = settings.anthropic_api_key[:15] + "..." if settings.anthropic_api_key else "not set"
    except Exception as e:
        result["settings_error"] = str(e)

    # Test actual Anthropic API call
    try:
        from llm.anthropic import AnthropicClient
        key = os.environ.get("EMPIRE_ANTHROPIC_API_KEY", "")
        if key:
            from llm.base import LLMRequest, LLMMessage
            client = AnthropicClient(key)
            resp = client.complete(LLMRequest(
                messages=[LLMMessage.user("Say hi in 3 words")],
                model="claude-haiku-4-5-20251001",
                max_tokens=20,
            ))
            result["anthropic_test"] = "OK"
            result["anthropic_response"] = resp.content[:50]
            result["anthropic_cost"] = resp.cost_usd
        else:
            result["anthropic_test"] = "no key"
    except Exception as e:
        result["anthropic_test"] = f"FAILED: {e}"
        result["anthropic_traceback"] = traceback.format_exc()[-500:]

    # Check scheduler
    try:
        daemon = current_app.config.get("_SCHEDULER_DAEMON")
        if daemon:
            status = daemon.get_status()
            result["scheduler_running"] = status.running
            result["scheduler_ticks"] = status.total_ticks
            result["scheduler_errors"] = status.errors
            result["scheduler_jobs_active"] = status.jobs_active
        else:
            result["scheduler_running"] = False
            result["scheduler_note"] = "daemon not initialized"
    except Exception as e:
        result["scheduler_error"] = str(e)

    # Cache stats
    try:
        from llm.cache import get_cache
        cache = get_cache()
        result["cache_enabled"] = cache.enabled
        result["cache_stats"] = cache.get_stats()
    except Exception as e:
        result["cache_error"] = str(e)

    return jsonify(result)


@api_bp.route("/health")
def api_health():
    """Comprehensive system health — DB, Redis, circuits, cache, budget, fleet."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.scheduler.health import HealthChecker
    checker = HealthChecker(empire_id)
    report = checker.run_all_checks()

    # Append infrastructure stats
    try:
        from llm.cache import get_cache
        report["cache"] = get_cache().get_stats()
    except Exception:
        report["cache"] = {"enabled": False}

    try:
        from utils.circuit_breaker import get_all_circuit_stats
        report["circuits"] = get_all_circuit_stats()
    except Exception:
        report["circuits"] = {}

    try:
        from web.middleware.rate_limit import get_rate_limiter
        limiter = get_rate_limiter()
        report["rate_limiter"] = {"enabled": limiter.config.enabled}
    except Exception:
        report["rate_limiter"] = {"enabled": False}

    return jsonify(report)


# ── Replication ────────────────────────────────────────────────────────

@api_bp.route("/empires/generate", methods=["POST"])
def api_generate_empire():
    """Generate a new empire."""
    data = _get_json_or_400()
    from core.replication.generator import EmpireGenerator
    gen = EmpireGenerator()
    result = gen.generate_empire(
        name=data.get("name", ""),
        template=data.get("template", ""),
        domain=data.get("domain", "general"),
        description=data.get("description", ""),
    )
    return jsonify({
        "empire_id": result.empire_id, "lieutenants": result.lieutenants_created,
        "ready": result.launch_ready,
    }), 201


@api_bp.route("/empires/templates")
def api_empire_templates():
    """Get empire templates."""
    from core.replication.generator import EmpireGenerator
    gen = EmpireGenerator()
    return jsonify(gen.get_templates())


# ── Web Search ─────────────────────────────────────────────────────────

@api_bp.route("/search/web")
def api_web_search():
    """Search the web."""
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "Query parameter 'q' required"}), 400
    max_results = request.args.get("limit", 10, type=int)
    from core.search.web import WebSearcher
    searcher = WebSearcher(current_app.config.get("EMPIRE_ID", ""))
    result = searcher.search_and_summarize(query, max_results=max_results)
    return jsonify(result)


@api_bp.route("/search/news")
def api_news_search():
    """Search news articles."""
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "Query parameter 'q' required"}), 400
    max_results = request.args.get("limit", 10, type=int)
    time_range = request.args.get("range", "w")
    from core.search.web import WebSearcher
    searcher = WebSearcher(current_app.config.get("EMPIRE_ID", ""))
    response = searcher.search_news(query, max_results=max_results, time_range=time_range)
    return jsonify({
        "query": query,
        "results": [{"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source, "published": r.published} for r in response.results],
        "total": response.total_results,
    })


@api_bp.route("/search/ai")
def api_ai_search():
    """Search for AI-specific news and developments."""
    topic = request.args.get("topic", "")
    max_results = request.args.get("limit", 10, type=int)
    from core.search.web import WebSearcher
    searcher = WebSearcher(current_app.config.get("EMPIRE_ID", ""))
    response = searcher.search_ai_news(topic, max_results=max_results)
    return jsonify({
        "topic": topic,
        "results": [{"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source, "published": r.published} for r in response.results],
        "total": response.total_results,
    })


@api_bp.route("/search/papers")
def api_paper_search():
    """Search for AI research papers."""
    topic = request.args.get("topic", "")
    if not topic:
        return jsonify({"error": "Query parameter 'topic' required"}), 400
    max_results = request.args.get("limit", 10, type=int)
    from core.search.web import WebSearcher
    searcher = WebSearcher(current_app.config.get("EMPIRE_ID", ""))
    response = searcher.search_ai_papers(topic, max_results=max_results)
    return jsonify({
        "topic": topic,
        "results": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in response.results],
        "total": response.total_results,
    })


@api_bp.route("/search/store", methods=["POST"])
def api_search_and_store():
    """Search the web and store findings in knowledge graph + memory."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "Query required"}), 400
    from core.search.web import WebSearcher
    searcher = WebSearcher(empire_id)
    result = searcher.search_and_store(query, max_results=data.get("max_results", 5))
    return jsonify(result)


@api_bp.route("/scrape", methods=["POST"])
def api_scrape_url():
    """Scrape a URL and extract content."""
    data = _get_json_or_400()
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "URL required"}), 400
    from core.search.scraper import WebScraper
    scraper = WebScraper(current_app.config.get("EMPIRE_ID", ""))
    page = scraper.scrape_url(url)
    return jsonify({
        "url": url, "success": page.success, "title": page.title,
        "content": page.content[:10000], "word_count": page.word_count,
        "author": page.author, "date": page.date, "domain": page.domain,
        "error": page.error,
    })


@api_bp.route("/scrape/store", methods=["POST"])
def api_scrape_and_store():
    """Scrape a URL and store in knowledge + memory."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "URL required"}), 400
    from core.search.scraper import WebScraper
    scraper = WebScraper(empire_id)
    return jsonify(scraper.scrape_and_store(url))


@api_bp.route("/sweep", methods=["POST"])
@rate_limit(requests_per_minute=3, requests_per_hour=20)
def api_intelligence_sweep():
    """Run an intelligence sweep — proactive discovery across AI sources."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.search.sweep import IntelligenceSweep
    sweep = IntelligenceSweep(empire_id)
    result = sweep.run_full_sweep()
    return jsonify({
        "sources_checked": result.sources_checked,
        "total_found": result.total_found,
        "novel_items": result.novel_items,
        "stored_memories": result.stored_memories,
        "stored_entities": result.stored_entities,
        "discoveries": [
            {"title": d.title, "source": d.source, "category": d.category, "is_novel": d.is_novel}
            for d in result.discoveries[:10]
        ],
        "duration_seconds": result.duration_seconds,
        "errors": result.errors,
    })


@api_bp.route("/sweep/discoveries")
def api_sweep_discoveries():
    """Get recent discoveries from intelligence sweeps."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.search.sweep import IntelligenceSweep
    sweep = IntelligenceSweep(empire_id)
    return jsonify(sweep.get_recent_discoveries(limit=request.args.get("limit", 20, type=int)))


# ── Content Pipeline ───────────────────────────────────────────────────

@api_bp.route("/content/generate", methods=["POST"])
@rate_limit(requests_per_minute=5, requests_per_hour=50)
def api_generate_content():
    """Generate formatted content on a topic.

    Body: {"topic": "...", "template": "research_briefing", "context": "..."}
    Templates: research_briefing, weekly_digest, deep_dive, competitive_analysis, status_report
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "Topic required"}), 400

    from core.content.generator import ContentGenerator
    gen = ContentGenerator(empire_id)
    content = gen.generate(
        topic=topic,
        template_name=data.get("template", "research_briefing"),
        additional_context=data.get("context", ""),
    )

    return jsonify({
        "title": content.title,
        "report_id": content.id,
        "template": content.template_used,
        "sections": [
            {"title": s.title, "content": s.content, "words": s.word_count, "cost": s.cost_usd}
            for s in content.sections
        ],
        "total_words": content.total_words,
        "total_cost": sum(s.cost_usd for s in content.sections),
        "markdown": content.markdown,
    })


@api_bp.route("/content/from-directive/<directive_id>", methods=["POST"])
def api_content_from_directive(directive_id: str):
    """Generate formatted content from a completed directive."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400() or {}
    from core.content.generator import ContentGenerator
    gen = ContentGenerator(empire_id)
    content = gen.generate_from_directive(
        directive_id=directive_id,
        template_name=data.get("template", "research_briefing"),
    )
    return jsonify({
        "title": content.title,
        "template": content.template_used,
        "sections": [{"title": s.title, "content": s.content, "words": s.word_count} for s in content.sections],
        "total_words": content.total_words,
        "markdown": content.markdown,
    })


@api_bp.route("/content/status-report", methods=["POST"])
def api_status_report():
    """Generate an Empire status report."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.content.generator import ContentGenerator
    gen = ContentGenerator(empire_id)
    content = gen.generate_status_report()
    return jsonify({
        "title": content.title,
        "sections": [{"title": s.title, "content": s.content, "words": s.word_count} for s in content.sections],
        "total_words": content.total_words,
        "markdown": content.markdown,
    })


@api_bp.route("/content/render/<directive_id>")
def api_render_report(directive_id: str):
    """Render a directive report as HTML page."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    template_name = request.args.get("template", "research_briefing")
    from core.content.generator import ContentGenerator
    gen = ContentGenerator(empire_id)
    content = gen.generate_from_directive(directive_id, template_name)
    return content.html, 200, {"Content-Type": "text/html"}


@api_bp.route("/content/weekly-digest", methods=["POST"])
def api_weekly_digest():
    """Generate a weekly AI digest from the last 7 days."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.content.generator import ContentGenerator
    gen = ContentGenerator(empire_id)
    content = gen.generate_weekly_digest()
    return jsonify({
        "title": content.title,
        "sections": [{"title": s.title, "content": s.content, "words": s.word_count, "cost": s.cost_usd} for s in content.sections],
        "total_words": content.total_words,
        "total_cost": content.total_cost,
        "markdown": content.markdown,
    })


@api_bp.route("/content/reports")
def api_stored_reports():
    """Get previously generated reports."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.content.generator import ContentGenerator
    gen = ContentGenerator(empire_id)
    return jsonify(gen.get_stored_reports(limit=request.args.get("limit", 10, type=int)))


@api_bp.route("/content/render-topic", methods=["POST"])
def api_render_topic():
    """Generate and render a report as HTML directly."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    topic = data.get("topic", "")
    template = data.get("template", "research_briefing")
    if not topic:
        return "Topic required", 400
    from core.content.generator import ContentGenerator
    gen = ContentGenerator(empire_id)
    content = gen.generate(topic=topic, template_name=template)
    return content.html, 200, {"Content-Type": "text/html"}


@api_bp.route("/content/templates")
def api_content_templates():
    """List available content templates."""
    from core.content.templates import list_templates
    return jsonify(list_templates())


@api_bp.route("/research", methods=["POST"])
@rate_limit(requests_per_minute=5, requests_per_hour=60)
def api_research_topic():
    """Search, scrape, and synthesize research on a topic.

    Full pipeline: search → scrape (with fallback to snippets) → LLM synthesis → store.
    Tries multiple sources, prefers open sites, falls back to search snippets.
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = _get_json_or_400()
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "Topic required"}), 400

    max_sources = data.get("max_sources", 3)

    from core.search.scraper import WebScraper
    from core.search.web import WebSearcher

    scraper = WebScraper(empire_id)
    searcher = WebSearcher(empire_id)

    # Domains that tend to allow scraping
    OPEN_DOMAINS = {
        "arxiv.org", "github.com", "huggingface.co", "simonwillison.net",
        "lilianweng.github.io", "openai.com", "anthropic.com", "ai.meta.com",
        "blog.google", "deepmind.google", "mistral.ai", "together.ai",
        "en.wikipedia.org", "techcrunch.com", "theverge.com", "arstechnica.com",
        "wired.com", "reuters.com", "apnews.com", "bbc.com", "macrumors.com",
    }

    # 1. Search multiple channels for sources
    all_results = []

    # News search
    news = searcher.search_ai_news(topic, max_results=max_sources * 2)
    for r in news.results:
        all_results.append({"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source, "type": "news"})

    # Web search as backup
    web = searcher.search(f"{topic} AI", max_results=max_sources * 2)
    for r in web.results:
        if r.url not in {ar["url"] for ar in all_results}:
            all_results.append({"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source, "type": "web"})

    if not all_results:
        return jsonify({"topic": topic, "success": False, "error": "No search results found"})

    # 2. Sort: prefer open domains first
    def domain_priority(r):
        domain = r.get("source", "").lower()
        return 0 if any(od in domain for od in OPEN_DOMAINS) else 1

    all_results.sort(key=domain_priority)

    # 3. Try to scrape — attempt more URLs, keep what works
    scraped = []
    scrape_failures = []
    for result in all_results[:max_sources * 3]:  # Try up to 3x the requested amount
        if len(scraped) >= max_sources:
            break
        url = result.get("url", "")
        if not url:
            continue
        page = scraper.scrape_url(url)
        if page.success and page.word_count > 50:
            scraped.append(page)
        else:
            scrape_failures.append({"url": url, "error": page.error or "too short"})

    # 4. Build research context — scraped articles + snippet fallback + credibility
    from core.search.credibility import CredibilityScorer
    cred_scorer = CredibilityScorer()

    source_texts = []
    source_info = []

    for page in scraped:
        cred = cred_scorer.score(page.url)
        cred_label = cred_scorer.format_for_prompt(page.url)
        source_texts.append(f"## {page.title}\nSource: {page.domain} | {page.date} {cred_label}\n\n{page.content[:3000]}")
        source_info.append({"title": page.title, "url": page.url, "domain": page.domain, "words": page.word_count, "type": "scraped", "credibility": cred.score, "tier": cred.tier})

    # Fallback: if we didn't get enough scraped content, use search snippets
    if len(source_texts) < max_sources:
        snippet_sources = [r for r in all_results if r["url"] not in {s.url for s in scraped}]
        for r in snippet_sources[:max_sources - len(source_texts)]:
            cred = cred_scorer.score(r.get("url", ""))
            cred_label = cred_scorer.format_for_prompt(r.get("url", ""))
            source_texts.append(f"## {r['title']}\nSource: {r['source']} (snippet only) {cred_label}\n\n{r['snippet']}")
            source_info.append({"title": r["title"], "url": r["url"], "domain": r["source"], "words": len(r["snippet"].split()), "type": "snippet", "credibility": cred.score, "tier": cred.tier})

    if not source_texts:
        return jsonify({"topic": topic, "success": False, "error": "No content available", "scrape_failures": scrape_failures})

    combined = "\n\n---\n\n".join(source_texts)

    # 4. LLM synthesis
    from llm.base import LLMRequest, LLMMessage
    from llm.router import ModelRouter, TaskMetadata

    router = ModelRouter()
    prompt = f"""Synthesize this research on: {topic}

Sources:
{combined}

Provide:
1. Key findings across all sources
2. What's new/significant
3. What this means for the AI landscape
4. Questions for follow-up research

Be specific and cite which source each finding comes from.
"""
    try:
        request_llm = LLMRequest(
            messages=[LLMMessage.user(prompt)],
            system_prompt="You are an AI research analyst. Synthesize sources accurately and identify what matters.",
            temperature=0.3,
            max_tokens=3000,
        )
        response = router.execute(request_llm, TaskMetadata(task_type="analysis", complexity="complex"))

        # 5. Store in memory
        from core.memory.manager import MemoryManager
        mm = MemoryManager(empire_id)
        mm.store(
            content=f"Research: {topic}\n\n{response.content[:5000]}",
            memory_type="semantic",
            title=f"Research: {topic}",
            category="research",
            importance=0.75,
            tags=["research", "synthesis", topic.lower().replace(" ", "_")],
            source_type="research",
        )

        return jsonify({
            "topic": topic,
            "success": True,
            "synthesis": response.content,
            "sources": source_info,
            "source_count": len(source_info),
            "scraped_count": len(scraped),
            "snippet_fallbacks": len(source_info) - len(scraped),
            "scrape_failures": scrape_failures[:5],
            "cost_usd": response.cost_usd,
        })

    except Exception as e:
        return jsonify({"topic": topic, "success": False, "error": str(e)}), 500


# ── RSS Feeds ──────────────────────────────────────────────────────────

@api_bp.route("/feeds")
def api_list_feeds():
    """List configured RSS feeds."""
    from core.search.feeds import FeedReader
    reader = FeedReader(current_app.config.get("EMPIRE_ID", ""))
    return jsonify(reader.list_feeds())


@api_bp.route("/feeds/latest")
def api_feed_latest():
    """Get latest entries from all feeds."""
    category = request.args.get("category")
    max_total = request.args.get("limit", 20, type=int)
    from core.search.feeds import FeedReader
    reader = FeedReader(current_app.config.get("EMPIRE_ID", ""))
    entries = reader.fetch_latest(
        categories=[category] if category else None,
        max_total=max_total,
    )
    return jsonify([
        {"title": e.title, "url": e.url, "summary": e.summary[:300],
         "source": e.source_feed, "published": e.published, "tags": e.tags}
        for e in entries
    ])


@api_bp.route("/feeds/sync", methods=["POST"])
def api_feed_sync():
    """Fetch all feeds and store new entries."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.search.feeds import FeedReader
    reader = FeedReader(empire_id)
    result = reader.fetch_and_store()
    return jsonify(result)


# ── Credibility ────────────────────────────────────────────────────────

@api_bp.route("/credibility")
def api_check_credibility():
    """Check credibility of a URL."""
    url = request.args.get("url", "")
    if not url:
        return jsonify({"error": "URL parameter required"}), 400
    from core.search.credibility import CredibilityScorer
    scorer = CredibilityScorer()
    score = scorer.score(url)
    return jsonify({
        "url": url, "domain": score.domain, "score": score.score,
        "tier": score.tier, "category": score.category, "reasoning": score.reasoning,
    })


@api_bp.route("/credibility/tiers")
def api_credibility_tiers():
    """Get all sources organized by tier."""
    from core.search.credibility import get_source_tiers
    return jsonify(get_source_tiers())


# ── Research Pipeline ────────────────────────────────────────────────

@api_bp.route("/pipeline/run", methods=["POST"])
@rate_limit(requests_per_minute=3)
def api_pipeline_run():
    """Run the full research pipeline on a topic."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()
    depth = data.get("depth", "standard")
    max_sources = data.get("max_sources", 8)

    if not topic:
        return jsonify({"error": "topic is required"}), 400
    if depth not in ("shallow", "standard", "deep"):
        return jsonify({"error": "depth must be shallow, standard, or deep"}), 400

    try:
        from core.research.pipeline import ResearchPipeline
        pipeline = ResearchPipeline(empire_id)
        result = pipeline.run(topic, depth=depth, max_sources=max_sources)
        return jsonify(result.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Model Routing ────────────────────────────────────────────────────

@api_bp.route("/routing/tiers")
def api_routing_tiers():
    """Show the current model tiering map."""
    from llm.router import ModelRouter
    router = ModelRouter()
    return jsonify(router.get_tier_map())


# ── Iterative Deepening ──────────────────────────────────────────────

@api_bp.route("/deepening/candidates")
def api_deepening_candidates():
    """Find topics that warrant deeper research."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.research.deepening import IterativeDeepener
        deepener = IterativeDeepener(empire_id)
        candidates = deepener.detect_candidates(max_candidates=10)
        return jsonify([{
            "topic": c.topic,
            "entity_names": c.entity_names[:10],
            "current_depth": c.current_depth,
            "signal_score": c.signal_score,
            "trigger_reason": c.trigger_reason,
        } for c in candidates])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/deepening/run", methods=["POST"])
@rate_limit(requests_per_minute=5)
def api_deepening_run():
    """Trigger an iterative deepening cycle."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json(silent=True) or {}
    max_topics = data.get("max_topics", 3)
    try:
        from core.research.deepening import IterativeDeepener
        deepener = IterativeDeepener(empire_id)
        results = deepener.run_deepening_cycle(max_topics=max_topics)
        return jsonify({
            "topics_deepened": len(results),
            "results": [{
                "topic": r.topic,
                "depth": r.depth,
                "new_entities": r.new_entities,
                "new_relations": r.new_relations,
                "queries_run": r.queries_run,
                "cost_usd": r.cost_usd,
                "duration_seconds": r.duration_seconds,
            } for r in results],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Shallow Enrichment ───────────────────────────────────────────────

@api_bp.route("/enrichment/targets")
def api_enrichment_targets():
    """Find knowledge graph entities needing enrichment."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.research.enrichment import ShallowEnricher
        enricher = ShallowEnricher(empire_id)
        targets = enricher.find_targets(max_targets=20)
        return jsonify([{
            "entity_id": t.entity_id,
            "entity_name": t.entity_name,
            "entity_type": t.entity_type,
            "completeness": t.completeness,
            "priority": t.priority,
            "missing_fields": t.missing_fields[:5],
            "reason": t.reason,
        } for t in targets])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/enrichment/run", methods=["POST"])
@rate_limit(requests_per_minute=5)
def api_enrichment_run():
    """Trigger a shallow enrichment cycle."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json(silent=True) or {}
    max_entities = data.get("max_entities", 10)
    try:
        from core.research.enrichment import ShallowEnricher
        enricher = ShallowEnricher(empire_id)
        result = enricher.run_enrichment_cycle(max_entities=max_entities)
        return jsonify({
            "entities_scanned": result.entities_scanned,
            "enriched": result.enriched,
            "descriptions_improved": result.descriptions_improved,
            "fields_added": result.fields_added,
            "cost_usd": result.cost_usd,
            "duration_seconds": result.duration_seconds,
            "errors": result.errors[:5],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Cross-Lieutenant Synthesis ─────────────────────────────────────────

@api_bp.route("/synthesis/overlaps")
def api_cross_synthesis_overlaps():
    """Detect cross-domain knowledge overlaps between lieutenants."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.research.cross_synthesis import CrossLieutenantSynthesizer
        synthesizer = CrossLieutenantSynthesizer(empire_id)
        overlaps = synthesizer.detect_overlaps()
        return jsonify([
            {
                "topic": o.topic,
                "domains": o.domains,
                "shared_entities": len(o.shared_entities),
                "overlap_score": round(o.overlap_score, 2),
                "entities": [e["name"] for e in o.shared_entities[:5]],
            }
            for o in overlaps[:10]
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/synthesis/run", methods=["POST"])
@rate_limit(requests_per_minute=2, requests_per_hour=10)
def api_cross_synthesis_run():
    """Run cross-lieutenant synthesis cycle."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json(silent=True) or {}
    max_syntheses = min(data.get("max_syntheses", 3), 5)

    try:
        from core.research.cross_synthesis import CrossLieutenantSynthesizer
        synthesizer = CrossLieutenantSynthesizer(empire_id)
        result = synthesizer.run_synthesis_cycle(max_syntheses=max_syntheses)
        return jsonify({
            "overlaps_detected": result.overlaps_detected,
            "syntheses_produced": result.syntheses_produced,
            "total_insights": result.total_insights,
            "cost_usd": round(result.total_cost_usd, 4),
            "results": [
                {
                    "topic": r.topic,
                    "domains": r.domains,
                    "entities_involved": r.entities_involved,
                    "connections_found": r.connections_found,
                    "insights": r.insights[:5],
                    "synthesis": r.synthesis[:1000],
                    "cost_usd": round(r.cost_usd, 4),
                }
                for r in result.results
            ],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
