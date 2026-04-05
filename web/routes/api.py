"""REST API routes for programmatic access to Empire."""

from __future__ import annotations

import logging
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, Response, abort, jsonify, request, current_app
from web.middleware.rate_limit import rate_limit
from db.engine import repo_scope, session_scope

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__)

_MAX_LIMIT = 200


# ── Helpers ───────────────────────────────────────────────────────────


def _clamp_limit(default: int = 20) -> int:
    """Get a clamped 'limit' query parameter."""
    return min(request.args.get("limit", default, type=int), _MAX_LIMIT)


def _safe_error(e: Exception) -> str:
    """Return a sanitized error message for API responses."""
    logger.error("API error: %s", e)
    return "Internal server error"


def _get_json_or_400() -> dict:
    """Get JSON body or abort with 400."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        abort(400, description="Request body must be valid JSON")
    return data


def _validate_url(url: str) -> str | None:
    """Validate URL for SSRF — returns error string or None if OK."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or \
       hostname.startswith(("169.254.", "10.", "192.168.", "172.16.", "172.17.",
                            "172.18.", "172.19.", "172.2", "172.30.", "172.31.")):
        return "Internal addresses are not allowed"
    if not parsed.scheme or parsed.scheme not in ("http", "https"):
        return "Only http/https URLs are allowed"
    return None


