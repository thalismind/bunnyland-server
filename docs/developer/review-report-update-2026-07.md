# Bunnyland Executive Review — Consolidated Implementation Update

**Date:** July 14, 2026

**Evidence cutoff:** `79bd2b1`, including implementation through `ec487c0`

This addendum reconciles the consolidated executive review with the server implementation from `804df40` through `ec487c0`. The architectural diagnosis has moved again: Bunnyland now has an executable World Contract, a plan-based mutation boundary across command handlers and non-handler phases, perspective-safe queries, hardened projections and traces, and the first reproducible Clover City systemic story. These are implemented and tested contracts, not proposed infrastructure.

## What is now implemented

**World Contract and atomic mutation plans.** `804df40` introduced `MutationPlan`, typed mutations, invariant checks, commit receipts, command sequencing and idempotency, checkpoint metadata, stream envelopes, and the initial perspective-query catalogue. The subsequent handler migration (`87a9e74` through `cae21d3`, consolidated by `d3ac273`) moved Colonysim, Gardensim, Barbariansim, Nukesim, Dragonsim, Neonsim, Voidsim, Daggersim, Dinosim, memory, core, foundation, Lifesim, and bundled-plugin handlers onto pure plans. Handlers now validate and describe mutations without editing the live Relics world. AP/FP costs, invariant validation, rollback, receipts, and post-commit event publication share the transaction boundary.

**Non-handler execution and graph modeling.** Passive systems and event reactions execute as ordered, fail-stop actor phases rather than implicit extensions of a command. Code that needs atomic multi-operation behavior explicitly executes a typed mutation plan; the runtime never snapshots the live world around a phase or event delivery. `1322384` added graph-query and semantic relationship foundations, while `ed1a21e` migrated audited persisted world references to ECS edges and added persistence migrations. This preserves Relics as the authoritative operational graph and snapshots as the canonical durable representation; no PostgreSQL, Redis, or full event-sourcing dependency was introduced.

**Perspective queries, projections, and streaming.** The v1 query surface provides bounded, claim-scoped `available_actions`, `valid_targets`, `why_not`, and `what_changed_since` behavior shared by REST/MCP and controller-facing code. `3c6079f` added declared output types and enforced ownership, visibility, result-limit, and execution-budget policies. `7f80c39` closed room-projection authorization so live projections require a valid controlling claim. `e928c32` corrected the contract language: live delivery is ordered and best-effort—not at-least-once or exactly-once—event IDs support deduplication, sequence gaps require a fresh projection, and `what_changed_since` reports when retained perspective-safe history is incomplete rather than implying an unavailable replay.

**Trace privacy and controller evidence.** `8a7a098` recursively redacts private values and secret-bearing fields from telemetry instead of relying on shallow name filtering. `cf5fb0a` added a fixed-snapshot benchmark that records attempted, valid, rejected, and committed decisions together with command receipts, event IDs, and actual results; `2a3ebb0` and `810fe19` completed failure-path and aggregate-transaction regression coverage.

**Clover City vertical slice.** `67333d6` completed the missing-parcel story using ordinary validated actions. Pip can investigate the parcel, return it to the incident location, fulfill the durable obligation, change the relevant relationship, and write a persistent incident-log resolution. The outcome survives snapshot save/reload and is not produced by a scripted shortcut. `ec487c0` runs that same twelve-action story from one checksummed snapshot across scripted, behavior-tree, goal-directed, and LLM controller contracts. Authoritative probes verify parcel return, report creation, obligation completion, incident resolution, and relationship change; every family must also produce complete receipt/result traces. The benchmark exposed and corrected an important cognitive boundary: room-local incident perception alone cannot sustain a multi-room task, so the fixture uses an explicit persistent goal rather than omniscient incident access.

## Revised assessment

The report should no longer list mutation atomicity, universal handler-plan migration, non-handler transaction boundaries, the four v1 perspective queries, output-policy enforcement, room-projection authorization, honest gap semantics, trace redaction, or a fixed-snapshot receipt benchmark as missing foundations. Likewise, semantic ECS edges are now the persisted representation for the audited repeatable relationships, with compatibility migration rather than pack disablement.

The release recommendation remains an invite-only controlled sandbox preview. The remaining risk is integrated and operational proof, not absence of a backend contract. Broad public write access should wait for the active gates below.

## Report-to-code status

