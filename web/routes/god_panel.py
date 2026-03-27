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
import time
import uuid
from datetime import datetime, timezone
from flask import Blueprint, render_template, jsonify, request, current_app

logger = logging.getLogger(__name__)
god_panel_bp = Blueprint("god_panel", __name__)

# ── Command tracker — stores status/results for async commands ────────
_command_store: dict[str, dict] = {}
_command_lock = threading.Lock()
_MAX_STORED_COMMANDS = 200


def _track_command(command_id: str, command: str, action: str, topic: str) -> dict:
    """Register a new command in the tracker."""
    entry = {
        "id": command_id,
        "command": command,
        "action": action,
        "topic": topic,
        "status": "accepted",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "result": None,
        "error": None,
        "cost": 0.0,
    }
    with _command_lock:
        _command_store[command_id] = entry
        # Evict oldest if over limit
        if len(_command_store) > _MAX_STORED_COMMANDS:
            oldest = sorted(_command_store.keys(), key=lambda k: _command_store[k]["started_at"])
            for k in oldest[:len(_command_store) - _MAX_STORED_COMMANDS]:
                del _command_store[k]
    return entry


def _complete_command(command_id: str, result: dict | None = None, error: str | None = None) -> None:
    """Mark a command as completed."""
    with _command_lock:
        if command_id in _command_store:
            entry = _command_store[command_id]
            entry["status"] = "completed" if not error else "failed"
            entry["completed_at"] = datetime.now(timezone.utc).isoformat()
            entry["result"] = result
            entry["error"] = error
            entry["cost"] = (result or {}).get("research_cost", 0) or (result or {}).get("cost", 0)


def _update_command_status(command_id: str, status: str) -> None:
    """Update command status (e.g. 'running', 'researching')."""
    with _command_lock:
        if command_id in _command_store:
            _command_store[command_id]["status"] = status


@god_panel_bp.route("/")
def god_panel():
    """The God Panel — one interface to command everything."""
    empire_id = current_app.config.get("EMPIRE_ID", "")

    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        from db.repositories.lieutenant import LieutenantRepository
        from db.repositories.directive import DirectiveRepository
        from core.routing.budget import BudgetManager
        from core.knowledge.graph import KnowledgeGraph
        from core.memory.manager import MemoryManager

        session = get_session()
        try:
            # All empires in the network
            empire_repo = EmpireRepository(session)
            empires = empire_repo.get_active()
            empire_list = [
                {
                    "id": e.id,
                    "name": e.name,
                    "domain": e.domain,
                    "status": e.status,
                    "tasks": e.total_tasks_completed,
                    "cost": e.total_cost_usd,
                    "knowledge": e.total_knowledge_entries,
                }
                for e in empires
            ]

            # Current empire stats
            lt_repo = LieutenantRepository(session)
            lts = lt_repo.get_by_empire(empire_id, status="active")
            fleet = [
                {
                    "id": lt.id,
                    "name": lt.name,
                    "domain": lt.domain,
                    "performance": lt.performance_score,
                    "tasks": lt.tasks_completed,
                    "cost": lt.total_cost_usd,
                }
                for lt in sorted(lts, key=lambda x: x.performance_score, reverse=True)
            ]

            # Recent directives
            dir_repo = DirectiveRepository(session)
            recent = dir_repo.get_completed(empire_id, days=7, limit=10)
            active = dir_repo.get_active(empire_id)
            directives = {
                "active": [{"id": d.id, "title": d.title, "status": d.status} for d in active],
                "recent": [
                    {"id": d.id, "title": d.title, "quality": d.quality_score, "cost": d.total_cost_usd}
                    for d in recent
                ],
            }

            # Budget
            bm = BudgetManager(empire_id)
            budget = bm.get_budget_report(days=30)

            # Knowledge stats
            graph = KnowledgeGraph(empire_id)
            kg_stats = graph.get_stats()

            # Memory stats
            mm = MemoryManager(empire_id)
            mem_stats = mm.get_stats()

            # Scheduler
            scheduler_info = {}
            daemon = current_app.config.get("_SCHEDULER_DAEMON")
            if daemon:
                status = daemon.get_status()
                scheduler_info = {
                    "running": status.running,
                    "ticks": status.total_ticks,
                    "jobs": status.jobs_active,
                    "errors": status.errors,
                }

            context = {
                "empires": empire_list,
                "fleet": fleet,
                "directives": directives,
                "budget": {
                    "daily": budget.daily_spend,
                    "monthly": budget.monthly_spend,
                    "daily_remaining": budget.daily_remaining,
                },
                "knowledge": {
                    "entities": kg_stats.entity_count,
                    "relations": kg_stats.relation_count,
                },
                "memory": {
                    "total": mem_stats.total_count,
                    "by_type": mem_stats.by_type,
                },
                "scheduler": scheduler_info,
            }

            return render_template("god_panel.html", **context)

        finally:
            session.close()

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
    command = data.get("command", "").strip()

    if not command:
        return jsonify({"error": "No command provided"}), 400

    try:
        import json
        from llm.router import ModelRouter, TaskMetadata
        from llm.base import LLMRequest, LLMMessage
        router = ModelRouter(empire_id)

        total_cost = 0.0

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
            context_block += f"\n\n## Related Knowledge Graph Entities\n" + "\n".join(entity_lines)

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

        # Parse classification
        try:
            text = response.content
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                plan = json.loads(text[start:end])
            else:
                plan = {"action": "RESEARCH", "topic": command, "description": command, "lieutenants": []}
        except (json.JSONDecodeError, ValueError):
            plan = {"action": "RESEARCH", "topic": command, "description": command, "lieutenants": []}

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
        return jsonify({"error": str(e), "command": command}), 500


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
        discoveries = sweep.run_sweep()
        return {"status": "completed", "discoveries": len(discoveries) if isinstance(discoveries, list) else 0}

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

    elif action == "CONTENT":
        from core.content.generator import ContentGenerator
        gen = ContentGenerator(empire_id)
        report = gen.generate_topic_report(topic)
        return {"status": "completed", "report": report}

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
        entry = _command_store.get(command_id)
    if not entry:
        return jsonify({"error": "Command not found"}), 404
    return jsonify(entry)


