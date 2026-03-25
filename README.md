 # Empire AI

    Self-upgrading multi-agent AI system for
    autonomous AI research.

    Empire runs autonomous research on the latest AI
    developments — model releases, papers, techniques,
     tooling, agent architectures, and industry moves.
     Lieutenants research independently, debate in War
     Rooms, and compound knowledge over time.

    **35K+ lines of Python | 17 commits | Postgres |
    Flask**

    ## Architecture

    Directive → War Room (debate + plan) → Wave
    Execution → Retrospective → Memory
         ↑
                              |
         └──────────────── Evolution Cycle
    (self-improvement) ←────────────────┘

    - **ACE (Autonomous Cognitive Engine)** — 3-agent
    pipeline (planner → executor → critic) powering
    every lieutenant
    - **Bi-temporal Memory** — 4-tier memory
    (semantic, experiential, design, episodic) with
    valid time + transaction time tracking
    - **Knowledge Graph** — 22 entity schemas,
    8-dimension quality scoring, 3-stage fuzzy entity
    resolution
    - **War Rooms** — multi-lieutenant debate with 4
    strategies, Chief of Staff synthesis
    - **Evolution** — propose → review → implement →
    learn → repeat, including prompt self-evolution
    - **Intelligence Sweep** — proactive discovery
    across HuggingFace, GitHub, arXiv, RSS feeds, web
    search
    - **Ralph Wiggum Retry** — error injection, model
    escalation, sibling context
    - **Content Pipeline** — 5 report templates
    (briefing, deep dive, digest, competitive
    analysis, status report)
    - **Scheduler Daemon** — 14 autonomous jobs
    including sweep, compression, quality scoring,
    decay

    ## Lieutenants

    | Name | Domain | Focus |
    |---|---|---|
    | Model Intelligence | models | LLM releases,
    benchmarks, pricing, capabilities |
    | Research Scout | research | Papers, training
    techniques, alignment, scaling laws |
    | Agent Systems | agents | Multi-agent, tool use,
    frameworks, MCP |
    | Tooling & Infra | tooling | APIs, inference,
    vector DBs, deployment |
    | Industry & Strategy | industry | Company
    strategy, funding, enterprise adoption |
    | Open Source | open_source | Open weight models,
    HuggingFace, local inference |

    ## Quick Start

    ```bash
    # Clone
    git clone https://github.com/GaryisfromIndiana/Emp
    ireisgay.git
    cd Empireisgay

    # Setup
    python3 -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"

    # Configure
    cp .env.example .env
    # Edit .env — add your EMPIRE_ANTHROPIC_API_KEY

    # Database (Postgres recommended, SQLite works)
    # Postgres:
    # EMPIRE_DB_URL=postgresql://user:pass@localhost:5
    432/empire
    # SQLite:
    # EMPIRE_DB_URL=sqlite:///empire.db

    # Initialize
    python -m cli.commands init

    # Seed lieutenants
    python seed.py

    # Run
    python -m web.app
    # → http://localhost:5000

    API Endpoints (120+)

    Core

    GET  /api/empire              — Empire overview
    GET  /api/health              — System health (6
    checks)
    GET  /api/budget              — Cost tracking

    Lieutenants

    GET  /api/lieutenants         — List all
    lieutenants
    POST /api/lieutenants         — Create a
    lieutenant
    POST /api/lieutenants/:id/task — Submit a task

    Directives

    POST /api/directives          — Create a directive
    POST /api/directives/:id/execute — Execute full
    pipeline
    GET  /api/directives/:id/report  — Get research
    report

    Knowledge

    GET  /api/knowledge/stats     — Graph statistics
    GET  /api/knowledge/ask?q=... — Ask the knowledge
    graph
    GET  /api/knowledge/profile/:name — Entity profile
    GET  /api/knowledge/schemas   — 22 entity type
    schemas
    GET  /api/knowledge/quality   — 8-dimension
    quality scores

    Memory

    GET  /api/memory/stats        — Memory statistics
    POST /api/memory/compress     — LLM-powered
    compression
    GET  /api/memory/temporal/query — Bi-temporal
    queries

    Search & Research

    GET  /api/search/news?q=...   — Search AI news
    POST /api/research            — Full research
    pipeline (search → scrape → synthesize)
    POST /api/sweep               — Intelligence sweep
     across 5 sources
    POST /api/feeds/sync          — Sync RSS feeds
    GET  /api/credibility?url=... — Source credibility
     scoring

    Content

    POST /api/content/generate    — Generate formatted
     report
    POST /api/content/weekly-digest — Weekly AI digest
    POST /api/content/status-report — Empire status
    report
    GET  /api/content/templates   — Available
    templates

    Scheduler

    GET  /scheduler/jobs          — List 14 autonomous
     jobs
    POST /scheduler/tick          — Manual scheduler
    tick

    Memory System

    Empire's memory is bi-temporal — every fact
    tracks:
    - Valid time: when was this true in the real
    world?
    - Transaction time: when did Empire learn this?

    Memory lifecycle:
    Store → Bi-temporal metadata → Novelty check →
    Feedback loop
    → Temporal decay → LLM compression → Context
    window → Task execution

    - Auto-supersession: new facts automatically
    replace outdated ones
    - Memory compression: LLM distills clusters into
    concise summaries
    - Feedback loop: successful tasks boost related
    memory importance
    - Temporal decay: old episodic memories decay 2x,
    semantic 0.5x

    Knowledge Graph

    - 22 entity type schemas (AI model, company,
    paper, technique, benchmark, framework, etc.)
    - 8-dimension quality scoring (source reliability,
     recency, corroboration, completeness,
    consistency, citation quality, extraction
    confidence, update frequency)
    - 3-stage fuzzy resolution (exact → normalized →
    token overlap)
    - Enriched relations with temporal bounds and
    bidirectional labels
    - Graph queries: "What do we know about
    Anthropic?" → structured traversal

    Stack

    Python 3.12 · PostgreSQL · Flask · SQLAlchemy ·
    Pydantic · Claude API · APScheduler · DuckDuckGo ·
     Trafilatura · Feedparser
