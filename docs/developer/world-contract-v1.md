# The World Is the Database — World Contract v1

This document is normative for the controlled Bunnyland preview. Relics ECS state is the
authoritative world database. JSON and compact YAML checkpoints are canonical durable
representations. Memory embeddings, WebSocket queues, command queues, projections, and
the operational journal are derived or operational state; none may override the ECS.

## Tick and transaction order

One `WorldActor` owns one Relics world and one async lock. A tick runs, in order:

1. drain deferred event reactions from the preceding transaction;
2. ingest accepted commands into character lanes;
3. advance the monotonic world clock, regenerate meters, and run passive systems;
4. reconcile direct room perception into durable `KnowsRoom` edges;
5. execute commands by descending initiative, focus before world lane, then ascending
   submission epoch and actor-assigned submission sequence;
6. run consequences as separately ordered transactions;
7. run registered after-tick work, including persistence and integrations;
8. close the event-bus transaction.

Commands may carry `expected_epoch`. If it differs when execution begins, the command is
rejected without spending points. `command_id` is the idempotency key. A bounded cache
returns the original terminal `CommitReceipt` for a known retry and never executes it
again. Pending duplicates are accepted as the same pending operation but are not queued
twice.

Fresh unrecorded randomness is forbidden for authoritative ordering. Random work uses a
named stream; checkpoint metadata currently records `command_order` state. New streams
must be named and added to checkpoint and journal records before use.

## Mutation and causality

New authoritative handlers return a `MutationPlan` containing typed entity, component,
and edge operations. The executor preflights every operation, applies them under the actor
lock, asserts central and plan-specific invariants, and rolls applied operations back in
reverse order on failure. Action and focus costs belong to the same command transaction.
Events are published only after commit and their IDs are recorded in `CommitReceipt`.
Entity deletion is a terminal operation: the executor validates all other work, constructs
post-apply events, resolves every deletion target, rejects duplicate or world-clock
deletions, and only then calls Relics removal. No fallible plan work runs after that commit
barrier. Plans containing deletion cannot add custom invariants because those invariants
cannot be evaluated against a deleted entity without making the deletion irreversible.

All 440 bundled action handlers use this plan contract. A successful handler result without
a plan is rejected without spending points. `HandlerContext` is read-only and standalone
callers must execute returned plans explicitly; handlers cannot use it to apply mutations as
a compatibility side effect. Admin patch and scripting surfaces compile to mutation plans
and may not invent a second mutation authority.

Passive systems and event reactions are not part of an initiating command's atomic
transaction. Their tick phase and causation/correlation identifiers establish their
boundary. When a passive system reuses handler validation, it explicitly executes the
returned plan as its own ordered transaction. A failure in a later reaction does not
retroactively uncommit its cause.

Core invariants are: exactly one world clock; monotonic time; at most one physical
`Contains` parent; legal, acyclic containment; existing edge endpoints; at most one active
`ControlledBy` relationship; bounded AP/FP and mechanic meters; and projections that
contain only facts allowed for their viewer. Violations fail closed.

## Persistence and recovery

`save_world` writes a sibling temporary file, flushes and `fsync`s it, computes SHA-256,
rotates three backups, atomically renames the checkpoint and checksum, then `fsync`s the
directory. Restore verifies a present checksum before parsing. Schema-v2 checkpoints made
before checksum sidecars remain readable. Restore drills must also exercise `.bak.1`.

The bounded `<save>.journal.jsonl` records checkpoint markers, command receipts, mutation
summaries, event ranges, RNG state, and epochs. It supports audit and recovery diagnosis;
it is not event sourcing and cannot replace a snapshot.

World metadata contains a versioned memory manifest: world namespace, backend, checkpoint
epoch, collection namespace, embedding implementation, and high watermark. Source
documents and metadata are authoritative. Embeddings are rebuildable indexes. Restoring
an older checkpoint requires quarantining documents above its checkpoint epoch. Cloning
creates a new `world_id` and namespace and explicitly copies source documents; it never
reuses another world's live collection implicitly.

## Perspective and cognitive integrity

Callers do not receive unrestricted Relics access. The plugin-owned perspective catalogue
defines typed input, owner, visibility, result limit, execution budget, required indexes,
and provenance. Preview v1 contains only:

- `available_actions(actor)`
- `valid_targets(actor, action)`
- `why_not(actor, action, target?)`
- `what_changed_since(actor, epoch)`

REST exposes one claim-required character query route and MCP exposes `query_world` using
the same registry. Autonomous controllers must use this surface when asking the same
questions. Current room perception updates server-owned `KnowsRoom` edges with first/last
seen epochs and remembered labels. Clients may cache this projection but cannot assert it.

Ordinary subjective experience remains in `MemoryStore`. Only mechanically actionable
knowledge—maps, obligations/promises, rumors, evidence, recipes, and shared intelligence—
belongs in typed ECS state. Retrieved memory text is quoted untrusted world data, never
instructions. Direct perception wins; disagreement is retained as a discrepancy rather
than silently rewriting history.

## Streaming contract

External frames carry `world_id`, `protocol_version`, `projection_version`, `world_epoch`,
connection-local `stream_sequence`, optional `event_id`, and optional
`causal_command_id`. Delivery is at least once. Clients deduplicate event IDs, detect gaps
in stream sequence, and request a fresh character projection after `resync`. They must not
infer exactly-once delivery. Claim validity is checked before every character frame and
subscriber queues stay bounded.

## Preview scope

The preview is limited to 20 invited players and must validate 40 concurrent clients.
Clover City fixes and integrations may land. Unrelated new sim packs are soft-frozen and
cannot delay gates. PostgreSQL, Redis, full event sourcing, a universal epistemic graph,
generic multi-step planning/theory of mind, regional sharding, broad SDK work, and new
standalone packs are deferred.
