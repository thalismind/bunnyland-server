# MCP server

The MCP integration exposes Bunnyland to agentic clients over Streamable HTTP. It mounts
inside the existing FastAPI app at `/mcp`; it does not start a separate process or listen
on a separate port.

Use it when an external agent should inspect the live world, claim a character, submit
ordinary world commands, or perform admin-authorized world editing/generation.

## Install

```bash
uv sync --extra server --extra mcp
```

`server` provides FastAPI/Uvicorn. `mcp` provides the official Python MCP SDK.

## Run

```bash
BUNNYLAND_ADMIN_TOKEN=change-me \
uv run --extra server --extra mcp bunnyland serve \
  --ticks 0 \
  --api-host 127.0.0.1 \
  --api-port 8765 \
  --mcp
```

The MCP endpoint is:

```text
http://127.0.0.1:8765/mcp
```

`--mcp` requires `--api-port` because MCP is mounted on the HTTP API app. If the API is
reverse-proxied under a prefix, include that prefix in the client URL. For example, an
nginx rule that maps public `/api/*` to the backend exposes MCP at:

```text
https://sandbox.example.com/api/mcp
```

## Authentication

There is a single admin secret, `BUNNYLAND_ADMIN_TOKEN` (also `--admin-token`), checked via
the `X-Bunnyland-Admin-Secret` header. It gates the snapshot/overview/DM projections, the
`/world/updates` stream, and the MCP `*_admin` tools.

Two layers cooperate on the VPS Docker deployment:

- nginx protects `/api/admin/`, `/api/mcp[/]`, and the admin world paths with one Basic-auth
  realm (the world-editor htpasswd). After a login it injects `X-Bunnyland-Admin-Secret`
  before proxying, so a single browser login also authorizes the same-origin WebSocket.
- The backend independently verifies that injected token, so reaching the app directly (not
  through nginx) still requires it.

Because nginx injects the token on `/api/mcp[/]`, MCP admin tools authorize from the header
automatically: a proxied client need not pass `admin_token`. The argument remains as a
fallback for direct, non-proxied MCP clients. Player tools never require it.

Do not expose MCP admin tools with a weak shared token. They can patch or replace the live
world.

## Client setup

Configure your MCP client for Streamable HTTP and point it at the `/mcp` URL above. The
exact config shape depends on the client, but the important values are:

```json
{
  "transport": "streamable_http",
  "url": "http://127.0.0.1:8765/mcp"
}
```

For the VPS public URL, configure the client to send HTTP Basic auth credentials for the
world-editor user because nginx protects `/api/mcp` before requests reach Bunnyland. If
the client does not have dedicated username/password fields, use its custom-header support
for the `Authorization` header.

The server uses stateful Streamable HTTP so it can deliver MCP resource-update
notifications. If your client calls the transport `http` rather than `streamable_http`,
use the client’s Streamable HTTP option. Legacy MCP SSE transport is not used here.

## Agent workflow

Start by listing available characters:

```json
{
  "tool": "list_characters",
  "arguments": {}
}
```

Claim a specific character by name:

```json
{
  "tool": "claim_character",
  "arguments": {
    "agent_id": "local-agent",
    "character_name": "Juniper",
    "label": "local planning agent"
  }
}
```

Or omit `character_name` and `character_id` to claim the first suspended, claimable
character:

```json
{
  "tool": "claim_character",
  "arguments": {
    "agent_id": "local-agent"
  }
}
```

Claiming creates or reuses an `MCPControllerComponent` and assigns it to the character.
Like Discord claims, automatic claims skip child life-stage characters unless
`allow_child_claims` is true.

Read the current Bunnyland prompt for the claimed character:

```json
{
  "tool": "agent_prompt",
  "arguments": {
    "agent_id": "local-agent"
  }
}
```

The same prompt is available as a resource:

```text
bunnyland://agents/local-agent/prompt
```

Send a command through the normal world command queue:

```json
{
  "tool": "send_command",
  "arguments": {
    "agent_id": "local-agent",
    "command_type": "move",
    "payload": {
      "direction": "north"
    }
  }
}
```

`send_command` accepts the same command types that the actor currently exposes. Core
examples include `move`, scoped inspection through `character_view`/`room_view`, `take`,
`put`, `use`, `write`, `sleep`, `wake`, `wait`, `say`, and `tell`; enabled sim plugins add
their own verbs. Commands still pay action/focus costs, obey policy gates, and can be
rejected by handlers.

Players should inspect the world through the scoped projections — `character_view` (your
own perceived room) and `room_view` — never the full snapshot. The full ECS dump is
admin-only, because seeing the whole world at once would be cheating. With the admin token,
use `world_snapshot_admin`:

