# bunnyland

An asynchronous social sandbox where humans and LLM agents share persistent characters in
an emergent ECS simulation. Built on the [Relics](https://github.com/ssube/relics) ECS
database.

Characters live in a world of rooms, items, and needs. They are driven by **controllers** —
an Ollama-backed LLM agent, a Discord user, or a no-op "suspended" controller — and all of
them act through the *same* verb surface (move, take, eat, say, take-note, …). The engine
validates every action the same way no matter who sent it, so an LLM can't do anything a
human couldn't, and vice versa.

```
controllers (LLM / Discord / suspended)
        │  submit commands by name ("take the marsh journal")
        ▼
   WorldActor  ──tick──▶  validate → resolve names → handlers → ECS mutation → events
        │                                                              │
   game loop                                                   projections / memory
```

## Quickstart

```bash
uv sync                     # core install
uv run bunnyland serve --ticks 5     # generate a world, simulate 5 rounds (offline)
```

That runs entirely offline with a deterministic world and characters that simply wait. To
have characters actually *think*, add an LLM (see below):

```bash
uv sync --extra llm
echo 'OLLAMA_CLOUD_API_KEY=sk-...' > .env
uv run bunnyland serve --llm --generator recursive --ticks 20
```

## Documentation

- **[The Vision](docs/vision.md)** — what bunnyland is trying to be, and what belongs in
  core, plugins, clients, scripts, and content libraries.
- **[Running a server](docs/running-a-server.md)** — install, the `serve` loop, the time
  model, and connecting an LLM.
- **[VPS admin setup](docs/vps-admin-setup.md)** — Linux VPS deployment with nginx,
  optional Docker, plugin/world setup, web client connection, and Discord bot wiring.
- **[World creation](docs/world-creation.md)** — generators (`oneshot` vs `recursive`),
  seeds, how generation stays inside the rules, and adding your own generator.
- **[Discord bot](docs/discord-bot.md)** — creating the bot, the token, inviting it,
  wiring a user to a character, and the player commands.
- **[Admin & controllers](docs/admin.md)** — claiming, suspending, and handing off
  characters; enabling/disabling plugins.
- **[Saving & reloading](docs/persistence.md)** — save/autosave/reload a world, and what
  is (and isn't) persisted.
- **[Scripting](docs/scripting.md)** — external JSON scripts for deterministic tests,
  plugin scenarios, and scripted events.

The full design is in [`bunnyland_specification.md`](bunnyland_specification.md); the build
plan is in [`PLAN.md`](PLAN.md).

## Simulation packages

Mechanics ship as **plugins** you enable per world, so a world is whatever bundle you turn
on. Each sim package adds its own components, verbs, systems, and prompt fragments without
touching the others — emergence comes from small systems reacting to shared events. The
full catalogue is in [`bunnyland_mechanics.md`](bunnyland_mechanics.md).

| Package         | Inspired by      | Key mechanics it introduces |
|-----------------|------------------|-----------------------------|
| **Life Sim**    | The Sims         | Needs, moods/thoughts, social bonds and jealousy, romance, family and pregnancy, skill progression, careers and household economy |
| **Colony Sim**  | RimWorld         | Work priorities and jobs, resource gathering, crafting recipes and workstations, ownership and reservations |
| **Garden Sim**  | Stardew Valley   | Soil and tilling, planting/watering/fertilizing, seasonal crop growth, and harvesting |
| **Barbarian Sim** | Conan Exiles   | Survival combat, stamina, temperature exposure, gear durability, poison and corruption |
| **Dragon Sim**  | Skyrim           | Open-world discovery, radiant quests and objectives, factions and reputation |
| **Dagger Sim**  | Daggerfall       | Procedural frontier expansion, rumors, travel logistics, guilds/institutions and services, banking and debt, civic law and fines, custom classes and spells, language pacification, supernatural afflictions, procedural dungeons, etiquette and social approach |
| **Void Sim**    | FTL              | Ships, stations and habitat modules, life support, pressure and airlocks, power grids, ship-system repair, and docking |

Foundational plugins back these up: **Environment** (time, weather, fire), **Mechanisms**
(doors, buttons), **Social Bonds**, **Policy & Boundaries**, **Persona**, **Storyteller**
(paced incidents), **Memory** (private notes and recall), and **World Generators**.

Each sim package ships a ready-to-play example world that shows off its mechanics (and the
life-sim needs every character shares). Spin one up with its `<sim>-demo` generator:

```bash
uv run bunnyland serve --generator voidsim-demo --ticks 5
```

The demos are `lifesim-demo`, `gardensim-demo`, `colonysim-demo`, `barbariansim-demo`,
`dragonsim-demo`, `daggersim-demo`, and `voidsim-demo`. There is also a larger life-sim
showcase, `apartment-demo`: a quirky NYC apartment building of eccentric tenants with
backstories, homes, and daily routines, a rat-man in the warren below, and hidden corners.

## Development

```bash
uv run pytest
uv run ruff check src tests
```

`tests/test_e2e.py` is the best place to see the whole stack exercised: generate a world,
check it matches both the proposal and the agent's prompt, then play several rounds and
assert each action is processed.

## Optional extras

| Extra      | Enables                                  | Install                      |
|------------|------------------------------------------|------------------------------|
| `llm`      | Ollama-backed world generation + agents  | `uv sync --extra llm`        |
| `discord`  | the Discord player front-end             | `uv sync --extra discord`    |
| `chroma`   | ChromaDB vector memory store             | `uv sync --extra chroma`     |
