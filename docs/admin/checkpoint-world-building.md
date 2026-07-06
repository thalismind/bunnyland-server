# Checkpoint world building

The `bunnyland.checkpoints` plugin adds player-facing save and reload checkpoint objects.
It is built in but disabled by default. Use it when you want a world to have intentional
Resident-Evil-style typewriters, Silent-Hill-style red scrolls, bonfires, terminals, save
shrines, guest books, or other in-world save anchors.

## Enable the plugin

Checkpoints require both the plugin and a configured save file:

```bash
uv run bunnyland serve --generator recursive --seed "a stormbound abbey" \
  --plugin bunnyland.core_verbs \
  --plugin bunnyland.worldgen \
  --plugin bunnyland.checkpoints \
  --api-host 127.0.0.1 --api-port 8765 \
  --save worlds/abbey.json
```

If you use a starter pack, include the checkpoint plugin in addition to the pack:

```bash
uv run bunnyland serve --starter-pack peaceful \
  --plugin bunnyland.checkpoints \
  --api-host 127.0.0.1 --api-port 8765 \
  --save worlds/peaceful.json
```

The plugin is opt-in because reload is a strong player-facing world mutation. Once enabled,
any player who can reach a checkpoint can use `save-checkpoint` or `reload-checkpoint`.

## Place checkpoint objects

The plugin does not scatter checkpoints automatically. Add `SaveCheckpointComponent` to
objects you deliberately place.

A minimal checkpoint object has:

- `IdentityComponent`, so players can target it by name;
- `DescriptionComponent`, so inspection explains the object in-world;
- `SaveCheckpointComponent`, so the checkpoint verbs accept it;
- room containment, so it is reachable.

Example patch-world operation for a typewriter in the room named `Foyer`:

```json
{
  "op": "add_entity",
  "bind": "foyer_typewriter",
  "contain_in": {
    "components": ["RoomComponent"],
    "room_title": "Foyer"
  },
  "containment_mode": "room_content",
  "components": [
    {
      "type": "IdentityComponent",
      "fields": {
        "name": "iron typewriter",
        "kind": "checkpoint"
      }
    },
    {
      "type": "DescriptionComponent",
      "fields": {
        "short": "An iron typewriter waits on a narrow desk.",
        "long": "The typewriter's keys are clean despite the dust. A fresh ribbon is threaded through the carriage."
      }
    },
    {
      "type": "SaveCheckpointComponent",
      "fields": {
        "label": "typewriter"
      }
    }
  ]
}
```

The component name is only available to patching, scripting, and persistence when
`bunnyland.checkpoints` is enabled.

## Placement guidelines

Place checkpoints where reload feels intentional:

- near safe rooms, camp rooms, elevators, terminals, shrines, or faction hubs;
- before or after risky dungeon branches;
- at natural session boundaries, such as inns, ship berths, station kiosks, or campfires;
- away from one-way traps unless the checkpoint is meant to make that trap recoverable.

Use setting-specific names and descriptions. The mechanics are the same, but the object
should read as part of the world:

```text
gothic mansion: iron typewriter, wax-sealed red scroll
survival camp: sheltered bonfire, carved trail marker
space station: emergency terminal, berth console
fantasy town: shrine ledger, inn guest book
```

Avoid placing too many checkpoints in one room. Multiple reachable checkpoints all point
to the same configured save file, so extra copies rarely add gameplay value unless they
serve different fiction or visibility needs.

## Save and reload behavior

`save-checkpoint` writes the current world to the server's configured `--save` path.
`reload-checkpoint` restores that same save file after the command finishes its tick.

Reload affects the whole world:

- ECS state is replaced with the saved state;
- queued commands and pending submissions are cleared;
- the world clock is rebound from the saved world;
- plugin handlers and actor services remain installed.

This means a checkpoint is not a per-player save slot. On shared servers, coordinate with
players before enabling reload access in live play.

## Expanding existing worlds

For an existing saved world:

1. Restart or load the world with `bunnyland.checkpoints` enabled.
2. Add checkpoint entities through the admin world patch surface or a setup script.
3. Save the world once through the admin save endpoint or by using a checkpoint.
4. Keep `bunnyland.checkpoints` enabled whenever loading that save.

If a saved world contains `SaveCheckpointComponent` and the plugin is not enabled at load
time, loading fails with a missing-plugin error. That is intentional: the persistence layer
needs the plugin component type to deserialize the saved ECS state.

