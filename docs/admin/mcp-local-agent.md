# MCP local coding-agent setup

This guide covers the operational setup for exposing a Bunnyland server to a local coding
agent over MCP. Use it when you want an agent running on your workstation to inspect the
live world, claim a character, submit game commands, receive MCP resource updates, and
optionally run admin world-editing tools.

The MCP server is disabled by default. When enabled, it mounts on the existing FastAPI app
under `/mcp`; it does not start a second listener or require a second public port.

## Security model

There are two separate secrets:

- **HTTP endpoint auth** protects the MCP route before a client reaches Bunnyland. On the
  VPS deployment, nginx protects `/api/mcp` with the same htpasswd file used for the world
  editor.
- **MCP admin token** authorizes destructive MCP tools. It is passed as the `admin_token`
  tool argument for admin operations such as patching or replacing the world.

Keep both secrets out of git. Store server-side deployment secrets in the private Compose
override or environment used by the host. Store local client credentials in user-level agent
configuration, a password manager, or an ignored local file.

## Enable MCP on a local server

Install the MCP extra along with the server extra:

```bash
uv sync --extra server --extra mcp
```

Start the API with MCP enabled:

```bash
BUNNYLAND_ADMIN_TOKEN='change-this-admin-token' \
uv run --extra server --extra mcp bunnyland serve \
  --api-host 127.0.0.1 \
  --api-port 8765 \
  --mcp
```

The local MCP URL is:

```text
http://127.0.0.1:8765/mcp
```

Local-only servers do not need reverse-proxy Basic auth. Without a proxy injecting
`X-Bunnyland-Admin-Secret`, admin tools take the admin token as an `admin_token` argument.

## Enable MCP on the VPS

For the Docker deployment, enable the plugin through setup-time environment variables or
the wizard:

```bash
BUNNYLAND_ENABLE_MCP=1 \
BUNNYLAND_ADMIN_TOKEN='change-this-admin-token' \
  scripts/vps-docker-setup
```

With the standard nginx frontend, the public MCP URL is:

```text
https://sandbox.example.com/api/mcp/
```

The trailing slash is fine and avoids client/proxy normalization surprises.

The setup script writes the MCP flag and token into the private deployment-specific Compose
configuration. Do not commit that file. If you manually edit `compose.user.yml`, keep any
backups and local secret files ignored with `.git/info/exclude` or an equivalent host-local
ignore mechanism.

## Configure a local coding agent

Configure the agent to use Streamable HTTP and point it at the MCP URL. Legacy MCP SSE is
not used.

Generic MCP client shape:

```json
{
  "transport": "streamable_http",
  "url": "https://sandbox.example.com/api/mcp/",
  "headers": {
    "Authorization": "Basic <base64 user:password>"
  }
}
```

For Codex, prefer a user-level config entry instead of a repo-local file:

```toml
[mcp_servers.bunnyland-vps]
url = "https://sandbox.example.com/api/mcp/"
http_headers = { Authorization = "Basic <base64 user:password>" }
```

If you need to keep the Basic auth material next to a project for local testing, put it in
an ignored file and do not commit the MCP configuration until the project has an agreed
secret-management pattern.

The MCP admin token is not part of the connection header. Pass it only when calling admin
tools:

```json
{
  "tool": "generate_world_admin",
  "arguments": {
    "admin_token": "change-this-admin-token",
    "confirm_reset": true,
    "generator": "recursive",
    "seed": "a moonlit canal town",
    "max_rooms": 6,
    "save": true
  }
}
```

## Validate the connection

First check that the HTTP protection is active:

```bash
curl -i https://sandbox.example.com/api/mcp/
```

Without credentials, the VPS should return `401`. With valid Basic auth, a plain `GET` may
return an MCP-level error such as `406`; that still proves the request reached the MCP app.
Use an MCP client handshake for a real protocol check.

After the client connects, confirm the expected tools are visible:

```text
agent_prompt
claim_character
generate_character_patch_admin
generate_event_patch_admin
generate_item_patch_admin
generate_room_patch_admin
generate_world_admin
list_characters
patch_world_admin
release_character
runtime_status
send_command
world_generation_status_admin
world_overview_admin
world_snapshot_admin
```

## Basic agent loop

Use this sequence to prove that the client can play and then cleanly hand the character
back:

1. Call `runtime_status` and confirm the world is running.
2. Call `list_characters` and choose a suspended, claimable character.
3. Call `claim_character` with a stable `agent_id`.
4. Call `agent_prompt` to get the current room, exits, inventory, and status.
5. Call `send_command` with a normal world command, such as `move`, `take`, `say`, `wait`,
   or another verb exposed by the loaded plugins.
6. Wait for a tick, then call `agent_prompt` or `world_snapshot` to observe the result.
7. Call `release_character` when the local agent is finished.

Example claim:

```json
{
  "tool": "claim_character",
  "arguments": {
    "agent_id": "local-coding-agent",
    "character_name": "Juniper",
    "label": "local coding agent"
  }
}
```

Example move:

```json
{
  "tool": "send_command",
  "arguments": {
    "agent_id": "local-coding-agent",
    "command_type": "move",
    "payload": {
      "direction": "east"
    }
  }
}
```

Example release:

```json
{
  "tool": "release_character",
  "arguments": {
    "agent_id": "local-coding-agent"
  }
}
```

By default, release suspends the character so another controller can claim it later. To hand
the character to an LLM controller, pass `mode: "llm"` and optionally `provider` and
`model`.

## Events and prompts

MCP clients can subscribe to resource updates. Bunnyland sends
`notifications/resources/updated` for these resources:

```text
bunnyland://events/recent
bunnyland://agents/<agent_id>/events
bunnyland://agents/<agent_id>/prompt
```

After receiving an update notification, read the resource again. Agent event resources are
updated when the controlled character is the event actor, including command results and
point regeneration events such as action or focus point changes. Agent prompt resources are
updated on every domain event because prompt context can change indirectly through nearby
rooms, actors, conditions, and regenerated points.

## Operations

Rotate the Basic auth password and MCP admin token separately. Updating Basic auth controls
who can connect to the endpoint. Updating the MCP admin token controls who can call admin
tools after connecting.

When rotating the admin token on Docker, update the private Compose configuration and
restart the server container. When rotating Basic auth on the VPS, update the nginx
htpasswd file and reload nginx.

If `/api/mcp` returns `404`, confirm `BUNNYLAND_ENABLE_MCP=1` and that the server command
includes `--mcp`. If admin tools report that `BUNNYLAND_ADMIN_TOKEN` is not configured,
confirm the token is present in the server environment.