@god_panel_bp.route("/commands")
def list_commands():
    """List all tracked God Panel commands (most recent first)."""
    with _command_lock:
        commands = sorted(
            _command_store.values(),
            key=lambda c: c["started_at"],
            reverse=True,
        )
    limit = request.args.get("limit", 50, type=int)
    status_filter = request.args.get("status")
    if status_filter:
        commands = [c for c in commands if c["status"] == status_filter]
    return jsonify(commands[:limit])


def _execute_autonomous_gap_research(empire_id: str, priority: int = 5) -> dict:
    """Empire finds its own knowledge gaps and researches to fill them.

    Flow:
    1. Scan KG for domains with least coverage
    2. Generate research topics for the weakest areas
    3. Run deep research on each topic
    4. Repeat for N rounds (configurable by priority)
    """
    import json
    from core.knowledge.graph import KnowledgeGraph
    from core.routing.budget import BudgetManager

    rounds = min(priority, 5)  # Higher priority = more rounds, max 5
    total_cost = 0.0
    topics_researched = []

    DOMAINS = {
        "models": "Latest LLM releases, benchmarks, pricing, architecture comparisons",
        "research": "Recent AI papers, training techniques, alignment research, scaling laws",
        "agents": "Multi-agent frameworks, tool use patterns, MCP developments, orchestration",
        "tooling": "Inference engines, vector databases, deployment tools, MLOps platforms",
        "industry": "AI company strategy, funding rounds, enterprise adoption trends",
        "open_source": "Open weight model releases, HuggingFace trends, local inference",
    }

    for round_num in range(1, rounds + 1):
        # Budget check each round
        bm = BudgetManager(empire_id)
        check = bm.check_budget(estimated_cost=0.10)
        if check.remaining_daily < 0.50:
            logger.info("Autoresearch stopping at round %d — budget low ($%.2f remaining)", round_num, check.remaining_daily)
            break

        # Find weakest domains
        graph = KnowledgeGraph(empire_id)
        domain_counts = {}
        for domain in DOMAINS:
            try:
                entities = graph.find_entities(query=domain, limit=100)
                domain_counts[domain] = len(entities) if entities else 0
            except Exception:
                domain_counts[domain] = 0

        sorted_domains = sorted(domain_counts.items(), key=lambda x: x[1])
        weak = sorted_domains[:2]  # 2 weakest per round

        for domain, count in weak:
            try:
                # Generate topic
                from llm.router import ModelRouter, TaskMetadata
                from llm.base import LLMRequest, LLMMessage

                router = ModelRouter(empire_id)
                topic_prompt = (
                    f"You are an AI research director. The '{domain}' knowledge domain has {count} entries, "
                    f"which is {'very low' if count < 20 else 'moderate'}.\n\n"
                    f"Domain focus: {DOMAINS[domain]}\n\n"
                    f"Already researched topics this session: {[t['topic'] for t in topics_researched]}\n\n"
                    f"Generate ONE specific, timely research topic that would fill the biggest gap. "
                    f"Focus on developments from early 2025. Do NOT repeat already-researched topics.\n\n"
                    f"Respond with ONLY the topic — one sentence, no explanation."
                )

                resp = router.execute(
                    LLMRequest(messages=[LLMMessage.user(topic_prompt)], max_tokens=100, temperature=0.7),
                    TaskMetadata(task_type="planning", complexity="simple"),
                )
                topic = resp.content.strip().strip('"')
                total_cost += resp.cost_usd

                if not topic:
                    continue

                # Run deep research on the topic
                logger.info("Autoresearch round %d: %s (domain=%s, entities=%d)", round_num, topic[:60], domain, count)
                research_result = _execute_deep_research(
                    empire_id, topic, f"Autonomous gap research for {domain}: {topic}",
                    [domain], "", False, priority,
                )
                total_cost += research_result.get("research_cost", 0)

                topics_researched.append({
                    "round": round_num,
                    "domain": domain,
                    "topic": topic,
                    "entities_before": count,
                    "success": research_result.get("status") == "completed",
                })

            except Exception as e:
                logger.warning("Autoresearch failed for %s: %s", domain, e)
                topics_researched.append({
                    "round": round_num,
                    "domain": domain,
                    "topic": f"Failed: {e}",
                    "success": False,
                })

    return {
        "status": "completed",
        "rounds_completed": min(round_num, rounds) if topics_researched else 0,
        "topics_researched": topics_researched,
        "total_cost": total_cost,
        "domains_covered": list(set(t["domain"] for t in topics_researched)),
    }


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


