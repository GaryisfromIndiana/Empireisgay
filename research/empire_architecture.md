# Empire AI — System Architecture
### Self-Upgrading Multi-Agent AI Research System

**Version:** March 2026
**Deployment:** Railway (empireisgay-production.up.railway.app)
**Repository:** github.com/GaryisfromIndiana/Empireisgay

---

## 1. System Overview

Empire AI is an autonomous AI research system that runs 24/7, conducting research on AI developments, debating findings, and evolving itself. It operates without human intervention through a scheduler daemon, 6 specialized lieutenants, and a self-improvement evolution cycle.

```
┌─────────────────────────────────────────────────────┐
│                    EMPIRE AI                         │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Flask    │  │ Scheduler│  │ Evolution        │  │
│  │ Web UI   │  │ Daemon   │  │ Cycle            │  │
│  │ + API    │  │ (5 min)  │  │ (propose→review  │  │
│  │          │  │          │  │  →implement      │  │
│  │ 6 workers│  │ 8 jobs   │  │  →learn)         │  │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
│       │              │                 │             │
│  ┌────┴──────────────┴─────────────────┴──────────┐ │
│  │              ACE Pipeline                       │ │
│  │         Planner → Executor → Critic             │ │
│  └────┬──────────────┬─────────────────┬──────────┘ │
│       │              │                 │             │
│  ┌────┴────┐  ┌──────┴──────┐  ┌──────┴──────┐     │
│  │ 4-Tier  │  │ Knowledge   │  │ War Rooms   │     │
│  │ Memory  │  │ Graph       │  │ (Debate)    │     │
│  └─────────┘  └─────────────┘  └─────────────┘     │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │           6 Lieutenants                       │   │
│  │  Model Intel · Research Scout · Agent Systems │   │
│  │  Tooling & Infra · Industry · Open Source     │   │
│  └──────────────────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         │             │             │
    ┌────┴────┐  ┌─────┴────┐  ┌────┴────┐
    │Postgres │  │  Redis   │  │Anthropic│
    │(Railway)│  │ (Cache)  │  │  API    │
    └─────────┘  └──────────┘  └─────────┘
```

---

## 2. Core Architecture

### 2.1 ACE Pipeline (Autonomous Cognitive Engine)

Three-agent pipeline powering every lieutenant task:

```
Input Task
    │
    ▼
┌─────────┐    ┌──────────┐    ┌─────────┐
│ Planner │───▶│ Executor │───▶│ Critic  │
│(claude- │    │(claude-  │    │(claude- │
│haiku-4.5│    │sonnet-4) │    │haiku-4.5│
└─────────┘    └──────────┘    └─────────┘
    │               │               │
    │          Quality Gates        │
    │          (min score,          │
    │           hallucination       │
    │           check)              │
    ▼                               ▼
 Task Plan              Approved/Rejected Result
```

**Files:** `core/ace/planner.py`, `core/ace/executor.py`, `core/ace/critic.py`, `core/ace/pipeline.py`

### 2.2 4-Tier Memory System

```
┌────────────────────────────────────────┐
│            Memory Manager              │
│                                        │
│  ┌──────────┐  ┌──────────────┐        │
│  │ Semantic  │  │ Experiential │        │
│  │ (facts,   │  │ (lessons,    │        │
│  │  domain   │  │  outcomes,   │        │
│  │  knowledge│  │  patterns)   │        │
│  └──────────┘  └──────────────┘        │
│                                        │
│  ┌──────────┐  ┌──────────────┐        │
│  │ Design   │  │ Episodic     │        │
│  │ (patterns,│  │ (raw task    │        │
│  │  arch     │  │  records,    │        │
│  │  decisions│  │  events)     │        │
│  └──────────┘  └──────────────┘        │
│                                        │
│  Consolidation: episodic → experiential│
│  Decay: temporal importance reduction  │
│  Compression: LLM-powered summarization│
│  Novelty Check: deduplication          │
│  Context Window: token-budget aware    │
└────────────────────────────────────────┘
```

**Files:** `core/memory/manager.py`, `core/memory/semantic.py`, `core/memory/experiential.py`, `core/memory/design.py`, `core/memory/episodic.py`, `core/memory/consolidation.py`, `core/memory/compression.py`

