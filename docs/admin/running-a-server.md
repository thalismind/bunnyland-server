# Running a server

`bunnyland serve` generates a world and runs the **game loop**: each round it advances the
simulation one tick (clock, regeneration, queued commands, consequences) and then lets each
active controller propose its next action. It runs headless — the world simulates whether or
not anyone is watching.

## Install

```bash
uv sync                 # core only: deterministic worlds, characters that wait
uv sync --extra llm     # add LLM generation/agent providers
```

## The simplest run (offline)

```bash
uv run bunnyland serve --ticks 5
```

```
Loaded plugins:
  - bunnyland.core_verbs (Core Verbs) v0.1.0
  - bunnyland.lifesim (Life Sim) v0.1.0
  - bunnyland.memory (Memory) v0.1.0
  - bunnyland.worldgen (World Generators) v0.1.0
Generated world 'a quiet marsh' via 'oneshot': 2 rooms, 2 characters.
Offline demo (no --llm): characters will wait.
Running game loop (5 ticks)...
Stopped after 5 ticks at game epoch 18000s.
```

Offline, the world is the deterministic stub world and characters take no actions — useful
for verifying setup, watching passive systems (hunger, thirst, regen) tick, and developing
plugins without network or API costs.

## Optional client API

Web, admin, and TUI clients live outside this repo, but they can connect to a running
bunnyland server through the optional HTTP/websocket API:

```bash
uv run --extra server bunnyland serve --ticks 0 --api-host 127.0.0.1 --api-port 8765
```

The API exposes:

- `GET /health` for liveness and current world epoch.
- `GET /world/snapshot` for the initial ECS snapshot and world metadata.
- `GET /world/events/recent` for recently published domain events.
- `POST /world/commands` to submit a command envelope into the world actor.
- `WS /world/updates` for an initial snapshot followed by typed domain events.
- `GET /admin/runtime`, `POST /admin/pause`, and `POST /admin/resume` for
  server-level tick control.
- `GET /admin/world/generators`, `POST /admin/world/generate`, and
  `GET /admin/world/generation` for listing enabled generators, starting async world
  replacement, and checking generation status.

Protect `/admin/*` at your reverse proxy.

## Optional MCP endpoint

The MCP server is mounted into the same FastAPI app as the HTTP/websocket API. It does
not start a second process or listen on a second port.

```bash
BUNNYLAND_MCP_ADMIN_TOKEN=change-me \
uv run --extra server --extra mcp bunnyland serve \
  --ticks 0 \
  --api-host 127.0.0.1 \
  --api-port 8765 \
  --mcp
```

This exposes the MCP Streamable HTTP endpoint at `http://127.0.0.1:8765/mcp`.
Agent tools can list and claim characters, inspect snapshots, and queue normal world
commands. World patching and generation tools require the MCP admin token.

See [MCP server](mcp-server.md) for tool details.

For a step-by-step Linux VPS deployment, use the containerized
[VPS Docker setup guide](vps-admin-setup.md). The older host-level setup is kept in
[host dev setup](host-dev-setup.md) for development and debugging.

## Connecting an LLM

