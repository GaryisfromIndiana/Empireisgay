# Empire Product North-Star Roadmap

Source input: `/Users/asd/Desktop/empire_deck_external.html`

This document records the external deck as the product north-star for the repo. It is a roadmap summary, not a description of current implementation. Current implemented reality lives in `README.md` and `research/empire_architecture.md`. The recommended architectural bridge from current implementation to roadmap lives in `docs/TARGET_ARCHITECTURE.md`.

## Status Legend

- `implemented`: shipped in the current repo and reflected in code paths today
- `partial`: some supporting scaffolding exists, but the full platform behavior is not implemented
- `planned`: described in the roadmap and intentionally not treated as current functionality
- `not started`: no meaningful implementation was found in the current repo

## Vision

The deck positions Empire as a compounding intelligence platform rather than a single agent. The target direction is a multi-empire system with shared memory, differentiated execution layers, persistent specialist agents, cross-domain synthesis, and tighter operating loops between research, judgment, and action.

## Current Implemented Platform

- `implemented`: a single-empire AI research and research-ops system centered on directives, War Room planning, lieutenant execution, memory, and knowledge graph updates
- `implemented`: a 4-tier memory system covering semantic, experiential, design, and episodic memory
- `implemented`: scheduler, knowledge maintenance, research, content, and quality loops for the current research workflow
- `partial`: cross-empire generation, replication, and knowledge-sync scaffolding exists, but it does not yet amount to the operational platform shown in the deck
- `partial`: spawning and research automation paths exist, but they are still part of the current research foundation rather than the broader roadmap execution model

## Planned Platform

The following deck concepts should be treated as `planned`, not `implemented`:

- `planned`: five-tier memory
- `planned`: heroes/soldiers lifecycle
- `planned`: six armories
- `planned`: prediction markets
- `planned`: DeFi swaps
- `planned`: stock trading
- `planned`: calibrated predictions and Brier loops
- `planned`: Redis hero coordination
- `planned`: 78 scheduled jobs
- `planned`: 4 fully operational empires

Additional roadmap themes from the deck:

- `planned`: multi-empire specialization across AI, marketing, quant, and crypto domains
- `planned`: stronger judgment and calibration loops tied to explicit prediction outcomes
- `planned`: broader execution surfaces that move beyond research and synthesis into gated actions
- `planned`: deeper self-improvement, prompt evolution, and system-building loops

## Gap Matrix

| Current reality | Roadmap target | Status | Notes |
| --- | --- | --- | --- |
| single-empire AI research system | multi-empire platform | `partial` | Current code has replication/generation/sync scaffolding, but not a production multi-empire platform. |
| 4-tier current memory | 5-tier roadmap memory | `partial` | Semantic, experiential, design, and episodic memory exist today; the fifth roadmap tier is not implemented. |
| lieutenants/war rooms | heroes/soldiers lifecycle | `not started` | Lieutenant and War Room execution exist, but the roadmap lifecycle model does not. |
| research/scheduler execution | armory execution | `not started` | The current repo executes research and maintenance workflows, not the six armories described in the deck. |
| current KG/memory quality loops | calibrated prediction loops | `partial` | Quality scoring and memory feedback exist; explicit calibrated predictions and Brier loops do not. |
| partial cross-empire scaffolding | operational cross-empire synthesis | `partial` | Cross-empire sync paths exist, but operational synthesis across empires is not yet delivered. |

## Near-Term Foundation Priorities

- Keep current-state docs factual and separate from aspirational roadmap language.
- Strengthen the single-empire research foundation before adding new platform abstractions.
- Reduce ambiguity in scheduler, memory, and cross-empire documentation so future implementation work starts from the real codebase.
- Treat existing replication, generator, and knowledge-bridge paths as partial scaffolding until they are hardened.
- Avoid renaming current concepts purely to match the deck until the underlying systems actually exist.
