# MCP server and local agents

Bunnyland mounts Streamable HTTP MCP at `/v1/mcp/` on the existing API listener. It does not
open a second port or use an MCP-specific credential. HTTP, WebSocket, and MCP share the same
opaque bearer principals and `world:play` / `world:admin` scopes.

## Prerequisites

Complete the [Discord guide](discord-bot.md) or skip Discord intentionally. The server must
already have a private token database and a loopback API. Your MCP client must support
Streamable HTTP and an `Authorization` header stored outside its project files.

Install the extra and enable MCP:

```bash
uv sync --locked --extra server --extra mcp
uv run bunnyland serve --config bunnyland.yml \
  --mcp \
  --api-host 127.0.0.1 \
  --api-port 8765 \
  --auth-users-file data/auth/users.yml \
  --token-db data/auth/tokens.sqlite3
```

Local endpoint:

```text
http://127.0.0.1:8765/v1/mcp/
```

Hosted same-origin endpoint:

```text
https://play.example.com/api/v1/mcp/
```

Keep the trailing slash. nginx should forward the bearer header and
`X-Bunnyland-Client-Id`; it should not add Basic auth or inject a second shared secret.

## Provision the smallest useful token

For normal play:

```bash
uv run bunnyland auth provision-token \
  --db data/auth/tokens.sqlite3 \
  --subject my-local-agent \
  --scope world:play \
  --expires-days 90
```

Add `--scope world:admin` only when that specific client must generate/edit worlds, inspect
global projections, administer runtime state, or use other privileged MCP tools. Prefer a
separate short-lived admin token over making the everyday play token an admin.

Capture the printed secret once. Configure the transport header with the client's protected
credential facility:

```text
Authorization: Bearer blt_<public-id>_<random-secret>
```

The bearer token never belongs in an MCP tool schema, prompt, argument, URL, repository
configuration, screenshot, or log. If a client cannot protect and send an HTTP header, do not
give that client a production credential.

## Understand bearer and claim credentials

The bearer token grants access to Bunnyland. A character claim ID and claim secret select the
specific character that the client controls. They are separate on purpose:

1. connect with a play-capable bearer principal;
2. list claimable characters;
3. claim one character and protect the returned claim secret;
4. use perceived views and normal action tools with that claim;
5. release the claim when finished.

Do not persist claim secrets in a world snapshot or promote them into long-lived account
tokens. Follow the play loop in the [MCP player guide](../player/clients/mcp.md).

## Test least privilege

With a play token, verify that character listing/claim/play works and an admin-only tool is
rejected with `403`. With no or an invalid bearer token, the MCP transport should return an
authentication failure. A valid token whose client ID is excluded by an optional allowlist
must also be rejected.

For client-specific configuration syntax, use that client's documentation. The essential
values are transport `streamable-http`, one of the endpoint URLs above, and the protected
`Authorization` header.

## Rotate and revoke

```bash
uv run bunnyland auth list-tokens --db data/auth/tokens.sqlite3
uv run bunnyland auth replace-token \
  --db data/auth/tokens.sqlite3 \
  --token-id TOKEN_ID
uv run bunnyland auth revoke \
  --db data/auth/tokens.sqlite3 \
  --token-id TOKEN_ID
```

Update the client with the replacement secret before discarding it. A revoked or expired
credential receives `401` with `WWW-Authenticate: Bearer`; a valid play-only principal
receives `403` for an admin operation.

The shorter [MCP authentication reference](mcp-server.md) documents the same transport
boundary for operators integrating custom clients.

## Troubleshooting

### The client receives 404

Confirm `--mcp` is enabled, the `mcp` extra is installed, and the URL ends in `/v1/mcp/`.
Hosted clients need the public `/api/` prefix.

### The client receives 401

Check that it is sending `Authorization: Bearer ...` on the HTTP transport, then inspect token
expiry/revocation metadata. Never move the token into tool arguments as a workaround.

### The client receives 403

The principal is authenticated but lacks a required scope or fails a configured client-ID
allowlist. Use `world:play` for character operation and reserve `world:admin` for privileged
tools.

### Local MCP works but hosted MCP fails

Verify nginx forwards `Authorization`, does not buffer the stream, preserves the request
path/trailing slash, and has a sufficiently long read timeout. Use HTTPS for every non-local
client.

### A claim becomes stale

Claims can expire, be released, or change controller generation. List/claim again rather than
reusing old claim secrets or queued commands.

[← Discord bot](discord-bot.md) · [Image generation →](image-generation.md)
