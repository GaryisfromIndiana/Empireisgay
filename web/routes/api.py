"""REST API routes for programmatic access to Empire."""

from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request, current_app

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__)


# ── Empire ─────────────────────────────────────────────────────────────

@api_bp.route("/empire")
def get_empire():
    """Get current empire info."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        session = get_session()
        repo = EmpireRepository(session)
        health = repo.get_health_overview(empire_id)
        return jsonify(health)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/empire/network")
def get_network():
    """Get network stats across all empires."""
    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        session = get_session()
        repo = EmpireRepository(session)
        return jsonify(repo.get_network_stats())
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


@api_bp.route("/lieutenants", methods=["POST"])
def api_create_lieutenant():
    """Create a lieutenant."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json()
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
    data = request.get_json()
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
    data = request.get_json()
    from core.directives.manager import DirectiveManager
    dm = DirectiveManager(empire_id)
    result = dm.create_directive(
        title=data.get("title", ""),
        description=data.get("description", ""),
        priority=data.get("priority", 5),
    )
    return jsonify(result), 201


@api_bp.route("/directives/<directive_id>/execute", methods=["POST"])
def api_execute_directive(directive_id: str):
    """Execute a directive in a background thread.

    Returns immediately with status. Poll /directives/<id>/progress for updates.
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    import threading

    def run_directive():
        from core.directives.manager import DirectiveManager
        dm = DirectiveManager(empire_id)
        try:
            dm.execute_directive(directive_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Directive execution failed: %s", e)

    thread = threading.Thread(target=run_directive, daemon=True, name=f"directive-{directive_id[:8]}")
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
        limit=int(request.args.get("limit", 20)),
    )
    return jsonify([{"name": e.name, "type": e.entity_type, "confidence": e.confidence, "importance": e.importance} for e in entities])


@api_bp.route("/knowledge/entity/<entity_name>/neighbors")
def api_entity_neighbors(entity_name: str):
    """Get entity neighbors."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.knowledge.graph import KnowledgeGraph
    graph = KnowledgeGraph(empire_id)
    neighbors = graph.get_neighbors(entity_name, max_depth=int(request.args.get("depth", 2)))
    return jsonify([{"name": n.name, "type": n.entity_type, "depth": n.depth} for n in neighbors])


@api_bp.route("/knowledge/ask")
def api_knowledge_ask():
    """Ask the knowledge graph a question."""
    question = request.args.get("q", "")
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
    data = request.get_json()
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
    data = request.get_json()
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
        limit=int(request.args.get("limit", 20)),
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
        limit=int(request.args.get("limit", 20)),
    ))


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

@api_bp.route("/health")
def api_health():
    """System health check."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from core.scheduler.health import HealthChecker
    checker = HealthChecker(empire_id)
    return jsonify(checker.run_all_checks())


# ── Replication ────────────────────────────────────────────────────────

@api_bp.route("/empires/generate", methods=["POST"])
def api_generate_empire():
    """Generate a new empire."""
    data = request.get_json()
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
    max_results = int(request.args.get("limit", 10))
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
    max_results = int(request.args.get("limit", 10))
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
    max_results = int(request.args.get("limit", 10))
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
    max_results = int(request.args.get("limit", 10))
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
    data = request.get_json()
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
    data = request.get_json()
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
    data = request.get_json()
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "URL required"}), 400
    from core.search.scraper import WebScraper
    scraper = WebScraper(empire_id)
    return jsonify(scraper.scrape_and_store(url))


@api_bp.route("/sweep", methods=["POST"])
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
    return jsonify(sweep.get_recent_discoveries(limit=int(request.args.get("limit", 20))))


# ── Content Pipeline ───────────────────────────────────────────────────

@api_bp.route("/content/generate", methods=["POST"])
def api_generate_content():
    """Generate formatted content on a topic.

    Body: {"topic": "...", "template": "research_briefing", "context": "..."}
    Templates: research_briefing, weekly_digest, deep_dive, competitive_analysis, status_report
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json()
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
    data = request.get_json() or {}
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
    return jsonify(gen.get_stored_reports(limit=int(request.args.get("limit", 10))))


@api_bp.route("/content/render-topic", methods=["POST"])
def api_render_topic():
    """Generate and render a report as HTML directly."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json()
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
def api_research_topic():
    """Search, scrape, and synthesize research on a topic.

    Full pipeline: search → scrape (with fallback to snippets) → LLM synthesis → store.
    Tries multiple sources, prefers open sites, falls back to search snippets.
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json()
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
    max_total = int(request.args.get("limit", 20))
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
