# Phase 1 Control Plane Spec

This document defines the safest first implementation slice for moving Empire from the current God Panel and background-thread model toward the target architecture in `docs/TARGET_ARCHITECTURE.md`.

The Phase 1 objective is:

- add a conversational God Panel surface
- persist command lifecycle state in the database
- support cooperative cancellation for long-running research-oriented work
- avoid a large rewrite of the directive, lieutenant, or scheduler systems

This is an implementation spec, not just a design note.

## Goals

### Product Goals

- allow a user to interact with Empire conversationally
- let the system answer simple questions directly without creating directives unnecessarily
- let the system propose structured actions, then require confirmation before executing them
- let the user cancel long-running command-driven work from the God Panel

### Engineering Goals

- replace in-memory God Panel command state with durable command records
- add a minimal event stream for visibility and debugging
- establish a standard cancellation model that can be reused by later worker-based execution
- preserve the current deterministic `/god/command` classifier as the action backend

## Non-Goals

- do not build the full durable worker/job platform in this phase
- do not redesign directive execution end-to-end
- do not implement generic cancellation for every background thread in the codebase
- do not add hero/soldier, armory, prediction, or trading features
- do not replace the existing deterministic God Panel actions

## Recommended Scope

Phase 1 should introduce a minimal control-plane layer centered on persisted commands.

Use the following model:

- chat turn may produce:
  - direct answer
  - confirmation-needed action proposal
  - confirmed action execution
- confirmed action creates a persisted command
- command execution may spawn a cancellable local runtime
- command status and events are read from the database, not in-memory cache

## API Design

### 1. `POST /god/chat`

Purpose:

- accept a conversational user message
- either answer directly or return a proposed action

Request:

```json
{
  "message": "should we run a sweep right now?",
  "conversation_id": "optional",
  "context": {
    "page": "god_panel"
  }
}
```

Response shapes:

Direct answer:

```json
{
  "type": "answer",
  "conversation_id": "conv_123",
  "message": "A sweep makes sense if you want recent discoveries. It will query stored and external sources."
}
```

Confirmation-needed action:

```json
{
  "type": "action_proposal",
  "conversation_id": "conv_123",
  "message": "I can run an intelligence sweep now.",
  "proposal": {
    "action": "SWEEP",
    "command_text": "Run an intelligence sweep across all AI sources",
    "requires_confirmation": true,
    "risk": "low"
  }
}
```

### 2. `POST /god/chat/confirm`

Purpose:

- confirm a proposed action and convert it into a real command execution

Request:

```json
{
  "conversation_id": "conv_123",
  "proposal": {
    "action": "SWEEP",
    "command_text": "Run an intelligence sweep across all AI sources"
  }
}
```

Response:

```json
{
  "type": "command_started",
  "command_id": "cmd_123",
  "status": "queued",
  "message": "Intelligence sweep queued."
}
```

### 3. `POST /god/command`

Keep this endpoint.

Role in Phase 1:

- deterministic backend action router
- used by `POST /god/chat/confirm`
- may still be called directly by the existing quick-action UI

Required change:

- stop using process-local command cache as the source of truth
- create/read/update persisted command rows instead

### 4. `GET /god/commands`

Keep this endpoint.

Required change:

- return persisted command records ordered by `created_at desc`
- include cancellation-related fields

### 5. `GET /god/commands/<command_id>`

Add this endpoint.

Purpose:

- retrieve one command with full event history

### 6. `POST /god/commands/<command_id>/cancel`

Add this endpoint.

Purpose:

- request cooperative cancellation of a running command

Behavior:

- if command is `queued` or `running`, mark `cancellation_requested_at`
- signal the in-process cancellation handle if one exists
- return `202 accepted`
- command eventually transitions to `cancelled` or `completed`

## Data Model

Phase 1 should add two tables.

### `commands`

Purpose:

- persisted lifecycle state for God Panel initiated work

Suggested fields:

