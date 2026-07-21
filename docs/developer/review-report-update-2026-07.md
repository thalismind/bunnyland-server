# Bunnyland Executive Review — Consolidated Implementation Update

**Date:** July 20, 2026

**Evidence cutoff:** July 16 hosted validation plus the v1.0 release-candidate hardening
work described in the compatibility and technical-results records.

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
| Journal and memory checkpoint coordination | **Implemented and drilled.** The bounded journal, memory manifest, watermarks, quarantine behavior, encrypted backup, clean-host restore, rollback, and revoked-token persistence have passed. The 72-hour release-candidate soak remains a release gate. |
| Versioned character streaming and claim revalidation | **Implemented.** |
| At-least-once WebSocket delivery | **Not implemented by design.** Delivery is ordered and best-effort with event-ID deduplication, gap detection, overflow `resync`, and fresh-projection recovery. |
| Bounded graph query engine | **Implemented.** |
| Shared typed perspective-query catalogue | **Implemented for v1.** The four core queries and plugin-owned social queries enforce typed outputs, visibility, result limits, and budgets; expand only from demonstrated needs. |
| Server-owned known maps | **Implemented.** |
| Private contextual memory and reflection | **Implemented.** |
| Goals, obligations, and routines | **Implemented.** Unified causal scoring and long-horizon behavioral evidence remain evaluation work. |
| Controller evaluation benchmark | **Implemented for scripted, behavior-tree, goal-directed, and LLM contracts.** RL remains future work. |
| Three Clover City systemic outcomes | **Implemented.** Missing parcel, water shortage, and elevator disruption all run through ordinary validated actions with persistent outcome probes and reload evidence. |
| Real 40-WebSocket validation and soak | **Hosted stream gate passed; soak pending.** The exact deployed image passed 40 distinct authenticated streams, reconnect resynchronization, invalidation, and mid-stream revocation. The 72-hour release-candidate soak remains. |
| Security/trace hardening and measured release gates | **Automated and operational gates implemented.** Claim/memory isolation, instruction-like memories, provider failures, request/rate limits, revocation, redaction, restore, and rollback have evidence. Ten fresh-player sessions and the 72-hour soak remain manual release gates. |

## Updated implementation TODO

Completed review items are removed from the active queue: handler and non-handler transaction migration, trace redaction, room-projection authorization, honest history/gap semantics, perspective-query typing/policy enforcement, audited semantic-edge migration, and the fixed-snapshot receipt benchmark.

The remaining work is ordered by v1 release risk:

1. [ ] Run ten fresh-player Apple Crossing sessions; require at least eight independent
   completions under ten minutes and retest every blocker seen by two players.
2. [ ] Run the immutable v1.0 release candidate for 72 hours with scheduled restart,
   checkpoint, encrypted backup, clean-host restore, rollback, and revoked-token checks.
3. [ ] Publish `relics-ecs==0.1.0`, replace the temporary Git dependency, and rerun the
   clean wheel/sdist, dependency-audit, migration, SBOM, and provenance gates.
4. [ ] Validate the browser adapter's deterministic Apple Crossing golden path and the
   apple-consumed, letter-taken, ignored-quest, reconnect, and save/reload branches in its
   client-owned contract run.
5. [ ] Expand experience and controller scorecards only from observed onboarding or hosted
   deployment failures; defer new sim-pack breadth and speculative infrastructure.

## Validation state

The historical `ec487c0` aggregate reported 3,186 tests and 100% line and branch coverage.
The current release candidate must satisfy the repository's warning-as-error aggregate,
Python 3.12–3.14 CI, package-install, compatibility, migration, security, and performance
gates before that historical result can be treated as current. Bunnyland now has three
demonstrated persistent systemic stories; v1 readiness depends on the Relics publication,
72-hour operational soak, and measured fresh-player gate above.