### 2.3 Knowledge Graph

```
┌────────────────────────────────────────┐
│          Knowledge Graph               │
│                                        │
│  Entities ──relationships──▶ Entities  │
│                                        │
│  Types: concept, framework, product,   │
│         company, person, metric,       │
│         process, technology, theory    │
│                                        │
│  Features:                             │
│  • Entity extraction from research     │
│  • Relation discovery                  │
│  • Confidence scoring                  │
│  • Duplicate resolution                │
│  • Quality scoring                     │
│  • Central entity analysis             │
│  • Cross-empire knowledge bridge       │
└────────────────────────────────────────┘
```

**Files:** `core/knowledge/graph.py`, `core/knowledge/entities.py`, `core/knowledge/search.py`, `core/knowledge/maintenance.py`, `core/knowledge/bridge.py`

### 2.4 War Rooms

Multi-lieutenant debate, planning, and synthesis:

```
Directive Input
    │
    ▼
┌─────────────────────────────┐
│         War Room            │
│                             │
│  Phase 1: Planning          │
│  Each lieutenant proposes   │
│  tasks from their domain    │
│                             │
│  Phase 2: Debate            │
│  Strategies:                │
│  • Adversarial              │
│  • Collaborative            │
│  • Round-Robin              │
│                             │
│  Phase 3: Synthesis         │
│  Merge proposals into       │
│  unified plan               │
│                             │
│  Phase 4: Retrospective     │
│  Analyze outcomes, extract  │
│  learnings for memory       │
└─────────────────────────────┘
```

**Files:** `core/warroom/session.py`, `core/warroom/debate.py`, `core/warroom/debate_strategies.py`, `core/warroom/synthesis.py`, `core/warroom/retrospective.py`

### 2.5 Evolution System

Self-improvement cycle:

```
┌─────────┐    ┌──────────┐    ┌───────────┐    ┌─────────┐
│ Propose │───▶│ Review   │───▶│ Implement │───▶│ Learn   │
│         │    │          │    │           │    │         │
│ Analyze │    │ Score &  │    │ Apply     │    │ Store   │
│ system  │    │ approve/ │    │ approved  │    │ outcome │
│ state,  │    │ reject   │    │ changes   │    │ in      │
│ generate│    │ proposals│    │           │    │ memory  │
│ ideas   │    │          │    │           │    │         │
└─────────┘    └──────────┘    └───────────┘    └─────────┘
     ▲                                              │
     └──────────────────────────────────────────────┘
                    Feedback Loop
```

**Files:** `core/evolution/cycle.py`, `core/evolution/proposer.py`, `core/evolution/reviewer.py`, `core/evolution/executor.py`

---

## 3. Lieutenant Fleet

| Lieutenant | Domain | Focus Areas |
|-----------|--------|-------------|
| Model Intelligence | models | LLM releases, benchmarks, pricing, capabilities |
| Research Scout | research | Papers, training techniques, alignment, scaling laws |
| Agent Systems | agents | Multi-agent, tool use, frameworks, MCP |
| Tooling & Infra | tooling | APIs, inference, vector DBs, deployment |
| Industry & Strategy | industry | Company strategy, funding, enterprise adoption |
| Open Source | open_source | Open weight models, HuggingFace, local inference |

Each lieutenant has:
- Domain-specific persona and system prompt
- Performance scoring (tasks completed, quality, cost)
- Workload balancing via TTL-cached lookup
- Task assignment based on domain relevance

**Files:** `core/lieutenant/base.py`, `core/lieutenant/manager.py`, `core/lieutenant/persona.py`, `core/lieutenant/registry.py`, `core/lieutenant/workload.py`

---

## 4. Infrastructure Layer

### 4.1 LLM Router

```
Request → Route (complexity/budget/capabilities) → Execute → Cache → Record Cost
              │                                        │
              ├── Model Selection (tier-based)          ├── Circuit Breaker
              ├── Fallback Model                        ├── Redis Cache (24h TTL)
              └── Cost Estimation                       └── Budget Tracking
```

