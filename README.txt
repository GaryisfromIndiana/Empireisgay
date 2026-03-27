================================================================================
                            EMPIRE AI
          Self-Upgrading Multi-Agent AI Research System
================================================================================

Empire is an autonomous AI research system that continuously monitors,
researches, and compounds knowledge about the AI landscape. It runs 24/7
on Railway with zero human intervention — researching papers, tracking
model releases, debating strategy, and improving itself.

--------------------------------------------------------------------------------
WHAT IT DOES
--------------------------------------------------------------------------------

  - Autonomous Research: 14 scheduled jobs scan the web, arXiv, HuggingFace,
    GitHub, and RSS feeds for AI developments every few hours.

  - Knowledge Graph: Entities and relations extracted from every piece of
    research. 22 entity types (models, papers, companies, techniques, etc.)
    with 8-dimension quality scoring and 3-stage fuzzy deduplication.

  - 4-Tier Memory: Semantic, experiential, design, and episodic memory
    with time-based decay, consolidation, and compression.

  - War Rooms: Multi-lieutenant debates where specialists argue from their
    domain perspective. 4 debate strategies + Chief of Staff synthesis.

  - Self-Improvement: Evolution cycles propose, review, implement, and
    learn from system changes. The system literally upgrades itself.

  - God Panel: Natural language command interface. Type a command,
    Empire classifies it, routes it to the right subsystem, and returns
    results. Supports RESEARCH, DIRECTIVE, WARROOM, SWEEP, EVOLVE,
    AUDIT, STATUS, CONTENT, and PIPELINE actions.

  - Research Pipeline: 5-stage orchestrated research —
    SEARCH -> SCRAPE -> EXTRACT -> DEEPEN -> SYNTHESIZE.
    Takes a topic and produces entities, relations, and a synthesis report.

  - Smart Model Tiering: Routes tasks to the optimal model —
    Haiku 4.5 for cheap tasks, Sonnet 4 for agent work, Opus 4 for
    heavy infra like synthesis and evolution.

--------------------------------------------------------------------------------
LIEUTENANTS (6 AI SPECIALISTS)
--------------------------------------------------------------------------------

  Model Intelligence   | models      | LLM releases, benchmarks, pricing
  Research Scout       | research    | Papers, training techniques, alignment
  Agent Systems        | agents      | Multi-agent, tool use, frameworks, MCP
  Tooling & Infra      | tooling     | APIs, inference, vector DBs, deployment
  Industry & Strategy  | industry    | Company strategy, funding, enterprise
  Open Source           | open_source | Open weight models, HuggingFace, local

  Each lieutenant runs on the ACE (Autonomous Cognitive Engine) — a 3-agent
  pipeline: Planner -> Executor -> Critic. If a task fails, it escalates
  through model tiers and retries with error context (Ralph Wiggum retry).

  Auto Lieutenant Spawning: When 5+ knowledge graph entities cluster around
  a topic no existing lieutenant covers, a new specialist is automatically
  created.

--------------------------------------------------------------------------------
ARCHITECTURE
--------------------------------------------------------------------------------

  Web Layer
    Flask app with 11 blueprints, 120+ API endpoints
    Session auth (web UI) + API key auth (programmatic)
    Rate limiting per client IP/API key
    Gunicorn (2 workers, 4 threads) behind Railway

  Core Engine
    core/ace/         ACE pipeline (planner, executor, critic)
    core/knowledge/   Knowledge graph, entity extraction, quality scoring
    core/memory/      4-tier memory with decay and consolidation
    core/search/      Web search, scraping, intelligence sweep, feeds
    core/research/    Iterative deepening, shallow enrichment, pipeline
    core/directives/  Multi-lieutenant research workflow orchestration
    core/warroom/     Debate strategies, synthesis, chief of staff
    core/evolution/   Self-improvement proposals and implementation
    core/scheduler/   14 autonomous jobs, Postgres advisory locks
    core/routing/     Budget management, cost tracking
    core/lieutenant/  Lieutenant management, persona system
    core/content/     Report generation, digests
    core/replication/ Cross-empire knowledge bridge

  LLM Layer
    llm/router.py     Smart model routing with 17 task-type tiers
    llm/anthropic.py  Claude API client (Opus, Sonnet, Haiku)
    llm/openai.py     OpenAI API client (GPT-4o, o3-mini)
    llm/cache.py      Redis-backed response cache (24h TTL)
    utils/circuit_breaker.py  Circuit breaker per provider

  Database
    PostgreSQL on Railway (SQLite for local dev)
    16 SQLAlchemy models
    Connection pool: 5 + 10 overflow with auto-cleanup
    TrackedSession: force-closes leaked sessions after 60s