```json
{
  "tool": "world_snapshot_admin",
  "arguments": {"admin_token": "..."}
}
```

Use `runtime_status` to check whether the tick loop is running or paused:

```json
{
  "tool": "runtime_status",
  "arguments": {}
}
```

Release the character when the client is done:

```json
{
  "tool": "release_character",
  "arguments": {
    "agent_id": "local-agent"
  }
}
```

By default this suspends the character so it can be claimed again. To hand it back to an
LLM controller instead, pass `mode: "llm"` and optionally `provider` and `model`.

## Event resources

MCP clients can subscribe to resources and receive `notifications/resources/updated`
whenever Bunnyland publishes relevant domain events. After receiving the notification, read
the resource again for the latest data.

Global recent events:

```text
bunnyland://events/recent
```

Events for one claimed MCP agent:

```text
bunnyland://agents/local-agent/events
```

Current prompt for one claimed MCP agent:

```text
bunnyland://agents/local-agent/prompt
```

The global event resource updates for every domain event. Agent event resources update
when the controlled character is the event actor, which includes command results and point
regeneration events such as `ActionPointsChangedEvent` and `FocusPointsChangedEvent`.
Agent prompt resources update on every domain event because prompt context can change
indirectly through room events, nearby actors, conditions, and regenerated points.

## Admin tools

Admin tools authorize from the `X-Bunnyland-Admin-Secret` header an authenticating proxy
injects, so a proxied client need not pass anything. The examples below show the explicit
`admin_token` argument, which is the fallback for direct, non-proxied MCP clients.

Start async world replacement:

```json
{
  "tool": "generate_world_admin",
  "arguments": {
    "admin_token": "change-me",
    "confirm_reset": true,
    "generator": "recursive",
    "seed": "rainy lantern town",
    "max_rooms": 6,
    "save": true
  }
}
```

Poll generation status:

```json
{
  "tool": "world_generation_status_admin",
  "arguments": {
    "admin_token": "change-me"
  }
}
```

Apply a world-editor patch:

```json
{
  "tool": "patch_world_admin",
  "arguments": {
    "admin_token": "change-me",
    "operations": [
      {
        "op": "set_component",
        "entity_id": "entity_123",
        "component": {
          "type": "IdentityComponent",
          "fields": {
            "name": "Lantern Hall",
            "kind": "room"
          }
        }
      }
    ]
  }
}
```

Generate editor patch proposals without applying them:

```json
{
  "tool": "generate_room_patch_admin",
  "arguments": {
    "admin_token": "change-me",
    "door_entity_id": "entity_456",
    "direction": "east",
    "prompt": "a small greenhouse with rain on the glass"
  }
}
```

The patch-generation tools return `WorldPatchRequest` payloads. Apply those with
`patch_world_admin` after review.

## Tool reference

| Tool | Auth | Purpose |
|------|------|---------|
| `list_characters` | none | List characters and controller status. |
| `world_snapshot_admin` | MCP admin token | Return the full serialized ECS snapshot and metadata. |
| `runtime_status` | none | Report epoch, paused, and running state. |
| `agent_prompt` | none | Return the current prompt for an MCP-controlled agent. |
| `claim_character` | none | Assign an MCP controller to a character. |
| `release_character` | none | Release an MCP-controlled character to suspended or LLM control. |
| `send_command` | none | Queue a command for the MCP-controlled character. |
| `patch_world_admin` | MCP admin token | Apply world-editor patch operations. |
| `generate_world_admin` | MCP admin token | Start async world replacement. |
| `world_generation_status_admin` | MCP admin token | Report generation job status. |
| `generate_room_patch_admin` | MCP admin token | Generate a room patch proposal. |
| `generate_character_patch_admin` | MCP admin token | Generate a character patch proposal. |
| `generate_item_patch_admin` | MCP admin token | Generate an item patch proposal. |
| `generate_event_patch_admin` | MCP admin token | Generate a story event patch proposal. |

## Troubleshooting

If `/mcp` is missing, confirm the server was started with both `--api-port` and `--mcp`.

If the server fails to start with an MCP import error, install the extra:

```bash
uv sync --extra server --extra mcp
```

If admin tools return `BUNNYLAND_ADMIN_TOKEN is not configured`, set
`BUNNYLAND_ADMIN_TOKEN` or pass `--admin-token` when starting the server.

If a command queues but does not run immediately, check `runtime_status`. A paused server
will keep queued commands pending until resumed. Commands can also wait for action/focus
points when `on_insufficient_points` is `queue`.

If a command is rejected as stale, the character was reassigned after the command was
created. Claim the character again and submit a fresh command.
