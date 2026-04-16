# Empire AI

Empire is a Python/Flask research-ops system for autonomous AI research. The current repo implements directive planning, lieutenant execution, knowledge and memory storage, and scheduled maintenance loops for a single empire.

## Roadmap / Product Direction

See [docs/ROADMAP.md](docs/ROADMAP.md).

`/Users/asd/Desktop/empire_deck_external.html` is the north-star product roadmap for Empire. This repo is the implemented research-ops foundation today; the deck describes a broader multi-empire platform that is planned, not already shipped.

For current implemented architecture, see [research/empire_architecture.md](research/empire_architecture.md).

For the recommended target architecture that bridges today's repo to the roadmap, see [docs/TARGET_ARCHITECTURE.md](docs/TARGET_ARCHITECTURE.md).

For the concrete first implementation slice toward that architecture, see [docs/PHASE1_CONTROL_PLANE_SPEC.md](docs/PHASE1_CONTROL_PLANE_SPEC.md).

## Current Implemented Platform

- Directive pipeline: directive intake -> War Room planning -> wave execution -> review and retrospective
- Lieutenants: persona-shaped specialists that all run the shared ACE pipeline
- Memory: 4-tier memory system with semantic, experiential, design, and episodic memories
- Knowledge graph: entity extraction, quality scoring, and maintenance loops
- Scheduler: 16 available job classes, with 8 default recurring jobs auto-registered by the daemon
- Cross-empire support: partial scaffolding for replication, empire generation, and knowledge sync
- Web UI + API: dashboard, directives, lieutenants, knowledge, memory, scheduler, budget, and replication views

## Reality vs Roadmap

The current codebase is best understood as a single-empire AI research foundation with some multi-empire scaffolding. The roadmap extends that into a broader platform with additional memory layers, hero/soldier lifecycle management, armory-style execution, calibrated prediction loops, and operational cross-empire synthesis. Those roadmap concepts are documented in `docs/ROADMAP.md` and should not be treated as implemented unless current-state docs explicitly say so.

## Quick Start

```bash
git clone https://github.com/GaryisfromIndiana/Empireisgay.git
cd Empireisgay

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit .env with your local settings and API keys

python -m cli.commands init
python seed.py
python -m web.app
```

The local app runs at `http://localhost:5000`.

## Core Flow

```text
Directive
  -> War Room planning
  -> Wave execution
  -> Review + retrospective
  -> Memory + knowledge updates
  -> Scheduled maintenance and evolution loops
```

## Stack

Python 3.12, Flask, SQLAlchemy, Pydantic, APScheduler, Anthropic/OpenAI clients, DuckDuckGo search, Trafilatura, Feedparser, SQLite/Postgres.
