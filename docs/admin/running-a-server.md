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
- `GET /world/events/recent` for the admin-authenticated global event history.
- `GET /world/character/{id}/events/recent` for a claim-authenticated, visibility-filtered
  player fallback feed.
- `POST /world/commands` to submit a command envelope into the world actor.
- `WS /world/updates` for an initial snapshot followed by typed domain events.
- `WS /world/character/{id}/updates` for claim-authenticated player invalidations and visible
  events; clients send the claim id and secret in the first frame, never in the URL.
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
BUNNYLAND_ADMIN_TOKEN=change-me \
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

For a step-by-step Linux VPS deployment, including the flow used by the maintained public
sandbox server, use the containerized [VPS Docker setup guide](vps-admin-setup.md). The
older host-level setup is kept in [host dev setup](host-dev-setup.md) for development and
debugging.

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

Server runtime settings can also be read from a private YAML file:

```bash
uv run bunnyland serve --config bunnyland.yml
```

| Flag             | Default        | Meaning                                                        |
|------------------|----------------|----------------------------------------------------------------|
| `--config`       | (none)         | Read server settings, credentials, plugins, and addon config from YAML. |
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
| `--admin-token`  | env            | Admin secret gating the whole `/admin/*` surface plus snapshot/overview/DM projections, the world-updates stream, and MCP admin tools; defaults to `BUNNYLAND_ADMIN_TOKEN`. |
| `--player-client-id` | env        | Allow one player `client_id`; repeat or pass comma-separated values. Defaults to `BUNNYLAND_PLAYER_CLIENT_IDS`; unset allows any player client ID. |
| `--admin-client-id` | env         | Allow one admin `client_id`; repeat or pass comma-separated values. Defaults to `BUNNYLAND_ADMIN_CLIENT_IDS`; unset allows any admin client ID with the admin token. |
| `--plugin`       | (all default)  | Enable only the named plugin id(s); repeatable. See [admin](./). |
| `--starter-pack` | (none)         | Enable a startup preset: `peaceful`, `fantastic`, or `futuristic`. |
| `--verbose`      | off            | Log each decision and world-generation step at INFO.           |
| `--load`         | (none)         | Resume a saved world instead of generating. See [persistence](../developer/persistence.md). |
| `--load-paused`  | off            | Start the server tick cycle paused when used with `--load`.    |
| `--save`         | (none)         | Save the world to this path on exit.                           |
| `--autosave-every`| `0`           | Autosave every N ticks (needs `--save`).                       |

## Admin surface security

The entire `/admin/*` surface is gated **server-side and fail-closed**: every admin route
requires the admin secret in the `X-Bunnyland-Admin-Secret` header, and if no admin token is
configured (`--admin-token` / `BUNNYLAND_ADMIN_TOKEN`) those routes return `403` rather than
falling open. This matters because routes such as `POST /admin/controllers/assign` and
`PATCH /admin/world` reassign controllers and mutate the world directly, bypassing the
per-player claim secret. The production nginx config performs admin Basic auth and then
injects the `X-Bunnyland-Admin-Secret` header (clients can never supply their own), so
browser admins log in once. Generic player `/api/` routes are protected by a separate
player Basic-auth file. Basic-auth usernames are not Bunnyland `client_id` values; nginx
forwards `X-Bunnyland-Client-Id` when a client provides it, and otherwise the server keeps
using the request body or query `client_id`. Do **not** publish the API container's port
directly — keep nginx the only ingress so the admin surface is never reachable without
passing Basic auth first.

Optional client-ID allowlists add a second role-scoped check. Set
`BUNNYLAND_PLAYER_CLIENT_IDS` and/or `BUNNYLAND_ADMIN_CLIENT_IDS` to comma-separated
client IDs, or repeat `--player-client-id` / `--admin-client-id`. When configured, player
claims and claim-secret-backed player requests must match the player list. Admin HTTP,
WebSocket, and MCP requests must match the admin list via `X-Bunnyland-Client-Id`.

Player commands (`POST /world/commands`) and the MCP `send_command` tool reject the control
verbs (`take-control`, `release-to-llm`, `suspend`, `resume`); controller changes go through
the dedicated `/world/controllers/web/*` endpoints (or the MCP claim/release tools), which
validate that the caller owns the claim.

## The time model

A round advances game time by `tick_seconds × time_scale` seconds. With the defaults
(`1.0 × 3600`) each round is **one game hour**, so regeneration and needs (defined per hour)
move at a comfortable rate while you watch a handful of rounds.