def empire_route(fn):
    """Decorator: injects empire_id, jsonifies return values, catches errors."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            empire_id = current_app.config.get("EMPIRE_ID", "")
            result = fn(empire_id, *args, **kwargs)
            if isinstance(result, Response):
                return result
            if isinstance(result, tuple):
                # Support (data, status) and (data, status, headers)
                return jsonify(result[0]), *result[1:]
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": _safe_error(e)}), 500
    return wrapper


# ── Empire ────────────────────────────────────────────────────────────


@api_bp.route("/empire")
@empire_route
def get_empire(empire_id):
    """Get current empire info."""
    from db.repositories.empire import EmpireRepository
    with repo_scope(EmpireRepository) as repo:
        return repo.get_health_overview(empire_id)


@api_bp.route("/empire/network")
@empire_route
def get_network(empire_id):
    """Get network stats across all empires."""
    from db.repositories.empire import EmpireRepository
    with repo_scope(EmpireRepository) as repo:
        return repo.get_network_stats()


# ── Lieutenants ───────────────────────────────────────────────────────


@api_bp.route("/lieutenants")
@empire_route
def api_list_lieutenants(empire_id):
    """List all lieutenants."""
    from core.lieutenant.manager import LieutenantManager
    return LieutenantManager(empire_id).list_lieutenants(
        status=request.args.get("status"),
        domain=request.args.get("domain"),
    )


@api_bp.route("/lieutenants", methods=["POST"])
@empire_route
def api_create_lieutenant(empire_id):
    """Create a lieutenant."""
    data = _get_json_or_400()
    from core.lieutenant.manager import LieutenantManager
    lt = LieutenantManager(empire_id).create_lieutenant(
        name=data.get("name", ""),
        template=data.get("template", ""),
        domain=data.get("domain", ""),
    )
    return {"id": lt.id, "name": lt.name, "domain": lt.domain}, 201


@api_bp.route("/lieutenants/<lt_id>/task", methods=["POST"])
@empire_route
def api_lieutenant_task(empire_id, lt_id: str):
    """Submit a task to a lieutenant."""
    data = _get_json_or_400()
    from core.lieutenant.manager import LieutenantManager
    from core.ace.engine import TaskInput
    lt = LieutenantManager(empire_id).get_lieutenant(lt_id)
    if not lt:
        return {"error": "Lieutenant not found"}, 404
    task = TaskInput(
        title=data.get("title", ""),
        description=data.get("description", ""),
        task_type=data.get("type", "general"),
    )
    return lt.execute_task(task).to_dict()


# ── Directives ────────────────────────────────────────────────────────


@api_bp.route("/directives")
@empire_route
def api_list_directives(empire_id):
    """List directives."""
    from core.directives.manager import DirectiveManager
    return DirectiveManager(empire_id).list_directives(status=request.args.get("status"))


@api_bp.route("/directives", methods=["POST"])
@empire_route
def api_create_directive(empire_id):
    """Create a directive."""
    data = _get_json_or_400()
    from core.directives.manager import DirectiveManager
    result = DirectiveManager(empire_id).create_directive(
        title=data.get("title", ""),
        description=data.get("description", ""),
        priority=data.get("priority", 5),
    )
    return result, 201


_directive_semaphore = __import__("threading").Semaphore(5)


@api_bp.route("/directives/<directive_id>/execute", methods=["POST"])
@rate_limit(requests_per_minute=5, requests_per_hour=50)
def api_execute_directive(directive_id: str):
    """Execute a directive in a background thread.

    Returns immediately with status. Poll /directives/<id>/progress for updates.
    """
    if not _directive_semaphore.acquire(blocking=False):
        return jsonify({"error": "Too many directives running concurrently. Try again later."}), 429

    empire_id = current_app.config.get("EMPIRE_ID", "")
    app = current_app._get_current_object()
    import threading

    def run_directive(app_ref, eid, did):
        try:
            with app_ref.app_context():
                from core.directives.manager import DirectiveManager
                dm = DirectiveManager(eid)
                try:
                    dm.execute_directive(did)
                except Exception as e:
                    logger.error("Directive execution failed: %s", e)
                    try:
                        dm.cancel_directive(did)
                    except Exception:
                        pass
        finally:
            _directive_semaphore.release()

    thread = threading.Thread(
        target=run_directive,
        args=(app, empire_id, directive_id),
        daemon=True,
        name=f"directive-{directive_id[:8]}",
    )
    thread.start()

    return jsonify({
        "directive_id": directive_id,
        "status": "started",
        "message": "Executing in background. Poll /api/directives/{id}/progress for updates.",
    }), 202


@api_bp.route("/directives/<directive_id>/progress")
@empire_route
def api_directive_progress(empire_id, directive_id: str):
    """Get directive progress."""
    from core.directives.manager import DirectiveManager
    return DirectiveManager(empire_id).get_progress(directive_id).__dict__


@api_bp.route("/directives/<directive_id>/report")
@empire_route
def api_directive_report(empire_id, directive_id: str):
    """Get the full output/report from a completed directive."""
    from db.repositories.directive import DirectiveRepository
    from db.repositories.task import TaskRepository
    from db.models import WarRoom
    from sqlalchemy import select, desc

    with session_scope() as session:
        dir_repo = DirectiveRepository(session)
        task_repo = TaskRepository(session)

        directive = dir_repo.get(directive_id)
        if not directive:
            return {"error": "Directive not found"}, 404

        tasks = task_repo.get_by_directive(directive_id)
        report_sections = []
        for task in tasks:
            content = (task.output_json or {}).get("content", "")
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

        war_rooms = list(session.execute(
            select(WarRoom).where(WarRoom.directive_id == directive_id).order_by(desc(WarRoom.created_at))
        ).scalars().all())
        synthesis = war_rooms[0].synthesis_json or {} if war_rooms else {}

        return {
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
        }


@api_bp.route("/reports/latest")
@empire_route
def api_latest_reports(empire_id):
    """Get the latest research reports."""
    from db.repositories.directive import DirectiveRepository
    from core.memory.manager import MemoryManager

    with repo_scope(DirectiveRepository) as repo:
        completed = repo.get_completed(empire_id, days=30, limit=10)
        reports = [{
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "quality_score": d.quality_score,
            "total_cost": d.total_cost_usd,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "completed_at": d.completed_at.isoformat() if d.completed_at else None,
            "report_url": f"/api/directives/{d.id}/report",
        } for d in completed]

    research_memories = MemoryManager(empire_id).recall(
        query="research synthesis",
        memory_types=["semantic"],
        limit=10,
    )

    return {
        "directive_reports": reports,
        "research_entries": research_memories,
    }


# ── Knowledge ─────────────────────────────────────────────────────────


@api_bp.route("/knowledge/stats")
@empire_route
def api_knowledge_stats(empire_id):
    """Get knowledge graph stats."""
    from core.knowledge.graph import KnowledgeGraph
    return KnowledgeGraph(empire_id).get_stats().__dict__


@api_bp.route("/knowledge/entities")
@empire_route
def api_knowledge_entities(empire_id):
    """Search knowledge entities."""
    from core.knowledge.graph import KnowledgeGraph
    entities = KnowledgeGraph(empire_id).find_entities(
        query=request.args.get("q", ""),
        entity_type=request.args.get("type", ""),
        limit=_clamp_limit(20),
    )
    return [{"name": e.name, "type": e.entity_type, "confidence": e.confidence, "importance": e.importance} for e in entities]


@api_bp.route("/knowledge/entity/<entity_name>/neighbors")
@empire_route
def api_entity_neighbors(empire_id, entity_name: str):
    """Get entity neighbors."""
    from core.knowledge.graph import KnowledgeGraph
    neighbors = KnowledgeGraph(empire_id).get_neighbors(
        entity_name, max_depth=request.args.get("depth", 2, type=int),
    )
    return [{"name": n.name, "type": n.entity_type, "depth": n.depth} for n in neighbors]


@api_bp.route("/knowledge/ask")
@empire_route
def api_knowledge_ask(empire_id):
    """Ask the knowledge graph a question."""
    question = request.args.get("q", "")
    if not question:
        return {"error": "Query parameter 'q' required"}, 400
    from core.knowledge.query import KnowledgeQuerier
    answer = KnowledgeQuerier(empire_id).ask(question)
    return {
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
    }


@api_bp.route("/knowledge/profile/<entity_name>")
@empire_route
def api_knowledge_profile(empire_id, entity_name: str):
    """Get structured knowledge profile for an entity."""
    from core.knowledge.query import KnowledgeQuerier
    return KnowledgeQuerier(empire_id).ask_structured(entity_name)


@api_bp.route("/knowledge/compare")
@empire_route
def api_knowledge_compare(empire_id):
    """Compare two entities."""
    a = request.args.get("a", "")
    b = request.args.get("b", "")
    if not a or not b:
        return {"error": "Parameters 'a' and 'b' required"}, 400
    from core.knowledge.query import KnowledgeQuerier
    return KnowledgeQuerier(empire_id).compare(a, b)


@api_bp.route("/knowledge/schemas")
def api_knowledge_schemas():
    """List all entity type schemas."""
    from core.knowledge.schemas import list_schemas
    return jsonify(list_schemas())


@api_bp.route("/knowledge/quality")
@empire_route
def api_knowledge_quality(empire_id):
    """Get quality scores for knowledge entities."""
    from core.knowledge.quality import EntityQualityScorer
    return EntityQualityScorer(empire_id).get_quality_stats()


@api_bp.route("/knowledge/audit", methods=["POST"])
@rate_limit(requests_per_minute=2, requests_per_hour=10)
@empire_route
def api_knowledge_audit(empire_id):
    """Deep LLM audit for contaminated/hallucinated entities."""
    data = _get_json_or_400()
    from core.knowledge.maintenance import KnowledgeMaintainer
    return KnowledgeMaintainer(empire_id).deep_llm_audit(
        batch_size=min(data.get("batch_size", 20), 50),
    )


@api_bp.route("/knowledge/duplicates")
@empire_route
def api_knowledge_duplicates(empire_id):
    """Find duplicate entities."""
    from core.knowledge.resolution import EntityResolver
    groups = EntityResolver(empire_id).find_duplicates()
    return [{"entities": group, "count": len(group)} for group in groups]


@api_bp.route("/knowledge/merge-duplicates", methods=["POST"])
@empire_route
def api_merge_duplicates(empire_id):
    """Find and merge all duplicate entities."""
    from core.knowledge.resolution import EntityResolver
    return {"merged": EntityResolver(empire_id).merge_duplicates()}


# ── Memory ────────────────────────────────────────────────────────────


@api_bp.route("/memory/stats")
@empire_route
def api_memory_stats(empire_id):
    """Get memory stats."""
    from core.memory.manager import MemoryManager
    return MemoryManager(empire_id).get_stats().__dict__


@api_bp.route("/memory/compress", methods=["POST"])
@empire_route
def api_compress_memories(empire_id):
    """Run memory compression — distill clusters into concise knowledge."""
    from core.memory.compression import MemoryCompressor
    result = MemoryCompressor(empire_id).run_compression()
    return {
        "clusters_found": result.clusters_found,
        "clusters_compressed": result.clusters_compressed,
        "memories_consumed": result.memories_consumed,
        "summaries_created": result.summaries_created,
        "compression_ratio": f"{result.compression_ratio:.0%}",
        "cost_usd": result.cost_usd,
    }


@api_bp.route("/memory/compress/topic", methods=["POST"])
@empire_route
def api_compress_topic(empire_id):
    """Compress all memories about a specific topic."""
    data = _get_json_or_400()
    topic = data.get("topic", "")
    if not topic:
        return {"error": "Topic required"}, 400
    from core.memory.compression import MemoryCompressor
    result = MemoryCompressor(empire_id).compress_by_topic(topic)
    if result:
        return result
    return {"error": f"Not enough memories about '{topic}' to compress (need 3+)"}


@api_bp.route("/memory/compress/stats")
@empire_route
def api_compression_stats(empire_id):
    """Get compression statistics."""
    from core.memory.compression import MemoryCompressor
    return MemoryCompressor(empire_id).get_compression_stats()


@api_bp.route("/memory/temporal/store", methods=["POST"])
@empire_route
def api_store_temporal(empire_id):
    """Store a bi-temporal fact."""
    data = _get_json_or_400()
    from core.memory.bitemporal import BiTemporalMemory
    fact = BiTemporalMemory(empire_id).store_fact(
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
    return {
        "id": fact.id, "title": fact.title, "version": fact.version,
        "valid_from": fact.valid_from, "valid_to": fact.valid_to,
        "recorded_at": fact.recorded_at,
    }, 201


@api_bp.route("/memory/temporal/query")
@empire_route
def api_temporal_query(empire_id):
    """Query bi-temporal memory."""
    from core.memory.bitemporal import BiTemporalMemory, TemporalQuery
    bt = BiTemporalMemory(empire_id)
    facts = bt.query(TemporalQuery(
        query=request.args.get("q", ""),
        as_of_valid=request.args.get("as_of_valid"),
        as_of_recorded=request.args.get("as_of_recorded"),
        include_superseded=request.args.get("include_superseded", "false").lower() == "true",
        limit=_clamp_limit(20),
    ))
    return [{
        "id": f.id, "title": f.title, "content": f.content[:500],
        "valid_from": f.valid_from, "valid_to": f.valid_to,
        "recorded_at": f.recorded_at, "superseded_at": f.superseded_at,
        "version": f.version, "confidence": f.confidence,
        "source": f.source, "tags": f.tags,
    } for f in facts]


@api_bp.route("/memory/temporal/timeline")
@empire_route
def api_fact_timeline(empire_id):
    """Get version history of a fact."""
    title = request.args.get("title", "")
    if not title:
        return {"error": "title parameter required"}, 400
    from core.memory.bitemporal import BiTemporalMemory
    timeline = BiTemporalMemory(empire_id).get_fact_timeline(title)
    return {
        "topic": timeline.topic,
        "current_version": timeline.current_version,
        "first_recorded": timeline.first_recorded,
        "last_updated": timeline.last_updated,
        "versions": [
            {"version": v.version, "content": v.content, "recorded_at": v.recorded_at,
             "superseded_at": v.superseded_at, "confidence": v.confidence, "source": v.source}
            for v in timeline.versions
        ],
    }


@api_bp.route("/memory/temporal/snapshot")
@empire_route
def api_temporal_snapshot(empire_id):
    """Get what Empire knew at a point in time."""
    as_of = request.args.get("as_of", "")
    if not as_of:
        return {"error": "as_of parameter required (ISO datetime)"}, 400
    from core.memory.bitemporal import BiTemporalMemory
    snapshot = BiTemporalMemory(empire_id).get_snapshot(
        as_of, request.args.get("type", "recorded"),
    )
    return {
        "as_of": snapshot.as_of,
        "type": snapshot.snapshot_type,
        "total_facts": snapshot.total_facts,
        "facts": [{"title": f.title, "content": f.content[:300], "version": f.version} for f in snapshot.facts[:20]],
    }


@api_bp.route("/memory/temporal/stats")
@empire_route
def api_temporal_stats(empire_id):
    """Get bi-temporal memory statistics."""
    from core.memory.bitemporal import BiTemporalMemory
    return BiTemporalMemory(empire_id).get_temporal_stats()


@api_bp.route("/memory/search")
@empire_route
def api_memory_search(empire_id):
    """Search memories."""
    from core.memory.manager import MemoryManager
    return MemoryManager(empire_id).search(
        query=request.args.get("q", ""),
        memory_types=request.args.getlist("type") or None,
        limit=_clamp_limit(20),
    )


@api_bp.route("/memory/purge", methods=["POST"])
@rate_limit(requests_per_minute=5, requests_per_hour=20)
@empire_route
def api_memory_purge(empire_id):
    """Purge bad/invalid memories matching a pattern.

    Body: {"pattern": "Invalid command", "dry_run": true}
    """
    data = request.get_json(silent=True) or {}
    pattern = data.get("pattern", "").strip()
    dry_run = data.get("dry_run", False)

    if not pattern or len(pattern) < 3:
        return {"error": "Pattern must be at least 3 characters"}, 400

    from sqlalchemy import text

    with session_scope() as session:
        result = session.execute(text(
            "SELECT id, title, content FROM memory_entries "
            "WHERE empire_id = :eid AND (title LIKE :pat OR content LIKE :pat)"
        ), {"eid": empire_id, "pat": f"%{pattern}%"})
        matches = [{"id": r[0], "title": (r[1] or "")[:80], "preview": (r[2] or "")[:100]} for r in result]

        if dry_run:
            return {"matches": len(matches), "entries": matches, "dry_run": True}

        if matches:
            ids = [m["id"] for m in matches]
            placeholders = ", ".join(f":id_{i}" for i in range(len(ids)))
            params = {f"id_{i}": uid for i, uid in enumerate(ids)}
            session.execute(text(
                f"DELETE FROM memory_entries WHERE id IN ({placeholders})"
            ), params)

        return {"purged": len(matches), "entries": matches}


@api_bp.route("/knowledge/purge", methods=["POST"])
@rate_limit(requests_per_minute=5, requests_per_hour=20)
@empire_route
def api_knowledge_purge(empire_id):
    """Purge bad/invalid KG entities matching a pattern.

    Body: {"pattern": "Invalid", "dry_run": true}
    """
    data = request.get_json(silent=True) or {}
    pattern = data.get("pattern", "").strip()
    dry_run = data.get("dry_run", False)

    if not pattern or len(pattern) < 3:
        return {"error": "Pattern must be at least 3 characters"}, 400

    from sqlalchemy import text

    with session_scope() as session:
        result = session.execute(text(
            "SELECT id, name, entity_type, description FROM knowledge_entities "
            "WHERE empire_id = :eid AND (name LIKE :pat OR description LIKE :pat)"
        ), {"eid": empire_id, "pat": f"%{pattern}%"})
        matches = [{"id": r[0], "name": r[1], "type": r[2], "desc": (r[3] or "")[:80]} for r in result]

        if dry_run:
            return {"matches": len(matches), "entities": matches, "dry_run": True}

        if matches:
            ids = [m["id"] for m in matches]
            placeholders = ", ".join(f":id_{i}" for i in range(len(ids)))
            params = {f"id_{i}": uid for i, uid in enumerate(ids)}
            session.execute(text(
                f"DELETE FROM knowledge_relations WHERE source_entity_id IN ({placeholders}) OR target_entity_id IN ({placeholders})"
            ), params)
            session.execute(text(
                f"DELETE FROM knowledge_entities WHERE id IN ({placeholders})"
            ), params)

        return {"purged": len(matches), "entities": matches}


# ── Evolution ─────────────────────────────────────────────────────────


@api_bp.route("/evolution/stats")
@empire_route
def api_evolution_stats(empire_id):
    """Get evolution stats."""
    from core.evolution.cycle import EvolutionCycleManager
    return EvolutionCycleManager(empire_id).get_stats().__dict__


@api_bp.route("/evolution/run", methods=["POST"])
@empire_route
def api_run_evolution(empire_id):
    """Run evolution cycle."""
    from core.evolution.cycle import EvolutionCycleManager
    result = EvolutionCycleManager(empire_id).run_full_cycle()
    return {
        "proposals": result.proposals_collected,
        "approved": result.approved,
        "applied": result.applied,
        "learnings": result.learnings,
    }


@api_bp.route("/evolution/evolve-prompts", methods=["POST"])
@empire_route
def api_evolve_prompts(empire_id):
    """Evolve lieutenant system prompts based on performance."""
    from core.evolution.prompt_evolution import PromptEvolver
    evolved = PromptEvolver(empire_id).evolve_all()
    return {
        "evolved_count": len(evolved),
        "lieutenants": [
            {"name": e.lieutenant_name, "confidence": e.confidence, "reasoning": e.reasoning[:200]}
            for e in evolved
        ],
    }


# ── Budget ────────────────────────────────────────────────────────────


@api_bp.route("/budget")
@empire_route
def api_budget(empire_id):
    """Get budget summary."""
    from core.routing.budget import BudgetManager
    report = BudgetManager(empire_id).get_budget_report()
    return {
        "daily_spend": report.daily_spend, "monthly_spend": report.monthly_spend,
        "daily_remaining": report.daily_remaining, "monthly_remaining": report.monthly_remaining,
        "alerts": [{"message": a.message, "severity": a.severity} for a in report.alerts],
    }


# ── Health ────────────────────────────────────────────────────────────


@api_bp.route("/health/debug")
def api_health_debug():
    """Debug endpoint — shows env vars, LLM connectivity, scheduler state."""
    import os
    import traceback

    result = {
        "redis_url_set": bool(os.environ.get("REDIS_URL")),
        "redis_url_prefix": (os.environ.get("REDIS_URL", "")[:25] + "...") if os.environ.get("REDIS_URL") else "not set",
        "anthropic_key_set": bool(os.environ.get("EMPIRE_ANTHROPIC_API_KEY")),
        "db_url_set": bool(os.environ.get("EMPIRE_DB_URL")),
        "db_url_prefix": (os.environ.get("EMPIRE_DB_URL", "")[:30] + "...") if os.environ.get("EMPIRE_DB_URL") else "not set",
    }

    try:
        from config.settings import get_settings
        result["settings_anthropic_key_set"] = bool(get_settings().anthropic_api_key)
    except Exception as e:
        result["settings_error"] = str(e)

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

    try:
        from llm.cache import get_cache
        cache = get_cache()
        result["cache_enabled"] = cache.enabled
        result["cache_stats"] = cache.get_stats()
    except Exception as e:
        result["cache_error"] = str(e)

    return jsonify(result)


@api_bp.route("/health")
@empire_route
def api_health(empire_id):
    """Comprehensive system health — DB, Redis, circuits, cache, budget, fleet."""
    from core.scheduler.health import HealthChecker
    report = HealthChecker(empire_id).run_all_checks()

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
        report["rate_limiter"] = {"enabled": get_rate_limiter().config.enabled}
    except Exception:
        report["rate_limiter"] = {"enabled": False}

    return report


# ── Replication ───────────────────────────────────────────────────────


@api_bp.route("/empires/generate", methods=["POST"])
@empire_route
def api_generate_empire(empire_id):
    """Generate a new empire."""
    data = _get_json_or_400()
    from core.replication.generator import EmpireGenerator
    result = EmpireGenerator().generate_empire(
        name=data.get("name", ""),
        template=data.get("template", ""),
        domain=data.get("domain", "general"),
        description=data.get("description", ""),
    )
    return {
        "empire_id": result.empire_id, "lieutenants": result.lieutenants_created,
        "ready": result.launch_ready,
    }, 201


@api_bp.route("/empires/templates")
def api_empire_templates():
    """Get empire templates."""
    from core.replication.generator import EmpireGenerator
    return jsonify(EmpireGenerator().get_templates())


# ── Web Search ────────────────────────────────────────────────────────


@api_bp.route("/search/web")
@empire_route
def api_web_search(empire_id):
    """Search the web."""
    query = request.args.get("q", "")
    if not query:
        return {"error": "Query parameter 'q' required"}, 400
    from core.search.web import WebSearcher
    return WebSearcher(empire_id).search_and_summarize(query, max_results=_clamp_limit(10))


@api_bp.route("/search/news")
@empire_route
def api_news_search(empire_id):
    """Search news articles."""
    query = request.args.get("q", "")
    if not query:
        return {"error": "Query parameter 'q' required"}, 400
    from core.search.web import WebSearcher
    response = WebSearcher(empire_id).search_news(
        query, max_results=_clamp_limit(10), time_range=request.args.get("range", "w"),
    )
    return {
        "query": query,
        "results": [{"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source, "published": r.published} for r in response.results],
        "total": response.total_results,
    }


@api_bp.route("/search/ai")
@empire_route
def api_ai_search(empire_id):
    """Search for AI-specific news and developments."""
    from core.search.web import WebSearcher
    topic = request.args.get("topic", "")
    response = WebSearcher(empire_id).search_ai_news(topic, max_results=_clamp_limit(10))
    return {
        "topic": topic,
        "results": [{"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source, "published": r.published} for r in response.results],
        "total": response.total_results,
    }


@api_bp.route("/search/papers")
@empire_route
def api_paper_search(empire_id):
    """Search for AI research papers."""
    topic = request.args.get("topic", "")
    if not topic:
        return {"error": "Query parameter 'topic' required"}, 400
    from core.search.web import WebSearcher
    response = WebSearcher(empire_id).search_ai_papers(topic, max_results=_clamp_limit(10))
    return {
        "topic": topic,
        "results": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in response.results],
        "total": response.total_results,
    }


@api_bp.route("/search/store", methods=["POST"])
@empire_route
def api_search_and_store(empire_id):
    """Search the web and store findings in knowledge graph + memory."""
    data = _get_json_or_400()
    query = data.get("query", "")
    if not query:
        return {"error": "Query required"}, 400
    from core.search.web import WebSearcher
    return WebSearcher(empire_id).search_and_store(query, max_results=data.get("max_results", 5))


@api_bp.route("/scrape", methods=["POST"])
@empire_route
def api_scrape_url(empire_id):
    """Scrape a URL and extract content."""
    data = _get_json_or_400()
    url = data.get("url", "")
    if not url:
        return {"error": "URL required"}, 400
    err = _validate_url(url)
    if err:
        return {"error": err}, 400
    from core.search.scraper import WebScraper
    page = WebScraper(empire_id).scrape_url(url)
    return {
        "url": url, "success": page.success, "title": page.title,
        "content": page.content[:10000], "word_count": page.word_count,
        "author": page.author, "date": page.date, "domain": page.domain,
        "error": page.error,
    }


@api_bp.route("/scrape/store", methods=["POST"])
@empire_route
def api_scrape_and_store(empire_id):
    """Scrape a URL and store in knowledge + memory."""
    data = _get_json_or_400()
    url = data.get("url", "")
    if not url:
        return {"error": "URL required"}, 400
    err = _validate_url(url)
    if err:
        return {"error": err}, 400
    from core.search.scraper import WebScraper
    return WebScraper(empire_id).scrape_and_store(url)


@api_bp.route("/sweep", methods=["POST"])
@rate_limit(requests_per_minute=3, requests_per_hour=20)
@empire_route
def api_intelligence_sweep(empire_id):
    """Run an intelligence sweep — proactive discovery across AI sources."""
    from core.search.sweep import IntelligenceSweep
    result = IntelligenceSweep(empire_id).run_full_sweep()
    return {
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
    }


@api_bp.route("/sweep/discoveries")
@empire_route
def api_sweep_discoveries(empire_id):
    """Get recent discoveries from intelligence sweeps."""
    from core.search.sweep import IntelligenceSweep
    return IntelligenceSweep(empire_id).get_recent_discoveries(limit=_clamp_limit(20))


@api_bp.route("/research", methods=["POST"])
@rate_limit(requests_per_minute=5, requests_per_hour=60)
@empire_route
def api_research_topic(empire_id):
    """Search, scrape, and synthesize research on a topic.

    Full pipeline: search -> scrape (with fallback to snippets) -> LLM synthesis -> store.
    """
    data = _get_json_or_400()
    topic = data.get("topic", "")
    if not topic:
        return {"error": "Topic required"}, 400

    max_sources = data.get("max_sources", 3)

    from core.search.scraper import WebScraper
    from core.search.web import WebSearcher

    scraper = WebScraper(empire_id)
    searcher = WebSearcher(empire_id)

    OPEN_DOMAINS = {
        "arxiv.org", "github.com", "huggingface.co", "simonwillison.net",
        "lilianweng.github.io", "openai.com", "anthropic.com", "ai.meta.com",
        "blog.google", "deepmind.google", "mistral.ai", "together.ai",
        "en.wikipedia.org", "techcrunch.com", "theverge.com", "arstechnica.com",
        "wired.com", "reuters.com", "apnews.com", "bbc.com", "macrumors.com",
    }

    # 1. Search multiple channels for sources
    all_results = []
    news = searcher.search_ai_news(topic, max_results=max_sources * 2)
    for r in news.results:
        all_results.append({"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source, "type": "news"})

    web = searcher.search(f"{topic} AI", max_results=max_sources * 2)
    seen_urls = {ar["url"] for ar in all_results}
    for r in web.results:
        if r.url not in seen_urls:
            all_results.append({"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source, "type": "web"})

    if not all_results:
        return {"topic": topic, "success": False, "error": "No search results found"}

    # 2. Sort: prefer open domains first
    def domain_priority(r):
        domain = r.get("source", "").lower()
        return 0 if any(od in domain for od in OPEN_DOMAINS) else 1

    all_results.sort(key=domain_priority)

    # 3. Try to scrape
    scraped = []
    scrape_failures = []
    for result in all_results[:max_sources * 3]:
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

    # 4. Build research context
    from core.search.credibility import CredibilityScorer
    cred_scorer = CredibilityScorer()

    source_texts = []
    source_info = []

    for page in scraped:
        cred = cred_scorer.score(page.url)
        cred_label = cred_scorer.format_for_prompt(page.url)
        source_texts.append(f"## {page.title}\nSource: {page.domain} | {page.date} {cred_label}\n\n{page.content[:3000]}")
        source_info.append({"title": page.title, "url": page.url, "domain": page.domain, "words": page.word_count, "type": "scraped", "credibility": cred.score, "tier": cred.tier})

    # Fallback to snippets
    if len(source_texts) < max_sources:
        scraped_urls = {s.url for s in scraped}
        for r in [r for r in all_results if r["url"] not in scraped_urls][:max_sources - len(source_texts)]:
            cred = cred_scorer.score(r.get("url", ""))
            cred_label = cred_scorer.format_for_prompt(r.get("url", ""))
            source_texts.append(f"## {r['title']}\nSource: {r['source']} (snippet only) {cred_label}\n\n{r['snippet']}")
            source_info.append({"title": r["title"], "url": r["url"], "domain": r["source"], "words": len(r["snippet"].split()), "type": "snippet", "credibility": cred.score, "tier": cred.tier})

    if not source_texts:
        return {"topic": topic, "success": False, "error": "No content available", "scrape_failures": scrape_failures}

    combined = "\n\n---\n\n".join(source_texts)

    # 5. LLM synthesis
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
    request_llm = LLMRequest(
        messages=[LLMMessage.user(prompt)],
        system_prompt="You are an AI research analyst. Synthesize sources accurately and identify what matters.",
        temperature=0.3,
        max_tokens=3000,
    )
    response = router.execute(request_llm, TaskMetadata(task_type="analysis", complexity="complex"))

    # 6. Store in memory
    from core.memory.manager import MemoryManager
    MemoryManager(empire_id).store(
        content=f"Research: {topic}\n\n{response.content[:5000]}",
        memory_type="semantic",
        title=f"Research: {topic}",
        category="research",
        importance=0.75,
        tags=["research", "synthesis", topic.lower().replace(" ", "_")],
        source_type="research",
    )

    return {
        "topic": topic,
        "success": True,
        "synthesis": response.content,
        "sources": source_info,
        "source_count": len(source_info),
        "scraped_count": len(scraped),
        "snippet_fallbacks": len(source_info) - len(scraped),
        "scrape_failures": scrape_failures[:5],
        "cost_usd": response.cost_usd,
    }


# ── RSS Feeds ─────────────────────────────────────────────────────────


@api_bp.route("/feeds")
@empire_route
def api_list_feeds(empire_id):
    """List configured RSS feeds."""
    from core.search.feeds import FeedReader
    return FeedReader(empire_id).list_feeds()


@api_bp.route("/feeds/latest")
@empire_route
def api_feed_latest(empire_id):
    """Get latest entries from all feeds."""
    category = request.args.get("category")
    from core.search.feeds import FeedReader
    entries = FeedReader(empire_id).fetch_latest(
        categories=[category] if category else None,
        max_total=_clamp_limit(20),
    )
    return [
        {"title": e.title, "url": e.url, "summary": e.summary[:300],
         "source": e.source_feed, "published": e.published, "tags": e.tags}
        for e in entries
    ]


@api_bp.route("/feeds/sync", methods=["POST"])
@empire_route
def api_feed_sync(empire_id):
    """Fetch all feeds and store new entries."""
    from core.search.feeds import FeedReader
    return FeedReader(empire_id).fetch_and_store()


# ── Credibility ───────────────────────────────────────────────────────


@api_bp.route("/credibility")
def api_check_credibility():
    """Check credibility of a URL."""
    url = request.args.get("url", "")
    if not url:
        return jsonify({"error": "URL parameter required"}), 400
    from core.search.credibility import CredibilityScorer
    score = CredibilityScorer().score(url)
    return jsonify({
        "url": url, "domain": score.domain, "score": score.score,
        "tier": score.tier, "category": score.category, "reasoning": score.reasoning,
    })


@api_bp.route("/credibility/tiers")
def api_credibility_tiers():
    """Get all sources organized by tier."""
    from core.search.credibility import get_source_tiers
    return jsonify(get_source_tiers())


# ── Research Pipeline ─────────────────────────────────────────────────


@api_bp.route("/pipeline/run", methods=["POST"])
@rate_limit(requests_per_minute=3)
@empire_route
def api_pipeline_run(empire_id):
    """Run the full research pipeline on a topic."""
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()
    depth = data.get("depth", "standard")

    if not topic:
        return {"error": "topic is required"}, 400
    if depth not in ("shallow", "standard", "deep"):
        return {"error": "depth must be shallow, standard, or deep"}, 400

    from core.research.pipeline import ResearchPipeline
    return ResearchPipeline(empire_id).run(
        topic, depth=depth, max_sources=data.get("max_sources", 8),
    ).to_dict()


# ── Model Routing ─────────────────────────────────────────────────────


@api_bp.route("/routing/tiers")
def api_routing_tiers():
    """Show the current model tiering map."""
    from llm.router import ModelRouter
    return jsonify(ModelRouter().get_tier_map())


# ── Iterative Deepening ──────────────────────────────────────────────


@api_bp.route("/deepening/candidates")
@empire_route
def api_deepening_candidates(empire_id):
    """Find topics that warrant deeper research."""
    from core.research.deepening import IterativeDeepener
    candidates = IterativeDeepener(empire_id).detect_candidates(max_candidates=10)
    return [{
        "topic": c.topic,
        "entity_names": c.entity_names[:10],
        "current_depth": c.current_depth,
        "signal_score": c.signal_score,
        "trigger_reason": c.trigger_reason,
    } for c in candidates]


@api_bp.route("/deepening/run", methods=["POST"])
@rate_limit(requests_per_minute=5)
@empire_route
def api_deepening_run(empire_id):
    """Trigger an iterative deepening cycle."""
    data = request.get_json(silent=True) or {}
    from core.research.deepening import IterativeDeepener
    results = IterativeDeepener(empire_id).run_deepening_cycle(
        max_topics=data.get("max_topics", 3),
    )
    return {
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
    }


