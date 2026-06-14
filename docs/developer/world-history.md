# World history

World history is durable ECS state for notable shared events. Physical marks are durable
ECS state for authored changes to objects. Neither is private memory or narration.
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

## Prompt use

`history_fragments(world, character)` returns concise, deterministic prompt lines for
records relevant to the character's current room, visible targets, or the character
themselves. `mark_fragments(world, character)` returns visible marks on reachable
entities. Both include ids and source event ids for audit.

## Current sources

The built-in `bunnyland.history` plugin records:

- physical writing on writable objects
- crafted outputs
- character deaths

Add new sources by extending the history reactor from typed domain events. Do not create
records from generated prose unless that prose has already been validated into world state.
