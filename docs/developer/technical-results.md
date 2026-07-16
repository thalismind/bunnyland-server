# Technical results

**Evidence date:** July 16, 2026

This report separates reproducible controller contracts from live model integration and
hosted operational tests. A deterministic scenario can prove shared rules and persistent
outcomes; it does not measure model intelligence.

## Fixed-snapshot controller contracts

Bunnyland runs persistent Clover City scenarios from checksummed snapshots under scripted,
behavior-tree, goal-directed, and LLM-controller contracts. The probes inspect authoritative
world outcomes and command receipts, including rejected-command recovery and save/reload
consequences.

| Scenario | Outcome under test | Current state |
| --- | --- | --- |
| Missing parcel | Return, obligation, relationship, incident report, reload | Implemented |
| Water shortage | Resource pressure, failed attempt, replenishment, sharing, aftermath, reload | Server aggregate passing |
| Elevator disruption | Noise dispute, required tool, repair, routine and relationship consequences, reload | Server aggregate passing |

The [fixed-snapshot controller benchmark](controller-benchmark.md) documents the reusable
methodology and measurement contract.

## Canonical causal experiment

The immutable Clover City water-shortage experiment starts four controller families from one
checksummed snapshot. Wick can only act through the character's current perspective and
ordinary validated actions.

1. Wick's attempt to take the fixed community pantry is rejected.
2. The controller recovers, travels to the store, and carries emergency water to the rooftop.
3. Wick agrees to share the ration with Saffron, changing their relationship, and fulfills the
   persistent obligation.
4. Wick records the resolution in the incident log; every final world is saved, reloaded, and
   probed again.

Scripted, behavior-tree, goal-directed, and deterministic LLM-contract controllers each
complete 17 attempts with 16 commits, one rejection, one recovery, complete receipt traces,
and all six authoritative outcomes passing. The immutable
[experiment card and saved worlds](../../artifacts/experiments/clover-water-shortage-2026-07/),
[manifest](../../artifacts/experiments/clover-water-shortage-2026-07/manifest.json),
[traces](../../artifacts/experiments/clover-water-shortage-2026-07/traces.jsonl), and
[receipts](../../artifacts/experiments/clover-water-shortage-2026-07/receipts.jsonl) contain
the reproducible evidence. The initial snapshot SHA-256 is
`178e4e096335f46336dbf38f1111e1e36752ef900645772e3839bcfdbfe69ad1`.

## Live model integration

Optional integration suites cover Ollama and OpenRouter separately from the deterministic
controller cases. The controlled sandbox uses Ollama Cloud; economical test models are used
for live OpenRouter validation. Provider tests demonstrate that a live service can use the
controller contract, but are not folded into deterministic scores. All 21 live provider tests
passed for the July 16 release refresh.

## Hosted load and streams

Earlier HTTP testing established a known-good bracket of 15 world-read iterations per second
on the current single VPS, while 30 iterations per second exceeded latency thresholds. The
exact deployed release image passed a 40-character authenticated stream run with distinct
users, client identities, character claims, reconnect resynchronization, mutation
invalidation, and mid-stream token revocation. The post-deployment rerun completed in 30.193
seconds.

Bunnyland WebSockets are ordered and best effort. A detected sequence gap or overflow must
trigger a fresh projection; the stream does not claim at-least-once delivery.

The separate [world-scale performance baseline](world-performance.md) measures synthetic ECS
operations through one million entities and one million edges.

## Restore and release validation

Encrypted clean-host restoration and an exact-image rollback rehearsal passed, including
proof that a previously revoked token remains rejected after restoration. The complete
post-deployment authorization, REST, WebSocket, streamable-HTTP MCP, browser, provider,
40-stream, Discord, encrypted-backup, restart, and revocation-persistence gates also passed.
The retained bearer-release gates have no open blockers; longer-running soak and ongoing
performance work remain continuous validation rather than claims made by these fixed results.

The VPS repository's
[hosted validation record](https://github.com/thalismind/bunnyland-vps/blob/main/releases/bunnyland-early-preview-2026-07-validation.md)
records immutable revisions, image digests, CI runs, and detailed operational evidence.
