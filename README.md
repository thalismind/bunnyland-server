# bunnyland

An asynchronous social sandbox where humans and LLM agents share persistent characters in
an emergent ECS simulation. Built on the [Relics](https://github.com/ssube/relics) ECS
database.

Characters live in a world of rooms, items, and needs. They are driven by **controllers** —
an Ollama- or OpenRouter-backed LLM agent, a Discord user, or a no-op "suspended" controller — and all of
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

Ollama is the default provider. OpenRouter can drive character controllers and world
generation with `--llm-provider openrouter`, `--worldgen-provider openrouter`, and
`OPENROUTER_API_KEY`; see [Running a server](docs/running-a-server.md#connecting-an-llm).

## Docker Compose

The server repo includes a ready-to-run Compose stack using published containers:
Install Docker, nerdctl, or Podman with Compose support before running it. On Ubuntu,
install Docker Engine from Docker's external apt repository using Docker's
[Install using the repository](https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository)
guide; do not rely on the older Ubuntu `docker.io` package for this setup.

```bash
BUNNYLAND_CONTAINER_RUNTIME=docker \
BUNNYLAND_TLS=0 \
BUNNYLAND_CONFIGURE_FIREWALL=0 \
BUNNYLAND_HTTP_BIND=127.0.0.1:8080 \
BUNNYLAND_DOMAIN=localhost \
BUNNYLAND_DATA_DIR=/tmp/bunnyland-data \
BUNNYLAND_ADMIN_USER=editor \
BUNNYLAND_ADMIN_PASSWORD=local \
BUNNYLAND_ENABLE_LLM=0 \
BUNNYLAND_ENABLE_DISCORD=0 \
  scripts/vps-docker-setup
```

Open `http://localhost:8080/`. The `frontend` container serves the web client and proxies
same-origin `/api/` requests to the private `server` container. Server state is bind-mounted
from `BUNNYLAND_DATA_DIR` into `/data` so admins can inspect saved worlds directly.
For a real VPS deployment over HTTPS, the fastest path is the interactive
`scripts/vps-docker-wizard`: it prompts for the required values and then runs
`scripts/vps-docker-setup` for you. You can also run `scripts/vps-docker-setup` directly with
the `BUNNYLAND_*` variables, as in the block above. Either way the setup script writes
`compose.user.yml`, configures admin auth, obtains a Let's Encrypt certificate with certbot,
and runs the checked-in Compose files. See the
[VPS Docker setup guide](docs/vps-admin-setup.md) for the full walkthrough.

For local image development, add the build override:

```bash
docker compose --env-file /dev/null -f compose.yml -f compose.user.yml -f compose.build.yml up -d --build
```

To reload an existing bind-mounted world instead of generating one, add
`BUNNYLAND_WORLD_SAVE` to the setup command:

```bash
BUNNYLAND_WORLD_SAVE=/tmp/bunnyland-data/worlds/main.json
```

To override the browser favicon, set `BUNNYLAND_FAVICON_FILE` during setup:

```bash
BUNNYLAND_FAVICON_FILE=/opt/bunnyland/favicon.png
```

CI builds and publishes `ghcr.io/thalismind/bunnyland-server` on pushes to `main`, with
branch tags and `latest` for the default branch. The web repo publishes
`ghcr.io/thalismind/bunnyland-web` with the same tag scheme.

## Documentation

### Player guides

- **[Getting started](docs/getting-started.md)** — looking around, moving, inventory,
  and talking to other characters.
- **[Gardening and farming](docs/gardening.md)** — finding soil, planting seeds,
  watering crops, harvesting produce, and selling it.
- **[Life-sim homes and rent](docs/lifesim.md)** — finding or claiming a home,
  joining a household, charging rent, and paying bills.

### Technical docs

- **[The Vision](docs/vision.md)** — what bunnyland is trying to be, and what belongs in
  core, plugins, clients, scripts, and content libraries.
- **[Running a server](docs/running-a-server.md)** — install, the `serve` loop, the time
  model, and connecting Ollama or OpenRouter.
- **[VPS Docker setup](docs/vps-admin-setup.md)** — Linux VPS deployment with the
  containerized server/frontend stack, Let's Encrypt, admin auth, LLM providers, and Discord bot
  wiring.
- **[Host dev setup](docs/host-dev-setup.md)** — older non-container host setup for
  development and debugging.
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

Optional live LLM checks are marked and skipped by default. They load `.env` before
checking credentials. To exercise real Ollama and OpenRouter SDK calls, install the `llm`
extra, set `BUNNYLAND_LIVE_LLM=1` plus `OLLAMA_HOST` or `OLLAMA_CLOUD_API_KEY` and/or
`OPENROUTER_API_KEY`, then run:

```bash
uv run pytest -m live_llm
```

`tests/test_e2e.py` is the best place to see the whole stack exercised: generate a world,
check it matches both the proposal and the agent's prompt, then play several rounds and
assert each action is processed.

## Optional extras

| Extra      | Enables                                  | Install                      |
|------------|------------------------------------------|------------------------------|
| `llm`      | Ollama/OpenRouter world generation and character agents | `uv sync --extra llm` |
| `discord`  | the Discord player front-end             | `uv sync --extra discord`    |
| `chroma`   | ChromaDB vector memory store             | `uv sync --extra chroma`     |