def _execute_deep_research(
    empire_id: str,
    topic: str,
    description: str,
    lieutenant_domains: list[str],
    prior_knowledge: str,
    build_on_existing: bool,
    priority: int,
) -> dict:
    """Execute the upgraded RESEARCH action with lieutenant perspectives.

    Flow:
    1. Run research pipeline (search → scrape → extract → synthesize)
    2. Get lieutenant perspectives on the findings
    3. Synthesize everything into a final brief
    4. Store compounded knowledge
    """
    import json
    result = {"status": "completed", "research_cost": 0.0}

    # ── 1. Research pipeline ────────────────────────────────────────
    try:
        from core.research.pipeline import ResearchPipeline
        pipeline = ResearchPipeline(empire_id)
        depth = "deep" if priority >= 7 else "standard"
        pipe_result = pipeline.run(topic, depth=depth)

        result["pipeline"] = {
            "stages": len(pipe_result.stages),
            "entities": pipe_result.total_entities,
            "relations": pipe_result.total_relations,
            "success": pipe_result.success,
        }
        result["research_cost"] += pipe_result.cost_usd

        raw_synthesis = pipe_result.synthesis or ""
    except Exception as e:
        logger.warning("Pipeline failed in deep research: %s", e)
        # Fallback to basic research
        from core.search.web import WebSearcher
        searcher = WebSearcher(empire_id)
        search_result = searcher.research_topic(topic, depth="deep")
        raw_synthesis = search_result.get("synthesis", "")
        result["pipeline"] = {"stages": 0, "fallback": True}
        result["research_cost"] += search_result.get("cost_usd", 0)

    if not raw_synthesis:
        result["synthesis"] = "Research produced no synthesis."
        return result

    # ── 2. Lieutenant perspectives ──────────────────────────────────
    # Domain → role descriptions for lieutenant perspectives
    DOMAIN_ROLES = {
        "models": ("Model Intelligence", "LLM releases, benchmarks, pricing, capabilities, architecture comparisons"),
        "research": ("Research Scout", "AI papers, training techniques, alignment research, scaling laws"),
        "agents": ("Agent Systems", "multi-agent architectures, tool use, frameworks, MCP, orchestration"),
        "tooling": ("Tooling & Infra", "APIs, inference engines, vector DBs, deployment, MLOps"),
        "industry": ("Industry & Strategy", "company strategy, funding rounds, enterprise AI adoption, market dynamics"),
        "open_source": ("Open Source", "open weight models, HuggingFace releases, local inference, community projects"),
    }

    lieutenant_insights = []
    if lieutenant_domains:
        try:
            from llm.router import ModelRouter, TaskMetadata
            from llm.base import LLMRequest, LLMMessage

            router = ModelRouter(empire_id)

            for domain in lieutenant_domains[:3]:  # Cap at 3 to control costs
                lt_name, lt_focus = DOMAIN_ROLES.get(domain, (domain.title(), domain))

                lt_prompt = (
                    f"You are {lt_name}, Empire's specialist in {lt_focus}.\n\n"
                    f"Research findings on '{topic}':\n{raw_synthesis[:3000]}\n\n"
                    f"From your domain perspective ({domain}), provide:\n"
                    f"1. What stands out as most significant?\n"
                    f"2. What's missing or needs deeper investigation?\n"
                    f"3. How does this connect to your domain?\n\n"
                    f"Be concise (3-5 sentences max)."
                )

                try:
                    lt_response = router.execute(
                        LLMRequest(
                            messages=[LLMMessage.user(lt_prompt)],
                            max_tokens=300,
                            temperature=0.3,
                        ),
                        TaskMetadata(task_type="analysis", complexity="moderate"),
                    )
                    lieutenant_insights.append({
                        "lieutenant": lt_name,
                        "domain": domain,
                        "perspective": lt_response.content,
                    })
                    result["research_cost"] += lt_response.cost_usd
                except Exception as e:
                    logger.debug("Lieutenant %s perspective failed: %s", domain, e)

        except Exception as e:
            logger.debug("Lieutenant perspectives failed: %s", e)

    result["lieutenant_perspectives"] = lieutenant_insights

    # ── 3. Final synthesis with all inputs ──────────────────────────
    try:
        from llm.router import ModelRouter, TaskMetadata
        from llm.base import LLMRequest, LLMMessage

        router = ModelRouter(empire_id)

        synthesis_parts = [f"## Research Findings\n{raw_synthesis[:4000]}"]

        if prior_knowledge and build_on_existing:
            synthesis_parts.append(f"\n## Empire's Prior Knowledge\n{prior_knowledge[:1500]}")

        if lieutenant_insights:
            lt_section = "\n## Lieutenant Perspectives\n"
            for lt in lieutenant_insights:
                lt_section += f"\n**{lt['lieutenant']}** ({lt['domain']}):\n{lt['perspective']}\n"
            synthesis_parts.append(lt_section)

        combined = "\n".join(synthesis_parts)

        final_prompt = (
            f"You are Empire's Chief of Staff. Synthesize all inputs about '{topic}' "
            f"into a final intelligence brief.\n\n"
            f"Structure:\n"
            f"1. **Executive Summary** (2-3 sentences)\n"
            f"2. **Key Findings** (bullet points)\n"
            f"3. **Lieutenant Insights** (what the specialists flagged)\n"
            f"4. **Knowledge Gaps** (what to investigate next)\n"
            f"5. **Strategic Implications** (what this means for AI)\n\n"
            f"Inputs:\n{combined[:8000]}"
        )

        final_response = router.execute(
            LLMRequest(
                messages=[LLMMessage.user(final_prompt)],
                max_tokens=1500,
                temperature=0.3,
            ),
            TaskMetadata(task_type="synthesis", complexity="complex"),
        )

        result["synthesis"] = final_response.content
        result["research_cost"] += final_response.cost_usd

        # ── 4. Store the compounded knowledge ───────────────────────
        try:
            from core.memory.manager import MemoryManager
            mm = MemoryManager(empire_id)
            mm.store(
                content=f"God Panel Research: {topic}\n\n{final_response.content}",
                memory_type="semantic",
                title=f"Research: {topic[:60]}",
                category="god_panel_research",
                importance=0.85,
                tags=["god_panel", "research", "synthesis"],
                source_type="god_panel",
                metadata={
                    "topic": topic,
                    "lieutenants_consulted": [lt["domain"] for lt in lieutenant_insights],
                    "had_prior_knowledge": bool(prior_knowledge),
                },
            )
        except Exception as e:
            logger.debug("Failed to store God Panel research memory: %s", e)

    except Exception as e:
        logger.warning("Final synthesis failed: %s", e)
        result["synthesis"] = raw_synthesis[:2000]

    return result


@god_panel_bp.route("/network/status")
def network_status():
    """Get status of all empires in the network."""
    try:
        from db.engine import get_session
        from db.repositories.empire import EmpireRepository
        session = get_session()
        try:
            repo = EmpireRepository(session)
            empires = repo.get_active()
            return jsonify([
                {
                    "id": e.id, "name": e.name, "domain": e.domain,
                    "status": e.status, "tasks": e.total_tasks_completed,
                    "cost": e.total_cost_usd, "knowledge": e.total_knowledge_entries,
                }
                for e in empires
            ])
        finally:
            session.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
