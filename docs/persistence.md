# Saving & reloading worlds

A world can be saved to disk and reloaded later. A save is a **single JSON file** that holds
both the Relics ECS snapshot (every entity, component, and edge) and the bunnyland
provenance that produced it — the **seed**, the literal **DM system prompt** the model was
given (empty for the deterministic offline builder), and which **generator** built it.
Reloading restores the world exactly: room graph, inventories, needs meters, moods,
controllers, and the game clock.

> The volatile command queues are intentionally **not** saved — a reloaded world resumes
> with empty queues and keeps playing from the saved game time.

## Saving from the server

```bash
# Save on exit:
uv run bunnyland serve --ticks 50 --save worlds/marsh.json

# Autosave every 20 ticks, and also on exit:
uv run bunnyland serve --ticks 0 --save worlds/marsh.json --autosave-every 20
```

`--autosave-every N` checkpoints the world every N ticks so an interrupted server loses at
most N ticks of play. It requires `--save` to know where to write.

## Reloading

```bash
uv run bunnyland serve --load worlds/marsh.json --ticks 50
```

`--load` skips generation and resumes the saved world (you'll see its seed, generator, and
game epoch echoed back). Combine with `--save` to keep checkpointing the reloaded world, and
with `--llm` to keep driving its characters:

```bash
uv run bunnyland serve --load worlds/marsh.json --llm --save worlds/marsh.json \
  --autosave-every 20 --ticks 0
```

## Reset / fresh start

There's no separate "reset" command — a reset is simply launching **without** `--load`,
which generates a fresh world. To discard a save, delete the file (or point `--save` at a new
path to keep the old one).

## What is and isn't persisted

| Persisted                                              | Not persisted                              |
|--------------------------------------------------------|--------------------------------------------|
| All entities, components, edges (rooms, items, characters, controllers) | Volatile command queues / inbox |
| The game clock (epoch) and per-character needs/moods   | Private notes in the memory store*         |
| Seed, generation prompt, and generator name            | Plugin code (re-applied from `--plugin`/`--module` on load) |

\* Vector/notes memory lives in a separate store; persisting it is tracked separately (see
`PLAN.md`). Plugins are *code*, not data: load re-applies the same plugins, so launch a
reload with the same `--plugin`/`--module` flags you generated with.

## From Python

The same operations are available programmatically:

```python
from bunnyland.persistence import save_world, load_world, WorldMeta
from bunnyland.plugins import bunnyland_plugins

# Save (provenance travels with the ECS data):
save_world(actor, "worlds/marsh.json",
           meta=WorldMeta(seed="a quiet marsh", prompt="...", generator="recursive"))

# Reload — pass the plugins whose components/edges the world uses, so the loader can
# reconstruct their types and re-register their handlers/systems:
actor, meta = load_world("worlds/marsh.json", plugins=bunnyland_plugins())
print(meta.seed, meta.generator, meta.saved_at_epoch)
```

`load_world` returns a ready `WorldActor` (clock rebound, plugins applied) and the
`WorldMeta` provenance. For an admin force-save mid-run, call `save_world(actor, path,
meta=...)` at any point — it stamps the current game epoch and wall-clock time.

## Format notes

The file is the layout Relics' own loader understands, so loading is just `relics.load`
under the hood (which preserves entity ids, so edges survive). bunnyland flattens its nested
value objects (needs meters, affect vectors) to plain JSON on save; pydantic rebuilds them on
load. The provenance lives under a `bunnyland` key the Relics loader ignores.