**Model Catalog:**
- claude-sonnet-4 (Tier 2, primary executor)
- claude-haiku-4.5 (Tier 3, planning/critic)
- gpt-4o (Tier 2, fallback)
- gpt-4o-mini (Tier 4, cheap tasks)

**Files:** `llm/router.py`, `llm/anthropic.py`, `llm/openai.py`, `llm/cache.py`, `llm/base.py`

### 4.2 Database Layer

```
PostgreSQL (Railway)
    │
    ├── empires
    ├── lieutenants
    ├── directives
    ├── tasks
    ├── memory_entries
    ├── knowledge_entities
    ├── knowledge_relations
    ├── budget_logs
    ├── health_checks
    ├── evolution_proposals
    ├── war_room_sessions
    ├── task_dependencies
    ├── audit_log
    └── _schema_versions (migrations)

Connection Pool: 20 connections, 40 overflow
Session Management: try/finally cleanup on all routes
Migrations: 6 versions with rollback support
```

**Files:** `db/engine.py`, `db/models.py`, `db/migrations.py`, `db/repositories/*.py`

### 4.3 Scheduler Daemon

8 autonomous jobs running on 5-minute tick interval:

| Job | Interval | Purpose |
|-----|----------|---------|
| health_check | 300s | System health monitoring |
| directive_check | 300s | Process pending directives |
| budget_check | 900s | Budget limit enforcement |
| memory_decay | 3600s | Temporal importance decay |
| knowledge_maintenance | 14400s | Graph cleanup and quality |
| learning_cycle | 21600s | Extract learnings from outcomes |
| evolution_cycle | 43200s | Self-improvement proposals |
| cleanup | 86400s | Remove expired/low-value data |

**Features:** Auto-re-enable after 10-tick cooldown, file-lock for multi-worker safety

**Files:** `core/scheduler/daemon.py`, `core/scheduler/jobs.py`, `core/scheduler/health.py`

### 4.4 Security & Resilience

```
┌─────────────────────────────────────┐
│ Rate Limiting                       │
│ • Per-client (IP/API key)           │
│ • Per-route custom limits           │
│ • 429 responses with Retry-After    │
├─────────────────────────────────────┤
│ Circuit Breaker                     │
│ • Per-provider (anthropic, openai)  │
│ • 15 failure threshold              │
│ • 30s recovery timeout              │
│ • Auto half-open → closed           │
├─────────────────────────────────────┤
│ Input Validation                    │
│ • JSON body validation (abort 400)  │
│ • Query param type coercion         │
│ • String sanitization               │
│ • Dict recursive sanitization       │
├─────────────────────────────────────┤
│ LLM Response Cache (Redis)          │
│ • 24h TTL, SHA-256 keyed            │
│ • Cache hits return cost_usd=0      │
│ • Graceful degradation if Redis down│
└─────────────────────────────────────┘
```

### 4.5 Search & Content Pipeline

```
Topic → Web Search (DuckDuckGo) → Scrape (Trafilatura)
    → Credibility Scoring → LLM Synthesis
    → Entity Extraction → Knowledge Graph
    → Memory Storage → Content Generation
```

**Files:** `core/search/web.py`, `core/search/scraper.py`, `core/search/credibility.py`, `core/search/feeds.py`, `core/search/cache.py`, `core/content/generator.py`

---

## 5. Deployment Architecture

```
┌─────────────────────────────────────────┐
│              Railway                     │
│                                         │
│  ┌───────────────────────┐              │
│  │   Empireisgay         │              │
│  │   (GitHub Deploy)     │              │
│  │                       │              │
│  │   Docker Container    │              │
│  │   Python 3.12-slim    │              │
│  │   Gunicorn            │              │
│  │   6 workers × 4 threads│             │
│  │   = 24 concurrent     │              │
│  │                       │              │
│  │   Port: $PORT (5000)  │              │
│  └───────┬───────────────┘              │
│          │                              │
│  ┌───────┴───────┐  ┌───────────────┐   │
│  │  PostgreSQL   │  │    Redis      │   │
│  │  (persistent) │  │  (LLM cache)  │   │
│  │  14 tables    │  │  24h TTL      │   │
│  │  6 migrations │  │               │   │
│  └───────────────┘  └───────────────┘   │
│                                         │
│  Public URL:                            │
│  empireisgay-production.up.railway.app  │
└─────────────────────────────────────────┘
```

