# Executive Review Update — July 2026

This addendum updates the world-as-a-database review after the implementation work from `804df40` through `ec487c0`. The architectural diagnosis has moved again: Bunnyland now has an executable World Contract, a plan-based mutation boundary across command handlers and non-handler phases, perspective-safe queries, hardened projections and traces, and the first reproducible Clover City systemic story. These are implemented and tested contracts, not proposed infrastructure.

## What is now implemented

**World Contract and atomic mutation plans.** `804df40` introduced `MutationPlan`, typed mutations, invariant checks, commit receipts, command sequencing and idempotency, checkpoint metadata, stream envelopes, and the initial perspective-query catalogue. The subsequent handler migration (`87a9e74` through `cae21d3`, consolidated by `d3ac273`) moved Colonysim, Gardensim, Barbariansim, Nukesim, Dragonsim, Neonsim, Voidsim, Daggersim, Dinosim, memory, core, foundation, Lifesim, and bundled-plugin handlers onto pure plans. Handlers now validate and describe mutations without editing the live Relics world. AP/FP costs, invariant validation, rollback, receipts, and post-commit event publication share the transaction boundary.

**Non-handler transactions and graph modeling.** `0e792bf` closed the major transaction boundary outside command handlers: passive systems and event reactions execute as separately ordered atomic plans rather than implicit extensions of a command. `1322384` added graph-query and semantic relationship foundations, while `ed1a21e` migrated audited persisted world references to ECS edges and added compatibility migrations. This preserves Relics as the authoritative operational graph and snapshots as the canonical durable representation; no PostgreSQL, Redis, or full event-sourcing dependency was introduced.

**Perspective queries, projections, and streaming.** The v1 query surface provides bounded, claim-scoped `available_actions`, `valid_targets`, `why_not`, and `what_changed_since` behavior shared by REST/MCP and controller-facing code. `3c6079f` added declared output types and enforced ownership, visibility, result-limit, and execution-budget policies. `7f80c39` closed room-projection authorization so live projections require a valid controlling claim. `e928c32` corrected the contract language: stream delivery is at least once, event IDs support deduplication, sequence gaps require explicit resynchronization, and `what_changed_since` reports only retained, perspective-safe history rather than implying an unavailable complete replay.

**Trace privacy and controller evidence.** `8a7a098` recursively redacts private values and secret-bearing fields from telemetry instead of relying on shallow name filtering. `cf5fb0a` added a fixed-snapshot benchmark that records attempted, valid, rejected, and committed decisions together with command receipts, event IDs, and actual results; `2a3ebb0` and `810fe19` completed failure-path and aggregate-transaction regression coverage.

**Clover City vertical slice.** `67333d6` completed the missing-parcel story using ordinary validated actions. Pip can investigate the parcel, return it to the incident location, fulfill the durable obligation, change the relevant relationship, and write a persistent incident-log resolution. The outcome survives snapshot save/reload and is not produced by a scripted shortcut. `ec487c0` runs that same twelve-action story from one checksummed snapshot across scripted, behavior-tree, goal-directed, and LLM controller contracts. Authoritative probes verify parcel return, report creation, obligation completion, incident resolution, and relationship change; every family must also produce complete receipt/result traces. The benchmark exposed and corrected an important cognitive boundary: room-local incident perception alone cannot sustain a multi-room task, so the fixture uses an explicit persistent goal rather than omniscient incident access.

## Revised assessment

The report should no longer list mutation atomicity, universal handler-plan migration, non-handler transaction boundaries, the four v1 perspective queries, output-policy enforcement, room-projection authorization, honest gap semantics, trace redaction, or a fixed-snapshot receipt benchmark as missing foundations. Likewise, semantic ECS edges are now the persisted representation for the audited repeatable relationships, with compatibility migration rather than pack disablement.

The remaining risk is integration and operational proof, not absence of a backend contract. The next release work should concentrate on:

1. Completing the shortage/conflict and disruption/repair Clover City stories with the same save/reload and cross-controller evidence as the parcel story.
2. Expanding fixed-snapshot evaluation metrics and adding the future RL controller without weakening the shared perception/action contract.
3. Running the 40-client reconnect, overflow, claim-revocation, and gap-recovery load gate plus the multi-day restart/restore soak.
4. Completing coordinated world/memory restore drills, adversarial memory-isolation and instruction-like-memory tests, and remaining security/moderation runbooks.
5. Measuring the Apple Crossing completion and comprehension gates with new players.

## Validation state

At `ec487c0`, the all-extras server regression suite reports **3,186 tests, zero failures or errors, 28 non-release-critical skips, and 100% line and branch coverage**. Full Ruff validation and repository diff checks pass. This supports a narrower updated verdict: Bunnyland has a credible authoritative database contract and one demonstrated persistent systemic story; controlled-preview readiness now depends on completing the remaining stories and proving the operational and player-experience gates under sustained load.
