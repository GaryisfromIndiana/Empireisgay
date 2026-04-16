"""God Panel — unified command interface across all empires.

The God Panel is the brain of Empire. Every command flows through here:
1. Memory check — what does Empire already know about this topic?
2. Classification — which action type fits best?
3. Lieutenant routing — which specialists should weigh in?
4. Execution — research, pipeline, directive, war room, etc.
5. Knowledge compounding — findings feed back into KG + memory
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime

from flask import Blueprint, current_app, jsonify, render_template, request

logger = logging.getLogger(__name__)
god_panel_bp = Blueprint("god_panel", __name__)

# ── Command tracker — DB-backed with in-memory cache for fast polling ──
_command_cache: dict[str, dict] = {}
_command_lock = threading.Lock()
_MAX_CACHED = 200


def _deterministic_command_plan(command: str) -> dict | None:
    """Return a local fallback plan for obvious command intents."""
    lowered = command.lower()

    if any(token in lowered for token in ("health", "status", "system check", "check system")):
        action = "STATUS"
    elif any(token in lowered for token in ("sweep", "scan sources", "discoveries", "intelligence")):
        action = "SWEEP"
    elif any(token in lowered for token in ("evolve", "evolution", "improvement cycle")):
        action = "EVOLVE"
    elif any(token in lowered for token in ("war room", "debate", "argue", "competing views")):
        action = "WARROOM"
    elif any(token in lowered for token in ("audit", "quality issues", "contaminated entities")):
        action = "AUDIT"
    elif any(token in lowered for token in ("pipeline", "search scrape extract synthesize")):
        action = "PIPELINE"
    elif any(token in lowered for token in ("autoresearch", "auto research", "knowledge gaps", "find gaps")):
        action = "AUTORESEARCH"
    elif "directive" in lowered:
        action = "DIRECTIVE"
    else:
        return None

    return {
        "action": action,
        "topic": command,
        "description": command,
        "lieutenants": [],
        "priority": 5,
        "build_on_existing": False,
    }


def _track_command(command_id: str, command: str, action: str, topic: str) -> dict:
    """Register a new command — persisted to its own table, cached in memory."""
    entry = {
        "id": command_id,
        "command": command,
        "action": action,
        "topic": topic,
        "status": "accepted",
        "started_at": datetime.now(UTC).isoformat(),
        "completed_at": None,
        "result": None,
        "error": None,
        "cost": 0.0,
    }
    with _command_lock:
        _command_cache[command_id] = entry
        if len(_command_cache) > _MAX_CACHED:
            for k in list(_command_cache.keys())[:len(_command_cache) - _MAX_CACHED]:
                del _command_cache[k]
    try:
        from db.engine import session_scope
        from db.models import GodPanelCommand
        empire_id = current_app.config.get("EMPIRE_ID", "")
        with session_scope() as session:
            session.add(GodPanelCommand(
                id=command_id, empire_id=empire_id,
                command=command, action=action, topic=topic,
            ))
    except Exception as e:
        logger.debug("Failed to persist command: %s", e)
    return entry


def _complete_command(command_id: str, result: dict | None = None, error: str | None = None) -> None:
    """Mark a command as completed — updates DB and cache."""
    now = datetime.now(UTC)
    cost = (result or {}).get("research_cost", 0) or (result or {}).get("cost", 0)
    status = "completed" if not error else "failed"

    with _command_lock:
        if command_id in _command_cache:
            entry = _command_cache[command_id]
            entry["status"] = status
            entry["completed_at"] = now.isoformat()
            entry["result"] = result
            entry["error"] = error
            entry["cost"] = cost

    try:
        from db.engine import session_scope
        from db.models import GodPanelCommand
        with session_scope() as session:
            cmd = session.get(GodPanelCommand, command_id)
            if cmd:
                cmd.status = status
                cmd.completed_at = now
                cmd.error = error
                cmd.cost_usd = cost
                if result and not error:
                    cmd.result_json = {k: v for k, v in result.items()
                                       if k in ("status", "research_cost", "topics_researched",
                                                 "discoveries", "proposals", "applied")}
    except Exception as e:
        logger.debug("Failed to update command in DB: %s", e)


def _update_command_status(command_id: str, status: str) -> None:
    """Update command status (e.g. 'running', 'researching')."""
    with _command_lock:
        if command_id in _command_cache:
            _command_cache[command_id]["status"] = status
    try:
        from db.engine import session_scope
        from db.models import GodPanelCommand
        with session_scope() as session:
            cmd = session.get(GodPanelCommand, command_id)
            if cmd:
                cmd.status = status
    except Exception as e:
        logger.debug("Failed to update command status: %s", e)


def _load_command_from_db(command_id: str) -> dict | None:
    """Load a command from DB if not in cache."""
    try:
        from db.engine import read_session
        from db.models import GodPanelCommand
        with read_session() as session:
            cmd = session.get(GodPanelCommand, command_id)
            if cmd:
                return cmd.to_dict()
    except Exception:
        pass
    return None


@god_panel_bp.route("/")
def god_panel():
    """The God Panel — one interface to command everything."""
    empire_id = current_app.config.get("EMPIRE_ID", "")

    try:
        from core.knowledge.graph import KnowledgeGraph
        from core.memory.manager import MemoryManager
        from core.routing.budget import BudgetManager
        from db.engine import read_session
        from db.repositories.directive import DirectiveRepository
        from db.repositories.empire import EmpireRepository
        from db.repositories.lieutenant import LieutenantRepository

        with read_session() as session:
            # All empires in the network
            empire_repo = EmpireRepository(session)
            empires = empire_repo.get_active()
            empire_list = [
                {"id": e.id, "name": e.name, "domain": e.domain, "status": e.status,
                 "tasks": e.total_tasks_completed, "cost": e.total_cost_usd, "knowledge": e.total_knowledge_entries}
                for e in empires
            ]

            # Current empire stats
            lt_repo = LieutenantRepository(session)
            lts = lt_repo.get_by_empire(empire_id, status="active")
            real_costs = lt_repo.get_real_costs_bulk([lt.id for lt in lts])
            fleet = [
                {"id": lt.id, "name": lt.name, "domain": lt.domain,
                 "performance": lt.performance_score, "tasks": lt.tasks_completed,
                 "cost": real_costs.get(lt.id, 0.0)}
                for lt in sorted(lts, key=lambda x: x.performance_score, reverse=True)
            ]

            # Recent directives
            dir_repo = DirectiveRepository(session)
            recent = dir_repo.get_completed(empire_id, days=7, limit=10)
            active = dir_repo.get_active(empire_id)
            directives = {
                "active": [{"id": d.id, "title": d.title, "status": d.status} for d in active],
                "recent": [{"id": d.id, "title": d.title, "quality": d.quality_score, "cost": d.total_cost_usd} for d in recent],
            }

        # Budget
        bm = BudgetManager(empire_id)
        budget = bm.get_budget_report(days=30)

        # Knowledge stats
        kg_stats = KnowledgeGraph(empire_id).get_stats()

        # Memory stats
        mem_stats = MemoryManager(empire_id).get_stats()

        # Scheduler
        scheduler_info = {}
        daemon = current_app.config.get("_SCHEDULER_DAEMON")
        if daemon:
            status = daemon.get_status()
            scheduler_info = {"running": status.running, "ticks": status.total_ticks,
                              "jobs": status.jobs_active, "errors": status.errors}

        return render_template("god_panel.html",
            empires=empire_list, fleet=fleet, directives=directives,
            budget={"daily": budget.daily_spend, "monthly": budget.monthly_spend, "daily_remaining": budget.daily_remaining},
            knowledge={"entities": kg_stats.entity_count, "relations": kg_stats.relation_count},
            memory={"total": mem_stats.total_count, "by_type": mem_stats.by_type},
            scheduler=scheduler_info,
        )

    except Exception as e:
        logger.error("God Panel error: %s", e)
        return render_template("god_panel.html", error=str(e))


@god_panel_bp.route("/command", methods=["POST"])
def execute_command():
    """Execute a natural-language command through the full Empire brain.

    Upgraded flow:
    1. Memory recall — check what Empire already knows
    2. Knowledge graph check — find related entities
    3. LLM classification — pick the right action + lieutenants
    4. Execute action (with lieutenant perspectives for RESEARCH)
    5. Compound results — store findings back to KG + memory
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json(silent=True) or {}
    raw_command = data.get("command", "").strip()

    # Extract the actual topic — callers send {"command":"research","args":{"topic":"..."}}
    # The real content is in args.topic, not in command (which is just "research").
    args = data.get("args", {})
    topic_from_args = ""
    if isinstance(args, dict):
        topic_from_args = args.get("topic", "") or args.get("description", "")

    # Build the full command text the LLM will classify
    command = topic_from_args if topic_from_args else raw_command
    if not command:
        return jsonify({"error": "No command or topic provided"}), 400

    try:
        total_cost = 0.0
        plan = _deterministic_command_plan(command)

        # ── Step 1: Check what Empire already knows ─────────────────────
        prior_knowledge = ""
        related_entities = []
        try:
            from core.memory.manager import MemoryManager
            mm = MemoryManager(empire_id)
            memories = mm.recall(query=command, memory_types=["semantic", "experiential"], limit=5)
            if memories:
                prior_parts = []
                for m in memories:
                    content = getattr(m, "content", "") if not isinstance(m, dict) else m.get("content", "")
                    title = getattr(m, "title", "") if not isinstance(m, dict) else m.get("title", "")
                    if content:
                        prior_parts.append(f"- {title}: {content[:200]}" if title else f"- {content[:200]}")
                if prior_parts:
                    prior_knowledge = "Empire's existing knowledge on this topic:\n" + "\n".join(prior_parts[:5])
        except Exception as e:
            logger.debug("Memory recall for God Panel failed: %s", e)

        try:
            from core.knowledge.graph import KnowledgeGraph
            graph = KnowledgeGraph(empire_id)
            entities = graph.find_entities(query=command, limit=5)
            if entities:
                related_entities = [
                    {"name": getattr(e, "name", ""), "type": getattr(e, "entity_type", ""), "description": getattr(e, "description", "")[:100]}
                    for e in entities
                ]
        except Exception as e:
            logger.debug("KG search for God Panel failed: %s", e)

        # ── Step 2: Classify with full context ──────────────────────────
        context_block = ""
        if prior_knowledge:
            context_block += f"\n\n## What Empire Already Knows\n{prior_knowledge}"
        if related_entities:
            entity_lines = [f"- {e['name']} ({e['type']}): {e['description']}" for e in related_entities[:5]]
            context_block += "\n\n## Related Knowledge Graph Entities\n" + "\n".join(entity_lines)

        if plan is None:
            try:
                from llm.base import LLMMessage, LLMRequest
                from llm.router import ModelRouter, TaskMetadata

                router = ModelRouter(empire_id)
                classify_prompt = (
                    "You are the God Panel — the brain of an autonomous AI research system called Empire.\n"
                    "Empire has 6 lieutenant specialists:\n"
                    "  - Model Intelligence (models): LLM releases, benchmarks, pricing, capabilities\n"
                    "  - Research Scout (research): Papers, training techniques, alignment, scaling\n"
                    "  - Agent Systems (agents): Multi-agent, tool use, frameworks, MCP\n"
                    "  - Tooling & Infra (tooling): APIs, inference, vector DBs, deployment\n"
                    "  - Industry & Strategy (industry): Company strategy, funding, enterprise\n"
                    "  - Open Source (open_source): Open weight models, HuggingFace, local inference\n\n"
                    "Available actions:\n"
                    "- RESEARCH: Deep research on a topic — searches web, consults lieutenants, compounds knowledge\n"
                    "- DIRECTIVE: Create a multi-lieutenant directive for complex multi-step work\n"
                    "- WARROOM: Multi-lieutenant debate where specialists argue from their domain\n"
                    "- SWEEP: Intelligence sweep — scan all sources for new discoveries\n"
                    "- EVOLVE: Trigger a self-improvement evolution cycle\n"
                    "- AUDIT: Deep audit of the knowledge graph for quality issues\n"
                    "- STATUS: Report full system status and health\n"
                    "- CONTENT: Generate a polished report on a topic\n"
                    "- PIPELINE: Full 5-stage research pipeline (search→scrape→extract→deepen→synthesize)\n"
                    "- AUTORESEARCH: Empire finds its own knowledge gaps and autonomously researches to fill them\n\n"
                    "IMPORTANT: For research-oriented commands, prefer RESEARCH (engages lieutenants) "
                    "over PIPELINE (no lieutenants). Use PIPELINE only when the user specifically wants "
                    "raw data extraction. Use DIRECTIVE for complex multi-step tasks. Use WARROOM when "
                    "the user wants debate or competing perspectives.\n"
                    f"{context_block}\n\n"
                    f'User command: "{command}"\n\n'
                    "Respond with EXACTLY this JSON:\n"
                    '{"action": "ACTION_TYPE", "topic": "refined topic", '
                    '"description": "what to do and why", '
                    '"lieutenants": ["domain1", "domain2"], "priority": 1-10, '
                    '"build_on_existing": true/false}'
                )

                response = router.execute(
                    LLMRequest(
                        messages=[LLMMessage.user(classify_prompt)],
                        max_tokens=400,
                        temperature=0.2,
                    ),
                    TaskMetadata(task_type="classification", complexity="simple"),
                )
                total_cost += response.cost_usd

                from llm.schemas import safe_json_loads
                fallback = {
                    "action": "RESEARCH",
                    "topic": command,
                    "description": command,
                    "lieutenants": [],
                    "priority": 5,
                    "build_on_existing": False,
                }
                plan = safe_json_loads(response.content, default=fallback)
            except Exception as e:
                logger.warning("God Panel classification failed, using local fallback: %s", e)
                plan = {
                    "action": "RESEARCH",
                    "topic": command,
                    "description": command,
                    "lieutenants": [],
                    "priority": 5,
                    "build_on_existing": False,
                }

        action = plan.get("action", "RESEARCH").upper()
        topic = plan.get("topic", command)
        description = plan.get("description", command)
        priority = plan.get("priority", 5)
        assigned_lts = plan.get("lieutenants", [])
        build_on = plan.get("build_on_existing", False)

        result = {
            "command": command,
            "action": action,
            "plan": plan,
            "prior_knowledge_found": bool(prior_knowledge),
            "related_entities": len(related_entities),
        }

        # ── Step 3: Execute (all heavy actions run async) ─────────────
        command_id = str(uuid.uuid4())[:12]
        _track_command(command_id, command, action, topic)
        result["command_id"] = command_id
        app = current_app._get_current_object()

        # STATUS is lightweight — run synchronously
        if action == "STATUS":
            from core.scheduler.health import HealthChecker
            checker = HealthChecker(empire_id)
            result["status"] = "completed"
            result["health"] = checker.run_all_checks()
            _complete_command(command_id, result)
            result["cost"] = total_cost
            return jsonify(result)

        # Everything else runs in a background thread
        def _run_async(app_ref, cmd_id, act, eid, top, desc, lts, prior, build, pri):
            with app_ref.app_context():
                _update_command_status(cmd_id, "running")
                try:
                    res = _dispatch_action(act, eid, top, desc, lts, prior, build, pri)
                    _complete_command(cmd_id, res)
                except Exception as e:
                    logger.error("Command %s (%s) failed: %s", cmd_id, act, e)
                    _complete_command(cmd_id, error=str(e))

        threading.Thread(
            target=_run_async,
            args=(app, command_id, action, empire_id, topic, description,
                  assigned_lts, prior_knowledge, build_on, priority),
            daemon=True,
        ).start()

        result["status"] = "accepted"
        result["message"] = f"{action} running in background"
        result["poll_url"] = f"/god/command/{command_id}/status"
        result["cost"] = total_cost
        return jsonify(result)

    except Exception as e:
        logger.error("God Panel command failed: %s", e)
        return jsonify({"error": "Internal server error", "command": command}), 500


