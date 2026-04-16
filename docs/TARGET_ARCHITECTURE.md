# Empire Target Architecture

This document proposes the target architecture that best fits Empire's current codebase and the roadmap in `docs/ROADMAP.md`.

It is not a claim that the current repo already implements this design. It is the recommended architecture to grow toward from the current single-empire research foundation.

## Executive Summary

Empire should not evolve into a large distributed system yet.

The right next architecture is a modular monolith with a durable control plane:

- keep the current research core: directives, War Rooms, lieutenants, ACE, memory, and knowledge graph
- move long-running work onto durable jobs and worker processes
- separate product domains into explicit bounded contexts instead of hiding future platform behavior inside prompts and JSON blobs
- treat cross-empire coordination as a control-plane problem, not just a replication problem
- delay service decomposition until there is real operational pressure for it

This gives Empire a path from today's research-ops system to the roadmap without forcing an early rewrite.

## Architectural Position

### What To Keep

- Python application stack
- SQLAlchemy data access
- directive -> planning -> execution -> review flow as the current research core
- War Room and lieutenant concepts as the current specialist coordination layer
- knowledge and memory systems as supporting intelligence infrastructure

### What To Change

- replace in-process orchestration with durable workflow execution
- replace thread-local/background runtime assumptions with worker-safe execution
- replace loosely typed future concepts with explicit domain models
- replace "single process owns everything" with a control plane plus workers

### What Not To Do Yet

- do not split the system into many microservices
- do not rename current concepts just to match roadmap language
- do not build hero/soldier, armory, prediction, or trading features on top of the current directive manager as-is

## Recommended Target Shape

### 1. Modular Monolith + Workers

Use one primary application codebase and one primary relational database, with separate process roles:

- API/UI process
- scheduler/control-plane process
- worker process pool
- optional sync/network worker process

All of these can live in the same repo and share the same domain modules.

This is the right tradeoff because:

- Empire is still one product with tightly coupled domain logic
- the roadmap requires stronger execution semantics more than independent deployment
- the current codebase is not mature enough to justify service boundaries yet

## Bounded Contexts

Empire should grow into these bounded contexts.

### Control Plane

Responsibilities:

- accept directives, commands, and future actions
- create execution plans
- schedule work
- assign work to workers
- own lifecycle state, retries, cancellation, and audit history

Core entities:

- `Command`
- `Directive`
- `ExecutionPlan`
- `ExecutionWave`
- `Job`
- `JobAttempt`
- `Event`

### Research Core

Responsibilities:

- planning
- War Room debate and synthesis
- lieutenant execution
- research and content generation

Core entities:

- `Lieutenant`
- `WarRoomSession`
- `Task`
- `TaskResult`
- `ResearchArtifact`

This is where the current implementation is strongest.

### Intelligence Store

Responsibilities:

- memory
- knowledge graph
- provenance
- retrieval context building
- consolidation and maintenance

Core entities:

- `MemoryEntry`
- `KnowledgeEntity`
- `KnowledgeRelation`
- `Evidence`
- `SourceDocument`

Future change:

- add stronger typed evidence and claim records so predictions and decisions are not stored as generic memory text

### Evaluation and Calibration

Responsibilities:

- quality gates
- forecast tracking
- outcome resolution
- scorecards
- Brier and calibration loops

Core entities:

- `Claim`
- `Prediction`
- `Outcome`
- `CalibrationRun`
- `Scorecard`

This should be a separate bounded context rather than an extension of the memory layer.

### Execution Surfaces

Responsibilities:

- future armory-style actions
- external system calls
- posting, trading, operations, tool execution
- policy and safety enforcement for high-risk actions

Core entities:

- `ActionProposal`
- `ActionPolicy`
- `ExecutionSurface`
- `ExecutionAttempt`
- `ExecutionReceipt`

This boundary matters because roadmap execution is fundamentally different from research.

### Empire Network

Responsibilities:

- multi-empire identity
- cross-empire discovery
- sync and synthesis
- shared protocols and message contracts

Core entities:

- `Empire`
- `EmpireCapability`
- `EmpireMessage`
- `SyncRun`
- `SharedArtifact`

The current knowledge bridge is only a small part of this future domain.

## Runtime Topology

### Today

Current runtime is roughly:

- Flask app
- in-process scheduler thread
- direct database writes from request and background paths
- ad hoc threads for async work

### Target

Recommended runtime:

1. API/UI process
   - HTTP routes
   - admin UI
   - command intake
   - read models

2. Control-plane process
   - job planning
   - job dispatch
   - scheduler tick ownership
   - retry and timeout management

3. Worker pool
   - executes research, debate, content, and future action jobs
   - stateless workers with explicit leases

4. Optional network/sync worker
   - cross-empire sync
   - federation work
   - background import/export tasks

### Key Rule

