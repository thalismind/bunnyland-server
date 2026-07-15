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

## Map systems to indexed components

Each independent system effect has one driving component: the component whose state the
system owns or changes. Its query must require that component so Relics can begin with the
per-component entity index. Exclusions, secondary indexes, and bounded relationship terms
may reduce that candidate set further.

Do not combine independent effects into an A-or-B system. A disjunctive component query, or
a full-world query followed by `has_component(A)` and `has_component(B)` branches, obscures
ownership and can make an idle tick scan every entity. Define one system for A and another
for B. An entity carrying both components then participates once in each system, while an
entity carrying only one participates only in the matching system.

An A-and-B system is different and remains valid when one semantic effect inherently needs
both components. Require both components in the query. Do not select A and discover B in
the processing loop, because that admits candidates the system cannot process.

Use this review checklist for every system:

1. Name the component whose state the system owns or changes.
2. Confirm the query is anchored by that component's index.
3. Split independent branches that operate on different components.
4. Keep multi-component systems only for genuinely conjunctive behavior.
5. Test entities with A only, B only, both, and neither.
6. For query-shape changes, prove cost scales with matching candidates rather than total
   world size.

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

## Reference-field audit and migration backlog

Schema v4 completed the audited live links for Storyteller incident location, Dinosim
lineage/care/ownership/behavior/provenance, Neon evidence provenance, and Void
orbit/navigation. Incident history and domain-event ids remain scalar historical provenance;
Dinosim lab names, pack keys, and hunt species are semantic keys rather than entity links.

TODO: migrate the remaining packages one bounded domain at a time, with a schema migration,
endpoint validation, cleanup rules, and projection/prompt tests for each group:

- **Colony factions:** establish canonical live faction entities first, then replace
  `FactionRelationComponent.faction_id`, trade-offer faction references, and other live
  faction participants with directed edges. Existing generated faction strings are semantic
  labels and must not be converted until identity and missing-target behavior are defined.
- **Neon follow-up:** audit active trace source devices, blackmail subjects, and handler/runner
  contracts. Preserve completed contract and evidence event ids as historical provenance.
- **Void follow-up:** audit first-contact participants, artifact/sample researchers,
  quarantine starters, insurance subjects, salvage claimants and source sites, and any species
  fields that identify live entities. Keep route labels and species taxonomy as semantic keys
  where no entity lifecycle exists.
- **Other packages:** audit Dagger banking/property participants, storyteller-adjacent package
  incident locations, Garden ladder/plot links, Dragon map/study subjects, and Nuke salvage
  claimants. Classify command payload ids and immutable event ids as boundary or historical
  data instead of converting them mechanically.

A mechanical `_id` search is useful for discovery but is not a modeling decision.