def _dispatch_action(
    action: str, empire_id: str, topic: str, description: str,
    lieutenant_domains: list[str], prior_knowledge: str,
    build_on_existing: bool, priority: int,
) -> dict:
    """Dispatch an action to the appropriate handler. Runs in background thread."""
    if action == "RESEARCH":
        return _execute_deep_research(
            empire_id, topic, description, lieutenant_domains,
            prior_knowledge, build_on_existing, priority,
        )

    elif action == "DIRECTIVE":
        from core.directives.manager import DirectiveManager
        dm = DirectiveManager(empire_id)
        directive = dm.create_directive(
            title=topic, description=description,
            priority=priority, source="god_panel",
        )
        directive_id = directive.get("id", "")
        if directive_id:
            dm2 = DirectiveManager(empire_id)
            dm2.execute_directive(directive_id)
        return {"status": "completed", "directive_id": directive_id}

    elif action == "WARROOM":
        from core.directives.manager import DirectiveManager
        dm = DirectiveManager(empire_id)
        directive = dm.create_directive(
            title=f"Debate: {topic}",
            description=f"War Room debate: {description}. Each lieutenant argues from their domain perspective.",
            priority=priority, source="god_panel",
        )
        directive_id = directive.get("id", "")
        if directive_id:
            dm2 = DirectiveManager(empire_id)
            dm2.execute_directive(directive_id)
        return {"status": "completed", "directive_id": directive_id}

    elif action == "SWEEP":
        from core.search.sweep import IntelligenceSweep
        sweep = IntelligenceSweep(empire_id)
        result = sweep.run_full_sweep()
        return {
            "status": "completed",
            "total_found": result.total_found,
            "novel_items": result.novel_items,
            "stored_memories": result.stored_memories,
            "stored_entities": result.stored_entities,
        }

    elif action == "EVOLVE":
        from core.evolution.cycle import EvolutionCycleManager
        ecm = EvolutionCycleManager(empire_id)
        evo_result = ecm.run_full_cycle()
        return {"status": "completed", "proposals": evo_result.proposals_collected, "applied": evo_result.applied}

    elif action == "AUDIT":
        from core.knowledge.maintenance import KnowledgeMaintainer
        maintainer = KnowledgeMaintainer(empire_id)
        audit = maintainer.deep_llm_audit(batch_size=20)
        return {"status": "completed", "audit": audit}

    elif action == "PIPELINE":
        from core.research.pipeline import ResearchPipeline
        pipeline = ResearchPipeline(empire_id)
        depth = "deep" if priority >= 7 else "standard"
        pipe_result = pipeline.run(topic, depth=depth)
        result = {"status": "completed", "pipeline": pipe_result.to_dict()}
        if pipe_result.synthesis:
            result["synthesis"] = pipe_result.synthesis[:2000]
        return result

    elif action == "AUTORESEARCH":
        return _execute_autonomous_gap_research(empire_id, priority)

    else:
        # Unknown action — fall back to research
        return _execute_deep_research(
            empire_id, topic, description, lieutenant_domains,
            prior_knowledge, build_on_existing, priority,
        )