- `id`
- `empire_id`
- `conversation_id` nullable
- `source` (`god_panel`, `chat`, `api`)
- `command_text`
- `action`
- `status`
  - `queued`
  - `running`
  - `cancellation_requested`
  - `cancelled`
  - `completed`
  - `failed`
- `result_json`
- `error`
- `directive_id` nullable
- `war_room_id` nullable
- `cancel_requested_at` nullable
- `started_at` nullable
- `completed_at` nullable
- `created_at`
- `updated_at`

Status semantics:

- `queued`: accepted, not yet executing
- `running`: currently executing
- `cancellation_requested`: stop requested, awaiting cooperative halt
- `cancelled`: execution intentionally stopped
- `completed`: finished normally
- `failed`: terminated due to error

### `command_events`

Purpose:

- lightweight event stream for progress and debugging

Suggested fields:

- `id`
- `command_id`
- `event_type`
- `message`
- `details_json`
- `created_at`

Suggested event types:

- `command.created`
- `command.started`
- `command.progress`
- `command.cancellation_requested`
- `command.cancelled`
- `command.completed`
- `command.failed`
- `directive.created`
- `warroom.created`

## Runtime Model

Phase 1 should keep local threads, but introduce a registry for cancellation.

### In-Process Registry

Add an in-process registry in the God Panel route module or a small new module.

Suggested structure:

```python
_command_runtime_registry: dict[str, CommandRuntimeHandle]
```

Where `CommandRuntimeHandle` contains:

- `command_id`
- `thread_name`
- `cancel_event`
- `started_at`

This is not the long-term control plane. It is a bridge to it.

### Cancellation Model

Use cooperative cancellation only.

Do not attempt:

- thread killing
- signal-based interruption
- database transaction force aborts

Use:

- `threading.Event`
- explicit checkpoint checks inside long-running loops

## Cancellation Coverage

Phase 1 should support cancellation for the following command types first:

- `SWEEP`
- `DIRECTIVE` only at wave/task boundaries
- future autoresearch command paths if wired through God Panel

Phase 1 should not attempt mid-token cancellation of a single LLM request already in flight.

That means:

- cancellation becomes effective between stages or iterations
- a currently executing network call may still complete before the command halts

## Implementation Strategy By Path

### A. God Panel Command Persistence

Replace:

- in-memory `_command_cache`

With:

- `Command` row writes
- `CommandEvent` row writes

Required behaviors:

- `record_command()` inserts command row with `queued`
- `update_command()` updates DB row and optionally appends event
- `recent_commands()` reads from repository

### B. Conversational Wrapper

Use the existing Anthropic client and tool-use support, but keep the first version narrow.

The model should have only a small set of tools:

- `get_system_status`
- `list_recent_commands`
- `get_command_details`
- `propose_action`

Important:

- action tools in Phase 1 should not execute directly
- the chat model proposes, the user confirms, then `/god/chat/confirm` executes

This avoids accidental directive creation from ambiguous chat turns.

### C. Sweep Cancellation

`core/search/sweep.py` is the cleanest first cancellation target because it already runs as a staged loop over source sweepers.

Add optional cancellation support:

- `run_full_sweep(cancel_event: Event | None = None)`
- before each source sweeper call, check `cancel_event.is_set()`
- if set, stop and return partial result with cancelled status information

Also add checks before storing batches of discoveries if needed.

### D. Directive Cancellation

`core/directives/manager.py` already has status-level cancellation, but not execution-level cancellation.

Phase 1 should add only coarse checkpoints:

- before planning
- before each wave
- before each task submission
- after each task result joins

If cancellation is requested:

- stop creating new work
- let currently running subtask finish if already in progress
- mark directive as `cancelled`
- mark command as `cancelled`

Do not attempt hard interruption of already executing task bodies in this phase.

### E. War Room and Content

These are lower priority for cancellation in Phase 1.

Reason:

- War Room requests are shorter and less loop-driven
- content generation is typically one-shot

