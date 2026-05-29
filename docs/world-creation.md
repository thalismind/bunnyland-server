# World creation

A world is a graph of **rooms** connected by **exits**, populated with **items** and
**characters**. bunnyland generates one from a seed at server start.

## How generation stays inside the rules

The model never touches the world directly. It only *proposes* structured content
(validated Pydantic models); the engine validates the proposal and performs every spawn and
edge itself. A bad or malicious proposal can't corrupt the world — at worst it fails
validation. This is the same boundary that keeps a playing LLM honest, applied to the
"dungeon master".

Offline (no `--llm`) a deterministic stub stands in for the model, so generation works
without a network or API key.

## Choosing a generator

World generators are **named strategies contributed by plugins**, selected with
`--generator`:

```bash
uv run bunnyland serve --generator recursive --max-rooms 8
```

Two are built in (from the `bunnyland.worldgen` plugin):

### `oneshot` (default)

The model proposes the entire world in a single response — all rooms, exits, objects, and
characters at once — which is then instantiated in one pass. Fast and simple; best for small
worlds.

### `recursive`

The world is grown breadth-first, one piece at a time, using the room graph as the frontier:

1. generate the root room, then its doors;
2. expand each door into a new room and generate *its* doors, until the `--max-rooms` budget
   is reached;
3. close the graph — every door still leading nowhere is **sealed** (becomes a locked door
   object), **dropped**, or **linked** back to an existing room, whichever the DM judges
   appropriate;
4. populate each room with characters and items (the DM is reminded of the rooms it already
   described);
5. recurse into containment — fill each character's inventory, then each container.

Doors are two-way by default; the DM can mark one-way passages (slides, cliffs, portals).
Because the DM is prompted per node, larger worlds stay coherent without the model having to
hold the whole map in one response. Use `--max-rooms` to bound the size.

An unknown `--generator` name lists what the enabled plugins actually provide:

```
unknown generator 'maze'; available: oneshot, recursive
```

## Seeds

`--seed` is free text. Offline it only labels the world; with `--llm` it flavours what the
DM builds:

```bash
uv run bunnyland serve --llm --generator recursive --seed "a flooded clockwork cathedral"
```

## What a generated world contains

Every generated world is playable: at least a couple of connected rooms, food, water, a
container, something writable, an LLM-controlled character, and a claimable (suspended)
character a human can take over. Characters come with needs (hunger/thirst) and a private
memory profile.

## Adding your own generator

Because generators are a plugin contribution, you can add one without touching the CLI.
Contribute a `WorldGenerator` from a plugin's `ContentContribution`:

```python
from bunnyland.plugins.model import ContentContribution, Plugin
from bunnyland.worldgen import GenOptions, InstantiatedWorld, WorldGenerator


async def generate_arena(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    ...  # spawn rooms/objects/characters on actor.world; return what you built


def bunnyland_plugins():
    return [
        Plugin(
            id="mygame.worldgen",
            name="My Generators",
            content=ContentContribution(
                world_generators=(WorldGenerator("arena", generate_arena, "a single combat room"),),
            ),
        )
    ]
```

Then load and select it:

```bash
uv run bunnyland serve --module mygame.worldgen --generator arena
```

See [admin & controllers](admin.md) for how `--module` and `--plugin` load external plugins.
The two builtins in `src/bunnyland/worldgen/generators.py` are worked examples.