--------------------------------------------------------------------------------
SCHEDULER (14 AUTONOMOUS JOBS)
--------------------------------------------------------------------------------

  Every 5 min:   health_check, directive_check
  Every 15 min:  budget_check
  Every 1 hour:  memory_decay
  Every 4 hours: knowledge_maintenance, duplicate_resolution
  Every 6 hours: learning_cycle, autonomous_research,
                 quality_scoring, shallow_enrichment
  Every 8 hours: iterative_deepening
  Every 12 hours: evolution_cycle, intelligence_sweep,
                  memory_compression
  Every 24 hours: cleanup, content_generation, auto_spawn

  Uses Postgres advisory locks so multiple workers don't duplicate jobs.
  Auto-disables jobs after 20 consecutive errors; re-enables after 10 ticks.

--------------------------------------------------------------------------------
SMART MODEL TIERING
--------------------------------------------------------------------------------

  HAIKU 4.5 (cheap, fast):
    classification, extraction, tagging, routing,
    summarization, formatting

  SONNET 4 (agent work):
    research, analysis, code, general, creative, debate

  OPUS 4 (heavy infra):
    synthesis, evolution, planning, audit, expert reasoning

  Fallback chain stays within Anthropic: Haiku -> Sonnet -> Opus.
  Last-resort loop tries every available model before failing.

--------------------------------------------------------------------------------
TECH STACK
--------------------------------------------------------------------------------

  Language:    Python 3.12
  Web:         Flask + Gunicorn
  Database:    PostgreSQL (prod) / SQLite (dev)
  ORM:         SQLAlchemy 2.0
  Config:      Pydantic Settings
  LLMs:        Anthropic Claude (primary), OpenAI (optional)
  Search:      DuckDuckGo (ddgs), Trafilatura, Feedparser
  Cache:       Redis (optional, for LLM response caching)
  Deploy:      Docker -> Railway
  Scheduler:   Custom daemon with APScheduler-style job registry

--------------------------------------------------------------------------------
RUNNING LOCALLY
--------------------------------------------------------------------------------

  # Setup
  cd empire && python3 -m venv .venv && source .venv/bin/activate
  pip install -e .

  # Set your API key
  export ANTHROPIC_API_KEY=sk-ant-...

  # Run the web UI
  python -m web.app
  # Open http://localhost:5000

  # Or via CLI
  python -m cli.commands serve
  python -m cli.commands scheduler start

--------------------------------------------------------------------------------
DEPLOYING TO RAILWAY
--------------------------------------------------------------------------------

  1. Push to GitHub (Railway auto-deploys from main branch)
  2. Add Postgres plugin in Railway dashboard
  3. Set environment variables:
       ANTHROPIC_API_KEY=sk-ant-...
       EMPIRE_DB_URL=postgresql://...  (auto-set by Postgres plugin)
       EMPIRE_AUTH_PASSWORD=...        (optional, enables login)
       EMPIRE_API_KEY=...              (optional, for API auth)
       REDIS_URL=redis://...           (optional, for LLM caching)
  4. Railway builds from Dockerfile and deploys
  5. Healthcheck: /ping (no DB, no auth, instant)

  The scheduler starts automatically on Postgres. On SQLite,
  start it manually via /scheduler/start.

--------------------------------------------------------------------------------
KEY API ENDPOINTS
--------------------------------------------------------------------------------

  GET  /ping                        Health check (plain "ok")
  GET  /api/health/db               Connection pool status
  GET  /api/empire                  Empire info
  GET  /api/lieutenants             List lieutenants
  GET  /api/knowledge/entities      Knowledge graph entities
  GET  /api/knowledge/stats         Graph statistics
  GET  /api/memory/stats            Memory statistics
  GET  /api/routing/tiers           Model tiering map

  POST /api/pipeline/run            Run research pipeline
       {"topic": "...", "depth": "standard|deep|shallow"}

  POST /api/deepening/run           Trigger iterative deepening
  POST /api/enrichment/run          Trigger entity enrichment

  POST /god/command                 God Panel natural language command
       {"command": "Research the latest MCP developments"}

  GET  /api/deepening/candidates    Topics queued for deepening
  GET  /api/enrichment/targets      Entities needing enrichment

--------------------------------------------------------------------------------
CONNECTION POOL SAFETY
--------------------------------------------------------------------------------

  Three layers prevent Postgres connection exhaustion:

  Layer 1 — TrackedSession: Force-closes any session open > 60 seconds.
            Logs a warning so leaked close() calls can be found.

  Layer 2 — Pool overflow recovery: If pool is exhausted, disposes all
            connections and retries once before raising.

  Layer 3 — Flask teardown: scoped_session.remove() runs after every
            web request. Sessions can never leak from route handlers.

  Monitor: GET /api/health/db shows checked_in, checked_out, overflow.

--------------------------------------------------------------------------------
PROJECT STATS
--------------------------------------------------------------------------------

  66 commits
  77+ Python modules in core/
  16 database models
  120+ API endpoints
  14 autonomous scheduler jobs
  22 knowledge entity types
  17 model tiering rules
  6 AI lieutenant specialists
  4 memory tiers
  4 war room debate strategies
  3 LLM providers supported
  5-stage research pipeline

================================================================================
  Built with Claude Code — https://claude.ai/code
================================================================================