| Area | Current status |
| --- | --- |
| “The World Is the Database” architecture document | **Implemented.** `world-contract-v1.md` and `world-database-modeling.md` are normative. |
| Command ordering, expected epoch, runtime idempotency | **Implemented.** |
| Typed command mutation plans and rollback | **Implemented.** Ordinary command handlers propose pure plans; the executor preflights, applies, checks, and reverses on failure. |
| All 440 bundled handlers migrated | **Implemented.** Enforced by contract tests. |
| Admin patches and scripting plans | **Implemented.** They compile through the shared mutation authority. |
| Passive/reaction/control execution semantics | **Implemented.** Passive and reaction phases are ordered and fail stop. Atomic work explicitly uses a mutation plan; no implicit transaction or live-world snapshot exists. |
| Central invariants | **Substantially implemented.** Ordinary plans validate their affected relationship neighborhood; full-world validation remains an explicit load, persistence, test, or diagnostic gate. |
| Crash-safe canonical snapshots | **Implemented.** Temporary write, flush/`fsync`, checksum, atomic rename, three-backup rotation, checksum verification, and compatible JSON/YAML restoration are present. |
| Journal and memory checkpoint coordination | **Partial.** The bounded journal, memory manifest, watermarks, and quarantine primitive exist; automatic backend checkpoint/quarantine and clean-host world/memory/media drills remain. |
| Versioned character streaming and claim revalidation | **Implemented.** |
| At-least-once WebSocket delivery | **Not implemented by design.** Delivery is ordered and best-effort with event-ID deduplication, gap detection, overflow `resync`, and fresh-projection recovery. |
| Bounded graph query engine | **Implemented.** |
| Shared typed perspective-query catalogue | **Implemented for v1.** The four core queries and plugin-owned social queries enforce typed outputs, visibility, result limits, and budgets; expand only from demonstrated needs. |
| Server-owned known maps | **Implemented.** |
| Private contextual memory and reflection | **Implemented.** |
| Goals, obligations, and routines | **Implemented.** Unified causal scoring and long-horizon behavioral evidence remain evaluation work. |
| Controller evaluation benchmark | **Implemented for scripted, behavior-tree, goal-directed, and LLM contracts.** RL remains future work. |
| Three Clover City systemic outcomes | **One of three demonstrated.** Missing parcel is persistent and cross-controller; shortage/conflict and disruption/repair remain. |
| Real 40-WebSocket validation and soak | **Partial.** An automated 40-subscriber fan-out/overflow/reconnect harness exists; hosted authenticated load, reconnect storm, and multi-day soak remain. |
| Security/trace hardening and measured release gates | **Partial.** Trace redaction and room authorization are implemented; adversarial memory/guard tests, governance artifacts, live drills, and fresh-player measurements remain. |

## Updated implementation TODO

Completed review items are removed from the active queue: handler and non-handler transaction migration, trace redaction, room-projection authorization, honest history/gap semantics, perspective-query typing/policy enforcement, audited semantic-edge migration, and the fixed-snapshot receipt benchmark.

The remaining work is ordered by controlled-preview risk:

1. [ ] Complete the shortage/conflict Clover City story with ordinary actions, a recoverable failure, cross-controller outcome probes, visible aftermath, and mid-story save/reload.
2. [ ] Complete the disruption/repair Clover City story to the same standard.
3. [ ] Instrument Apple Crossing lightly and run ten fresh-player comprehension sessions; fix recurring action, target, rejection, and persistence confusion.
4. [ ] Run the real authenticated 40-client stream/reconnect/gap-recovery gate and multi-day restart/restore soak.
5. [ ] Automate coordinated world/memory/media checkpoint and restore behavior, including future-memory quarantine, namespace/clone checks, and clean-host restoration.
6. [ ] Red-team cross-character memory isolation, instruction-like memories, claim boundaries, provider/guard failure, rate limits, and secret handling.
7. [ ] Publish proportionate sandbox rules, privacy notice, security contact, model-safety failure behavior, operator runbooks, compatibility statement, and preview release notes.
8. [ ] Expand the controller scorecard with rejection recovery, commitment completion, persona consistency, memory relevance, repetition/deadlock, latency/cost, and trace completeness; add RL later through the same contracts.
9. [ ] Improve player-visible causality—away summaries, relationship/obligation explanations, incident aftermath, and appropriately scoped “why” views—using observed story and onboarding gaps.
10. [ ] Continue bounded semantic-edge and query-catalogue work only where a shipped mechanic, controller, or client demonstrates a need; defer new sim-pack breadth and speculative infrastructure.

## Validation state

At `ec487c0`, the all-extras server regression suite reports **3,186 tests, zero failures or errors, 28 non-release-critical skips, and 100% line and branch coverage**. Full Ruff validation and repository diff checks pass. This supports a narrower updated verdict: Bunnyland has a credible authoritative database contract and one demonstrated persistent systemic story; controlled-preview readiness now depends on completing the remaining stories and proving the operational and player-experience gates under sustained load.
