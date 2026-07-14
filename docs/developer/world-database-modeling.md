# World-as-a-Database Modeling

This guide is normative for authoritative Bunnyland state. Relics is the world database;
the graph-query layer compiles bounded joins to Relics indexes and relationship traversal. It
is not a second store.

## Choose the shape of a fact

A component is a unary, singleton fact about one entity. Use one when the fact has one
current value per entity, such as health, pregnancy timing, a career, or a room description.
Replacing a component replaces that fact.

An edge is a fact involving two live entities. Use an edge when the target is part of the
meaning, the relationship can repeat for one source, or per-target properties matter. Edge
direction should read consistently as a sentence: `character OwnsHome room`, `pregnant
character PregnancyCoParent character`, and `room Contains item`.

A linked entity is appropriate when the fact has its own identity, lifecycle, history, or
several participants. Obligations are entities with an `ObligationComponent` and debtor and
creditor edges; they are not a list embedded on either character.

Keep these other categories distinct:

- **Derived data:** projections, caches, embeddings, indexes, and prompt text are rebuildable
  views, not alternate authority.
- **Historical data:** immutable event ids and snapshots may remain scalar provenance. A past
  event need not stay a live entity forever.
- **Subjective memory:** private recollection belongs in `MemoryStore` unless mechanics must
  query it as typed world state.
- **Semantic keys:** generator keys, faction labels, recipe names, and plugin ids identify
  concepts, not necessarily live entities. Do not convert them merely because they end in
  `_id`.
- **External ids:** Discord users, transport messages, provider jobs, and similar identifiers
  belong at the integration boundary and must not be treated as Relics entity ids.

## Edge contract checklist

Every new edge must document and test:

1. Direction and endpoint types.
2. Source and target cardinality. “Many homes per character, at most one owner per room” is
   different from one-to-one ownership.
3. Edge properties and which operation replaces them.
4. Creation, transfer, and cleanup rules, including entity deletion and lifecycle completion.
5. Projection and prompt visibility. Authority does not imply that every viewer can see it.
6. Migration behavior for any component field it replaces, including missing-target failure.
7. Representative bounded queries that mechanics or trusted scripts need.

For each proposed field, ask: is this a single value intrinsic to the owning entity? If yes,
use a component field. Does it name a live entity, repeat, or carry per-target state? Use an
edge. Does the record need identity or a lifecycle of its own? Create a linked entity. If the
value is historical, semantic, or external, classify it explicitly before changing it.

## Bounded graph queries

`GraphQuerySpec` is a connected conjunction of at most eight terms and six variables.
Component terms bind an entity with a plugin-registered component and optional exact field
matches. Directed edge terms join source and target variables through a plugin-registered
edge. Fixed bindings anchor variables to live entity ids, and `select` declares the returned
bindings.

Execution uses stable entity-id ordering, removes duplicate rows, and stops at 100 rows or
10,000 candidate expansions. Unknown types, missing bindings, undefined selections,
disconnected Cartesian products, and exhausted budgets fail closed. OR, negation, optional
terms, inheritance, transitivity, recursion, numeric comparisons, and arbitrary predicates
are intentionally outside this contract.

Trusted scripts may use a graph target selector and receive every selected variable as a
`$binding`. Agents cannot submit graph specifications. Their only relational questions are
typed, claim-scoped plugin registrations such as `social_connections` and
`open_obligations`, exposed through the shared REST/MCP `query_world` registry.

## Reference-field audit

These are review candidates, not automatic migrations:

| Area | Current examples | Classification / next question |
|---|---|---|
| Storyteller | incident `room_id`, incident history ids, spawned-requirement incident ids | Live room and requirement links are edge candidates; bounded history ids and event payload ids are historical provenance. |
| Neon | evidence event `evidence_id` and evidence subject/device provenance | Event ids are historical; live subject/device provenance should be audited for explicit evidence edges. |
| Void | orbit `body_id` and navigation destinations | Live ship/body or traveler/destination state is relational and should be piloted as edges when that package is migrated. |
| Colony | `FactionRelationComponent.faction_id`, trade-offer faction ids, incident ids | Some faction values are semantic labels generated without faction entities; convert only worlds that establish live faction identity. Incident command/event ids are references at the action boundary. |
| Dinosim | taming `tamer_id`, companion `owner_id`, behavior/incident links | Live tamers and owners are strong edge candidates; incident event ids are historical, while behavior names may be semantic strategy keys. |

The audit should proceed package by package with migrations and endpoint validation. A
mechanical `_id` search is useful for discovery but is not a modeling decision.