- For a fast offline demo, keep a finite `--ticks` and ignore wall-clock time (the loop
  doesn't sleep when `--ticks` is finite).
- For a long-running server, use `--ticks 0` and tune `--tick-seconds` (how often the loop
  wakes) and `--time-scale` (how much game-time each wake represents). For example
  `--tick-seconds 60 --time-scale 3600` is "one game hour every real minute".

Starter packs are startup plugin selections, not live-world toggles. Use
`--starter-pack peaceful`, `--starter-pack fantastic`, or `--starter-pack futuristic`
before generating or loading the world so the server imports and applies the proper
mechanics from startup. Docker deployments can set `BUNNYLAND_STARTER_PACK` to the same
pack name.

Starter packs include required base layers. For example, `futuristic` includes
life-sim, colony-sim, garden-sim, barbarian-sim, void-sim, and nuke-sim so salvage,
resources, survival pressure, and radiation all load together. If you use repeated
`--plugin` flags instead, include every required plugin listed in [admin](./).

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

## Observability (OpenTelemetry)

The engine can export **metrics about the world** and **traces about the actions agents
run** over OpenTelemetry. It is **off by default** and a no-op unless you install the
optional `otel` extra *and* set `BUNNYLAND_OTEL_ENABLED`:

```bash
uv sync --extra otel   # or: pip install 'bunnyland[otel]'

BUNNYLAND_OTEL_ENABLED=1 \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
uv run bunnyland serve --llm --ticks 0
```

The standard OTLP environment variables are honoured by the SDK directly:

- `OTEL_EXPORTER_OTLP_ENDPOINT` — collector address (e.g. an OpenTelemetry Collector,
  Grafana Alloy, Tempo, or Jaeger OTLP endpoint).
- `OTEL_EXPORTER_OTLP_PROTOCOL` — `grpc` (default) or `http/protobuf`.
- `OTEL_EXPORTER_OTLP_HEADERS` — auth headers for a hosted collector.
- `OTEL_SERVICE_NAME` — service name (defaults to `bunnyland`).

When disabled, the per-tick and per-command hot paths cost a single boolean check, so it
is safe to leave the instrumentation in place in production and flip the gate on as needed.

**Metrics emitted** (attributes kept low-cardinality — no raw ids or free-text reasons):

| Metric | Type | Attributes |
|--------|------|------------|
| `bunnyland.tick.duration` | histogram (s) | — |
| `bunnyland.commands.submitted` / `.accepted` | counter | `command_type` |
| `bunnyland.commands.rejected` | counter | `command_type`, `reject_reason` (bucketed) |
| `bunnyland.command.handler.duration` | histogram (s) | `command_type` |
| `bunnyland.llm.decision.duration` | histogram (s) | `provider`, `model` |
| `bunnyland.llm.tokens.prompt` / `.completion` / `.total` | counter | `provider`, `model` |
| `bunnyland.llm.cost` | counter (USD) | `provider`, `model` |
| `bunnyland.world.entities` / `.characters` / `.rooms` | observable gauge | — |
| `bunnyland.worldgen.duration` | histogram (s) | `generator`, `llm` |

**Spans emitted** — a server loop iteration is the trace root, with the world tick and the
controller turn hanging off it:

- `game.loop.iteration` (root) → `game.tick` + `controller.run_once`.
- `game.tick` (also a root when ticked outside the loop) carries `tick.epoch` and breaks
  into phase children: `tick.ingest`, `tick.systems`, `tick.commands`,
  `tick.consequences`, `tick.after_tick`.
- `tick.commands` → `command.attempt` (with `command.type`, `command.lane`, `command.id`,
  `character.id`, `command.executed`/`command.queued`, and on failure `command.outcome`
  plus `command.reject_reason` (bucketed) and `command.reject_reason_text`) →
  `handler.execute` (with `handler.kind`, `handler.ok`, `handler.reason`,
  `handler.event_count`).
- `controller.run_once` (with `dispatch.actable_count`, `dispatch.decision_count`) →
  `agent.prompt.build` and `agent.decide` (with `provider`, `model`, `agent.kind`,
  `character.id`, `decision.tool`, `decision.arguments`, and — for LLM-controlled
  characters — `decision.prompted`, `decision.prompt`, `decision.prompt_chars`; live LLM
  calls also add `llm.request.kind`, `llm.tools.count`, `llm.history.messages`,
  `llm.system_prompt_chars`, `llm.tokens.available`, input/output token counts as
  `llm.tokens.prompt`/`.completion`, `llm.tokens.total`, and `llm.cost.available`.
  Provider-reported `llm.cost` is attached when the SDK/API exposes cost metadata.
- `command.submit` at the single submission chokepoint, so every queued command (API,
  MCP, Discord, or autonomous dispatch) is tied back to its originating trace.
- `world.generate` at startup, with child `worldgen.llm.request` spans when recursive
  LLM generation asks Ollama or OpenRouter for a room, door, content, character, item, or
  event proposal.

Unlike metric attributes, span attributes carry richer, higher-cardinality context (entity
ids, the rendered prompt, the chosen arguments) since each span is a discrete event. Long
text such as the prompt is truncated to `MAX_ATTRIBUTE_CHARS`. With the server API running,
incoming HTTP requests are also auto-instrumented as their own server spans.

### Bundled Tempo backend (compose)

For Docker/Compose deployments, [`compose.tempo.yml`](../../compose.tempo.yml) is an
optional, off-by-default fragment that runs a single monolithic Grafana Tempo container,
wires the server to export **traces** to it over OTLP (metrics stay off — Tempo is
traces-only), and persists trace blocks to a small `tempo-data` volume:

```bash
docker compose -f compose.yml -f compose.tls.yml -f compose.tempo.yml up -d
```

Tempo publishes no host ports; it is reachable only on the compose network. Its query API
is exposed for a remote Grafana through the **same** frontend nginx (the fragment mounts
`deploy/nginx/tempo-location.inc`, which adds a `/tempo/` route behind the same
`Bunnyland admin` Basic-auth realm as every other admin surface) — so it requires the same
admin password. Point a Grafana Tempo datasource at `https://<your-host>/tempo/` with those
credentials. nginx resolves the `tempo` upstream by its compose DNS name and caches the IP
at config load, so restart the `frontend` after recreating the `tempo` container. Trace
retention defaults to 72h (tune `compactor.block_retention` in
[`deploy/tempo/tempo.yaml`](../../deploy/tempo/tempo.yaml) to grow or shrink the volume).
The published server image already includes the `otel` extra, so no rebuild is needed.