@god_panel_bp.route("/command/<command_id>/status")
def command_status(command_id):
    """Poll the status of an async God Panel command."""
    with _command_lock:
        entry = _command_cache.get(command_id)
    if not entry:
        # Try loading from DB (survives deploys)
        entry = _load_command_from_db(command_id)
    if not entry:
        return jsonify({"error": "Command not found"}), 404
    return jsonify(entry)


@god_panel_bp.route("/commands")
def list_commands():
    """List all tracked God Panel commands (most recent first)."""
    limit = request.args.get("limit", 50, type=int)
    status_filter = request.args.get("status")

    try:
        from sqlalchemy import desc, select

        from db.engine import read_session
        from db.models import GodPanelCommand

        with read_session() as session:
            stmt = (
                select(GodPanelCommand)
                .where(GodPanelCommand.empire_id == current_app.config.get("EMPIRE_ID", ""))
                .order_by(desc(GodPanelCommand.started_at))
            )
            if status_filter:
                stmt = stmt.where(GodPanelCommand.status == status_filter)
            stmt = stmt.limit(limit)
            commands = [cmd.to_dict() for cmd in session.execute(stmt).scalars().all()]

        # Merge in any in-memory entries not yet persisted
        db_ids = {c["id"] for c in commands}
        with _command_lock:
            for entry in _command_cache.values():
                if entry["id"] not in db_ids:
                    if not status_filter or entry["status"] == status_filter:
                        commands.append(entry)

        commands.sort(key=lambda c: c.get("started_at", ""), reverse=True)
        return jsonify(commands[:limit])

    except Exception:
        # Fallback to cache-only if DB unavailable
        with _command_lock:
            commands = list(_command_cache.values())
        if status_filter:
            commands = [c for c in commands if c["status"] == status_filter]
        commands.sort(key=lambda c: c.get("started_at", ""), reverse=True)
        return jsonify(commands[:limit])