They can still be persisted as commands, but cancellation support can be deferred.

## UI Plan

### God Panel

Replace the single command box with a simple chat layout:

- message list
- composer
- quick actions
- confirmation card for proposed actions
- recent commands sidebar or panel

The existing command stream should stay visible because it is useful operational context.

### Required UX Rules

- if chat answers directly, do not create a command
- if chat proposes an action, show confirmation UI
- if confirmed, create command and stream status updates
- running commands with cancellation support show a `Cancel` control

## File-Level Change Plan

### New Files

- `db/repositories/command.py`
- `docs/PHASE1_CONTROL_PLANE_SPEC.md`

Optional:

- `web/routes/god_chat.py` if separation from `god_panel.py` is cleaner
- `core/control_plane/registry.py` for runtime handles

### Files To Modify

- `db/models.py`
  - add `Command`
  - add `CommandEvent`
- `web/routes/god_panel.py`
  - replace in-memory cache
  - add cancel endpoint
  - route command execution through persisted records
- `web/templates/god_panel.html`
  - add chat UI
  - add confirmation UI
  - add cancel buttons for cancellable running commands
- `llm/anthropic.py` or chat wrapper layer
  - wire model/tool-use loop for chat
- `core/search/sweep.py`
  - add cancellation checkpoints
- `core/directives/manager.py`
  - add coarse cancellation checkpoints
- `tests/test_god_panel_commands.py`
  - update for DB-backed command state
- `tests/`
  - add chat endpoint tests
  - add cancellation tests

## Safest First Slice

The safest first slice is:

1. persist God Panel commands in DB
2. add command events
3. keep the current `/god/command` classifier
4. add `POST /god/commands/<id>/cancel`
5. add cancellation only for `SWEEP`
6. add chat wrapper only after the command persistence layer is stable

This order is correct because:

- command persistence removes the current in-memory fragility
- sweep cancellation is loop-based and easy to checkpoint
- directive cancellation is more complex and should build on the persisted command model
- chat without durable command state creates a UX that is hard to debug and hard to trust

## Phase 1 Sequence

### Step 1

Persist command state and command events.

Deliverables:

- DB models
- repository
- `GET /god/commands` backed by DB
- `GET /god/commands/<id>`

### Step 2

Refactor `/god/command` to create command rows and update lifecycle state in DB.

Deliverables:

- no in-memory command cache dependency
- DB-backed status updates

### Step 3

Add sweep cancellation.

Deliverables:

- runtime registry
- cancel endpoint
- cooperative checkpoints in sweep
- command transitions to `cancelled`

### Step 4

Add conversational wrapper.

Deliverables:

- `POST /god/chat`
- `POST /god/chat/confirm`
- confirmation UX

### Step 5

Add directive cancellation checkpoints.

Deliverables:

- coarse cancellation across planning/waves/tasks
- proper command and directive status mapping

## Acceptance Criteria

Phase 1 is complete when:

- God Panel commands survive server refresh and process restart as records
- recent command stream is DB-backed
- a running sweep can be cancelled from the UI
- cancelled sweep ends as `cancelled`, not `failed`
- chat can answer simple operational questions without creating commands
- chat can propose actions and require explicit confirmation before execution

## Risks

### Risk: Partial Cancellation Creates Inconsistent State

Mitigation:

- cooperative checkpoints only
- explicit `cancelled` status
- append events for every transition

### Risk: Chat Layer Produces Ambiguous Actions

Mitigation:

- proposal-only tool use
- explicit confirmation step
- keep deterministic action backend

### Risk: SQLite Local Dev Behavior Differs From Future Postgres Runtime

Mitigation:

- keep Phase 1 logic DB-agnostic where possible
- local thread registry is explicitly temporary
- persisted command model is reusable under Postgres later

## Recommendation

Do not start Phase 1 with chat UI.

Start with:

- persisted command model
- command event log
- sweep cancellation

Then add the conversational wrapper on top of that stable control-plane slice.
