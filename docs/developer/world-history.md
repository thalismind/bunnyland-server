# World history

World history is durable ECS state for notable shared events. Physical marks, creator
signatures, and deed reputation are durable ECS state for authored changes, made objects,
and later reactions to known deeds. None of these are private memory or narration.
Narration and prompts may present these records, but the source of truth is ECS state.

Use world history when an event should remain discoverable by characters or mechanics
after the original actor leaves, forgets, or the world is saved and reloaded.

## Model

Each record is its own entity:

```text
WorldHistoryRecordComponent(summary, source_event_id, event_type, created_at_epoch,
                            location_id, tags, salience)
HistoryActor -> character or institution involved
HistoryTarget -> item, character, place, or artifact affected
```

`source_event_id` is the dedupe key. Replaying the same domain event must not create
another history entry.

Each physical mark is also its own entity:

```text
PhysicalMarkComponent(text, mark_type, author_id, source_event_id, created_at_epoch)
MarkOn -> marked object
```

Use mark entities when one object can accumulate several carvings, written lines, scars,
or other visible authored changes. Do not add repeated components to the marked object.

Crafted or authored artifacts carry creator metadata:

```text
CreatorSignatureComponent(creator_id, source_event_id, created_at_epoch, circumstance)
CreatedBy -> creator
```

Use a signature component for the artifact's current provenance summary and a `CreatedBy`
edge for mechanics that need to traverse from artifact to maker. Replaying the same source
event should not create another signature.

Actors involved in history records accumulate deed reputation:

```text
DeedReputationComponent(scores, deed_ids, known_for)
```

Scores are keyed by history tags, such as `crafted`, `writing`, or `death`. Mechanics can
gate services or behavior on those explicit scores rather than inferring reputation from
prompt text.

## Prompt use

`history_fragments(world, character)` returns concise, deterministic prompt lines for
records relevant to the character's current room, visible targets, or the character
themselves. `mark_fragments(world, character)` returns visible marks on reachable
entities. `creator_fragments(world, character)` returns visible artifact makers and
circumstances. `deed_reputation_fragments(world, character)` returns the character's
explicit deed scores and recent known deeds. All include ids or source event data for
audit where relevant.

## Current sources

The built-in `bunnyland.history` plugin records:

- physical writing on writable objects
- crafted outputs
- character deaths

Physical writing creates a mark entity and signs that mark. Crafting signs each crafted
output. History records project deed reputation onto their actors; dagger-sim institution
services can optionally require a deed tag and score.

Add new sources by extending the history reactor from typed domain events. Do not create
records from generated prose unless that prose has already been validated into world state.