Characters only *think* when an LLM is attached. bunnyland uses [Ollama
Cloud](https://ollama.com) by default, and can also drive character controllers through
OpenRouter.

1. Install the extra: `uv sync --extra llm`
2. Put your provider key in a `.env` file (it is git-ignored). Ollama is the default:
   ```
   OLLAMA_CLOUD_API_KEY=sk-...
   # optional: point at a different host (defaults to https://ollama.com)
   # OLLAMA_HOST=http://localhost:11434
   ```
3. Run with `--llm`:
   ```bash
   uv run bunnyland serve --llm --ticks 20
   ```

With `--llm`, world generation and character controllers can use different models.
World generation defaults to `deepseek-v4-pro`; character controllers default to
`deepseek-v4-flash`. Override them separately with `--worldgen-model` and
`--character-model`, or use `--ollama-model` as a shared override. Each character keeps
its own conversation history, so it remembers what it has done.

To use a local Ollama instead of the cloud, set `OLLAMA_HOST` to your local server; the API
key may be any non-empty value for local servers that don't check it.

OpenRouter can drive character controllers, world generation, or both. Set
`OPENROUTER_SERVER_URL` only when pointing the SDK at a non-default endpoint.

```dotenv
OPENROUTER_API_KEY=sk-or-...
# optional: point at a non-default OpenRouter-compatible endpoint
# OPENROUTER_SERVER_URL=https://openrouter.ai/api/v1
```

```bash
uv run bunnyland serve --llm --generator recursive \
  --llm-provider openrouter \
  --worldgen-provider openrouter \
  --worldgen-model openai/gpt-4.1 \
  --character-model openai/gpt-4.1-mini \
  --ticks 20
```

## Options

| Flag             | Default        | Meaning                                                        |
|------------------|----------------|----------------------------------------------------------------|
| `--seed`         | `a quiet marsh`| World-generation seed (free text; flavours LLM generation).    |
| `--generator`    | `oneshot`      | Which world generator to use. See [world creation](../developer/world-creation.md). |
| `--max-rooms`    | `6`            | Room budget for graph-based generators (`recursive`).          |
| `--llm`          | off            | Drive LLM generation and character controllers (needs `llm` extra). |
| `--llm-provider` | `ollama`       | Default provider for character controllers (`ollama` or `openrouter`). |
| `--worldgen-provider` | `ollama`  | Provider for LLM world generation (`ollama` or `openrouter`). |
| `--ollama-model` | (none)         | Shared Ollama model override for generation and characters. |
| `--worldgen-model` | `deepseek-v4-pro` | Ollama model for world generation.                    |
| `--character-model` | `deepseek-v4-flash` | Default Ollama model for character controllers.    |
| `--ticks`        | `10`           | Number of rounds to run; `0` runs forever (until Ctrl-C).      |
| `--tick-seconds` | `1.0`          | Real seconds the loop sleeps between rounds (when `--ticks 0`).  |
| `--time-scale`   | `3600.0`       | Game seconds that pass per round.                              |
| `--api-host`     | `127.0.0.1`    | Host for the optional HTTP/websocket client API.                |
| `--api-port`     | (none)         | Port for the optional HTTP/websocket client API.                |
| `--mcp`          | off            | Mount the MCP endpoint at `/mcp` on the existing API server.    |
| `--mcp-admin-token` | env         | Token required by MCP admin tools; defaults to `BUNNYLAND_MCP_ADMIN_TOKEN`. |
| `--plugin`       | (all default)  | Enable only the named plugin id(s); repeatable. See [admin](./). |
| `--module`       | (none)         | Import an external plugin module; repeatable. See [admin](./).   |
| `--verbose`      | off            | Log each decision and world-generation step at INFO.           |
| `--load`         | (none)         | Resume a saved world instead of generating. See [persistence](../developer/persistence.md). |
| `--load-paused`  | off            | Start the server tick cycle paused when used with `--load`.    |
| `--save`         | (none)         | Save the world to this path on exit.                           |
| `--autosave-every`| `0`           | Autosave every N ticks (needs `--save`).                       |

## The time model

A round advances game time by `tick_seconds × time_scale` seconds. With the defaults
(`1.0 × 3600`) each round is **one game hour**, so regeneration and needs (defined per hour)
move at a comfortable rate while you watch a handful of rounds.

- For a fast offline demo, keep a finite `--ticks` and ignore wall-clock time (the loop
  doesn't sleep when `--ticks` is finite).
- For a long-running server, use `--ticks 0` and tune `--tick-seconds` (how often the loop
  wakes) and `--time-scale` (how much game-time each wake represents). For example
  `--tick-seconds 60 --time-scale 3600` is "one game hour every real minute".

## Running long-term

`--ticks 0` runs until interrupted:

```bash
uv run bunnyland serve --llm --generator recursive --max-rooms 8 --ticks 0 \
  --tick-seconds 30 --time-scale 1800 --save worlds/marsh.json --autosave-every 20
```

`--save` writes the world (and its seed/prompt/generator) on exit; `--autosave-every N`
checkpoints it every N ticks; `--load` resumes a saved world instead of generating a new
one. See [saving & reloading](../developer/persistence.md).

## Watching it play

Pass `--verbose` to log each decision (under `bunnyland.dispatch`) and world-generation step
(under `bunnyland.worldgen`) at INFO:

```bash
uv run bunnyland serve --llm --ticks 10 --verbose
```

```
bunnyland.worldgen recursive worldgen: {'rooms': 3, 'sealed': 9, 'dropped': 0, 'linked': 0}
bunnyland.dispatch character entity_..09 chose take {'item_id': 'entity_..06'}
bunnyland.dispatch character entity_..09 chose say {'text': 'Hello Juniper!', 'intent': 'conversation'}
```

Note that the logged tool calls show *resolved* entity ids — names the controller used
(`"the marsh journal"`) have already been mapped to the entities they refer to.
