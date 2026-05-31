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

### Sim example worlds (`<sim>-demo`)

Every sim package contributes a deterministic, hand-built example world that shows off its
mechanics — handy for trying a package, demoing it in the web inspector, or seeding a play
session. They need no `--llm` and run offline:

```bash
uv run bunnyland serve --generator voidsim-demo --ticks 5
```

| Generator            | What it sets up |
|----------------------|-----------------|
| `lifesim-demo`       | A married couple with careers, skills, money, and aspirations |
| `gardensim-demo`     | A farm with tilled soil, a half-grown crop, and seeds |
| `colonysim-demo`     | A camp with a resource node, workstation, recipe, and a job |
| `barbariansim-demo`  | A frozen ridge and sheltered cave, with gear, stamina, and corruption |
| `dragonsim-demo`     | A village, an undiscovered barrow, a faction, and a quest |
| `daggersim-demo`     | A town with a bank, guild, rumor, travel route, and a frontier site to expand |
| `voidsim-demo`       | A ship of habitat modules with life support, power, a damaged reactor, and a distress beacon |
| `apartment-demo`     | A five-storey NYC apartment building of quirky tenants with backstories, homes, and daily routines, a rat-man in the warren below, and hidden corners to find |

Each demo builds on the shared life-sim basics (every character has needs), then layers on
its own package's components. Each is contributed by its sim's plugin, so it only appears
when that plugin is enabled (the default set enables all of them). The per-package demos live
in `src/bunnyland/worldgen/examples.py` and double as worked examples for the section below;
the larger `apartment-demo` (also contributed by the life-sim plugin) lives in
`src/bunnyland/worldgen/apartment.py`.

An unknown `--generator` name lists what the enabled plugins actually provide:

```
unknown generator 'maze'; available: apartment-demo, barbariansim-demo, colonysim-demo,
daggersim-demo, dragonsim-demo, gardensim-demo, lifesim-demo, oneshot, recursive, voidsim-demo
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
