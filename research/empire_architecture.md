# Empire Current Architecture

This document describes the current implemented architecture in this repo. It is intentionally narrower than the product roadmap. For the north-star product direction, see `docs/ROADMAP.md`. For the recommended target architecture that bridges current implementation to the roadmap, see `docs/TARGET_ARCHITECTURE.md`. Unless a section is explicitly labeled otherwise, this file should be read as current-state only.

## System Scope

Empire currently operates as a single-empire AI research and research-ops system. The dominant implemented loop is directive intake, planning, execution, retrospective learning, and scheduled maintenance. Multi-empire concepts exist only as partial scaffolding.

## Core Execution Flow

The main directive lifecycle is:

1. Directive intake and persistence
2. War Room planning across selected lieutenants
3. Wave-based task execution
4. Review and retrospective synthesis
5. Memory and knowledge updates

This flow is implemented in the current codebase through `core/directives/manager.py`, `core/warroom/session.py`, and the lieutenant execution stack.

## Lieutenants

Lieutenants are the current specialist execution unit. They are persona-shaped specialists that all run the same ACE engine, rather than fully distinct agent architectures. War Rooms coordinate lieutenants for planning and debate; they are not the roadmap's hero/soldier lifecycle system.

## Memory

The implemented memory model is a 4-tier system:

- semantic
- experiential
- design
- episodic

That model is managed in `core/memory/manager.py`. The roadmap's five-tier memory model is not implemented in this repo today.

## Scheduler

There are two scheduler surfaces in the current codebase:

- The scheduler daemon auto-registers 8 default recurring jobs in `core/scheduler/daemon.py`.
- The scheduler job registry exposes 16 available job classes in `core/scheduler/jobs.py`.

Current-state docs should refer to those actual counts, not older job totals or the roadmap's larger process/job claims.

## Cross-Empire Scaffolding

The repo contains partial multi-empire scaffolding:

- empire generation templates in `core/replication/generator.py`
- empire-level repository queries in `db/repositories/empire.py`
- cross-empire knowledge sync in `core/knowledge/bridge.py`
- replication routes and UI in `web/routes/replication.py`

This is useful scaffolding, but it is not the same as a fully operational multi-empire platform with mature coordination and synthesis.

## Explicitly Not Implemented

The following roadmap concepts should not be described as current functionality in this repo:

- five-tier memory
- heroes/soldiers lifecycle
- six armories
- prediction markets
- DeFi swaps
- stock trading
- calibrated prediction/Brier loops
- Redis-based hero coordination
- 78 scheduled jobs across 5 processes
- 4 fully operational empires