**Environment Variables:**
- EMPIRE_ANTHROPIC_API_KEY
- EMPIRE_DB_URL (postgresql://...)
- EMPIRE_FLASK_SECRET_KEY
- EMPIRE_FLASK_DEBUG=false
- REDIS_URL
- PORT=5000

---

## 6. Web UI Routes

| Section | Routes | Purpose |
|---------|--------|---------|
| Dashboard | / | System overview, fleet stats, budget, research |
| Lieutenants | /lieutenants/* | Fleet management, performance |
| Directives | /directives/* | Research task management |
| War Rooms | /warrooms/* | Multi-agent debate sessions |
| Knowledge | /knowledge/* | Entity graph exploration |
| Memory | /memory/* | Memory search and stats |
| Evolution | /evolution/* | Self-improvement proposals |
| Budget | /budget/* | Cost tracking and limits |
| Scheduler | /scheduler/* | Autonomous job management |
| Network | /network/* | Cross-empire replication |
| Settings | /settings/* | Configuration |
| API | /api/* | Full REST API (50+ endpoints) |

---

## 7. Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| Web Framework | Flask 3.x + Gunicorn |
| Database | PostgreSQL (SQLAlchemy 2.x ORM) |
| Cache | Redis 5.x |
| LLM Providers | Anthropic (Claude), OpenAI (GPT-4o) |
| Search | DuckDuckGo (ddgs) |
| Scraping | Trafilatura |
| Feeds | feedparser (RSS) |
| Validation | Pydantic 2.x |
| Deployment | Railway (Docker) |
| Version Control | GitHub |

---

## 8. File Structure

```
empire/
├── config/
│   └── settings.py          # Pydantic settings, model catalog
├── core/
│   ├── ace/                  # Planner → Executor → Critic pipeline
│   ├── content/              # Report generation
│   ├── directives/           # Directive intake, planning, execution
│   ├── evolution/            # Self-improvement cycle
│   ├── knowledge/            # Entity graph, search, maintenance
│   ├── lieutenant/           # Agent management, personas
│   ├── memory/               # 4-tier memory system
│   ├── replication/          # Cross-empire sync
│   ├── retry/                # Ralph Wiggum retry with escalation
│   ├── routing/              # Budget management, pricing
│   ├── scheduler/            # Daemon, jobs, health checks
│   ├── search/               # Web search, scraping, feeds
│   └── warroom/              # Debate, synthesis, retrospective
├── db/
│   ├── engine.py             # Connection pool, session management
│   ├── models.py             # SQLAlchemy ORM models
│   ├── migrations.py         # Schema versioning
│   └── repositories/         # Data access layer
├── llm/
│   ├── anthropic.py          # Claude client
│   ├── openai.py             # GPT client
│   ├── router.py             # Smart model selection
│   ├── cache.py              # Redis-backed response cache
│   └── schemas.py            # Pydantic output schemas
├── utils/
│   ├── circuit_breaker.py    # Provider resilience
│   ├── validators.py         # Input sanitization
│   ├── crypto.py             # Token generation
│   ├── events.py             # Event system
│   ├── metrics.py            # Performance metrics
│   └── text.py               # Text utilities
├── web/
│   ├── app.py                # Flask factory, scheduler init
│   ├── middleware/            # Rate limiting
│   ├── routes/               # 13 route blueprints
│   └── templates/            # Jinja2 HTML templates
├── research/                 # Generated research papers
├── Dockerfile                # Production container
├── railway.toml              # Railway deployment config
├── pyproject.toml            # Dependencies
└── seed.py                   # Database initialization
```

---

## 9. Current Stats (March 26, 2026)

- **Knowledge Entities:** 68+
- **Relations:** 65+
- **Memories:** 183+
- **Lieutenant Performance:** 87% avg
- **Scheduler:** Running (8 jobs, 0 errors)
- **Evolution Cycles:** 3 (6 proposals, 1 approved)
- **Research Topics Processed:** 40+
- **Codebase:** ~30,000 lines of Python
