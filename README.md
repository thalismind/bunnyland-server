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

- **[Running a server](docs/running-a-server.md)** — install, the `serve` loop, the time
  model, and connecting an LLM.
- **[World creation](docs/world-creation.md)** — generators (`oneshot` vs `recursive`),
  seeds, how generation stays inside the rules, and adding your own generator.
- **[Discord bot](docs/discord-bot.md)** — creating the bot, the token, inviting it,
  wiring a user to a character, and the player commands.
- **[Admin & controllers](docs/admin.md)** — claiming, suspending, and handing off
  characters; enabling/disabling plugins.
- **[Saving & reloading](docs/persistence.md)** — save/autosave/reload a world, and what
  is (and isn't) persisted.

The full design is in [`bunnyland_specification.md`](bunnyland_specification.md); the build
plan is in [`PLAN.md`](PLAN.md).

## Development

```bash
uv run pytest            # 122 tests
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