def _execute_autonomous_gap_research(empire_id: str, priority: int = 5) -> dict:
    """Empire finds its own knowledge gaps and researches to fill them."""
    from core.research.deep import execute_autonomous_gap_research
    return execute_autonomous_gap_research(empire_id, priority)


@god_panel_bp.route("/autoresearch", methods=["POST"])
def trigger_autoresearch():
    """Trigger autonomous gap research directly via API."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json(silent=True) or {}
    rounds = min(data.get("rounds", 3), 10)

    command_id = str(uuid.uuid4())[:12]
    _track_command(command_id, "Autonomous gap research", "AUTORESEARCH", "knowledge gaps")

    max_questions = min(rounds * 2, 10)

    app = current_app._get_current_object()
    def _run(app_ref, cmd_id, eid, max_q):
        with app_ref.app_context():
            _update_command_status(cmd_id, "running")
            try:
                from core.research.autoresearcher import AutoResearcher
                researcher = AutoResearcher(eid)
                result = researcher.run_cycle(max_questions=max_q)
                _complete_command(cmd_id, result.to_dict())
            except Exception as e:
                logger.error("Autoresearch failed: %s", e)
                _complete_command(cmd_id, error=str(e))

    threading.Thread(target=_run, args=(app, command_id, empire_id, max_questions), daemon=True).start()

    return jsonify({
        "status": "accepted",
        "command_id": command_id,
        "max_questions": max_questions,
        "poll_url": f"/god/command/{command_id}/status",
        "message": f"AutoResearcher running: gaps → questions → search → extract → synthesize ({max_questions} questions max)",
    })


@god_panel_bp.route("/warroom", methods=["POST"])
def trigger_warroom():
    """Trigger an autonomous war room debate.

    Optionally pass {"topic": "...", "domains": ["models","agents",...]}
    to force a specific topic. Otherwise auto-detects from recent research.
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    data = request.get_json(silent=True) or {}
    forced_topic = data.get("topic", "")
    forced_domains = data.get("domains", [])

    command_id = str(uuid.uuid4())[:12]
    _track_command(command_id, forced_topic or "Auto-detect debate topic", "WARROOM", forced_topic or "autonomous")

    app = current_app._get_current_object()

    def _run(app_ref, cmd_id, eid, topic, domains):
        with app_ref.app_context():
            _update_command_status(cmd_id, "running")
            try:
                if topic and domains:
                    # Forced topic — run directly
                    from core.warroom.session import WarRoomSession
                    from db.engine import get_session
                    from db.models import _generate_id
                    from db.repositories.lieutenant import LieutenantRepository

                    session_db = get_session()
                    try:
                        lt_repo = LieutenantRepository(session_db)
                        all_lts = lt_repo.get_by_empire(eid, status="active")

                        war_room = WarRoomSession(
                            session_id=_generate_id(), empire_id=eid,
                            session_type="manual_debate",
                        )
                        for lt in all_lts:
                            if lt.domain in domains:
                                war_room.add_participant(lt.id, lt.name, lt.domain)

                        result = war_room.start_debate(topic)
                        _complete_command(cmd_id, {
                            "topic": topic, "domains": domains,
                            "participants": len(war_room.participants),
                            "contributions": result.get("participant_count", 0),
                            "synthesis": result.get("synthesis", {}),
                        })
                    finally:
                        session_db.close()
                else:
                    # Auto-detect — find a debate-worthy topic from recent research
                    from core.warroom.session import run_autonomous_debate
                    result = run_autonomous_debate(eid)
                    _complete_command(cmd_id, result)
            except Exception as e:
                logger.error("War room failed: %s", e)
                _complete_command(cmd_id, error=str(e))

    threading.Thread(target=_run, args=(app, command_id, empire_id, forced_topic, forced_domains), daemon=True).start()

    return jsonify({
        "status": "accepted",
        "command_id": command_id,
        "topic": forced_topic or "auto-detecting from recent research",
        "poll_url": f"/god/command/{command_id}/status",
        "message": "War Room debate starting — lieutenants will argue from their domain perspectives",
    })


def _execute_deep_research(
    empire_id: str,
    topic: str,
    description: str,
    lieutenant_domains: list[str],
    prior_knowledge: str,
    build_on_existing: bool,
    priority: int,
) -> dict:
    """Execute deep research with lieutenant perspectives."""
    from core.research.deep import execute_deep_research
    return execute_deep_research(
        empire_id, topic, description, lieutenant_domains,
        prior_knowledge, build_on_existing, priority,
    )


@god_panel_bp.route("/network/status")
def network_status():
    """Get status of all empires in the network."""
    try:
        from db.engine import repo_scope
        from db.repositories.empire import EmpireRepository

        with repo_scope(EmpireRepository) as repo:
            empires = repo.get_active()
            return jsonify([
                {
                    "id": e.id, "name": e.name, "domain": e.domain,
                    "status": e.status, "tasks": e.total_tasks_completed,
                    "cost": e.total_cost_usd, "knowledge": e.total_knowledge_entries,
                }
                for e in empires
            ])
    except Exception as e:
        logger.error("API error: %s", e)
        return jsonify({"error": "Internal server error"}), 500