Requests should enqueue work, not perform the work inline unless it is trivially fast and side-effect safe.

## Persistence Model

### Primary Store

Use Postgres as the canonical operational store for shared and multi-process environments.

Use SQLite only for local development.

Postgres should become the authoritative store for:

- directives
- tasks
- jobs
- events
- War Room sessions
- memory metadata
- knowledge graph metadata
- evaluation records
- future execution receipts

### Event Log

Add an append-only event table for lifecycle visibility.

Example events:

- directive.created
- directive.planning_started
- task.started
- task.completed
- warroom.closed
- prediction.scored
- action.executed

This is the cleanest way to support:

- auditability
- replay
- analytics
- UI progress streams

### Specialized Stores

Add only when justified:

- Redis for leases, queues, ephemeral coordination, and cache
- vector index only if retrieval quality clearly demands it
- object storage for large artifacts and transcripts

Do not make Redis mandatory for core correctness yet.

## Domain Modeling Recommendations

The roadmap requires stronger typing than the current generic research model.

### Introduce Explicit Models For

- forecasts and calibration
- action proposals and execution attempts
- cross-empire messages
- evidence and provenance
- capability registry for future armories

### Avoid

- encoding business state only inside prompt strings
- storing roadmap concepts as arbitrary JSON blobs without contracts
- using memory entries as a substitute for domain entities

## Execution Architecture

### Current Weakness

`DirectiveManager` currently acts like planner, orchestrator, executor coordinator, and finalizer.

That is acceptable for a research monolith, but it becomes a bottleneck for roadmap growth.

### Recommended Split

- `DirectiveService`
  - owns directive lifecycle and user intent
- `PlanningService`
  - creates plans and waves
- `JobService`
  - creates durable executable jobs
- `WorkerRuntime`
  - executes jobs
- `ReviewService`
  - quality, retrospective, scoring

War Rooms remain a research/planning primitive, not the global orchestration primitive.

## Scheduler Architecture

### Current State

The scheduler is an in-process thread with in-memory job registration.

### Recommended State

Move to durable scheduled jobs:

- a scheduler process marks due jobs
- jobs are written to the database or queue
- workers claim jobs using leases
- retries and backoff are persisted

This gives:

- crash recovery
- multiple workers
- clean observability
- future multi-empire scheduling

## Cross-Empire Architecture

### Current State

Cross-empire support is mostly replication and sync scaffolding.

### Recommended State

Treat empires as first-class runtime actors with:

- identity
- declared capabilities
- message contracts
- provenance on imported artifacts
- explicit sync and synthesis workflows

Do not let cross-empire behavior emerge from direct graph copying alone.

## Architecture Decision Record

### Recommended Decisions

1. Keep a modular monolith for now.
2. Introduce a durable control plane before adding major roadmap features.
3. Keep research execution as one bounded context, not the whole product model.
4. Use Postgres for shared runtime correctness; keep SQLite for local development only.
5. Introduce typed entities for predictions, actions, and outcomes before building those product surfaces.
6. Treat cross-empire orchestration as a domain, not a utility layer.

### Rejected Alternatives

#### Full microservices now

Rejected because:

- too much operational overhead
- current domain boundaries are not stable enough
- would slow roadmap execution rather than help it

#### Keep extending the current directive manager indefinitely

Rejected because:

- orchestration concerns are already too concentrated
- future retries, replay, leases, and multi-surface actions will become fragile
- it will blur research, operations, and network concerns together

## Migration Path

### Phase 1: Stabilize Current Core

- keep current research architecture
- move UI/admin command execution onto durable jobs
- persist command/event history
- keep SQLite viable for local work

### Phase 2: Introduce Control Plane

- add `Job` and `Event` tables
- move scheduler to durable dispatch
- move long-running directive and War Room execution to workers
- add progress streams from persisted state instead of in-memory caches

### Phase 3: Separate Domain Models

- add prediction/calibration domain
- add action proposal/execution domain
- add provenance/evidence models
- make memory a support layer, not the only intelligence store

### Phase 4: Enable Empire Network

- add empire capability registry
- add cross-empire message contracts
- add shared artifact ingestion and synthesis workflows
- treat sync as explicit jobs with audit trails

### Phase 5: Add Roadmap Surfaces

- hero/soldier or equivalent lifecycle only after execution contracts exist
- armories only after execution surfaces and policy layers exist
- prediction/trading only after typed forecast and settlement models exist

## Immediate Engineering Priority

If the goal is roadmap alignment, the next architectural step is not adding features.

The next step is:

- durable job model
- persisted event stream
- worker runtime
- DB-backed command execution state

That is the smallest architectural shift that meaningfully improves fit for the roadmap.

For the recommended first implementation slice, see `docs/PHASE1_CONTROL_PLANE_SPEC.md`.
