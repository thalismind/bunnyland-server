# World history

World history is durable ECS state for notable shared events. It is not private memory and
it is not narration. Narration and prompts may present history records, but the source of
truth is `WorldHistoryRecordComponent` plus `HistoryActor` and `HistoryTarget` edges.

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

## Prompt use

`history_fragments(world, character)` returns concise, deterministic prompt lines for
records relevant to the character's current room, visible targets, or the character
themselves. The lines include history id and source event id for audit.

## Current sources

The built-in `bunnyland.history` plugin records:

- physical writing on writable objects
- crafted outputs
- character deaths

Add new sources by extending the history reactor from typed domain events. Do not create
records from generated prose unless that prose has already been validated into world state.
