# MCP server authentication

Bunnyland mounts streamable HTTP MCP at `/mcp` when `bunnyland serve --mcp` is enabled.
The MCP transport uses the same opaque bearer tokens as every other API client; there is no
MCP-specific credential or tool argument.

Provision a 90-day manual-rotation token and capture the printed secret once:

```bash
bunnyland auth provision-token \
  --db /data/auth-tokens.sqlite3 \
  --subject local-agent \
  --scope world:play \
  --scope world:admin
```

Configure the MCP client's HTTP transport with:

```text
Authorization: Bearer blt_<public-id>_<random-secret>
```

`world:play` permits character claims, perceived views, normal commands, and client event
resources. `world:admin` also permits global projections, world generation/editing, runtime
administration, and the corresponding admin MCP tools. Admin scope implies play scope.

Client-ID allowlists remain an additional policy check. Send `X-Bunnyland-Client-Id` when
the deployment configures `BUNNYLAND_PLAYER_CLIENT_IDS` or `BUNNYLAND_ADMIN_CLIENT_IDS`, but
do not treat that caller-supplied value as identity; the bearer token subject is identity.

Rotate automation credentials explicitly:

```bash
bunnyland auth list-tokens --db /data/auth-tokens.sqlite3
bunnyland auth replace-token --db /data/auth-tokens.sqlite3 --token-id <public-id>
bunnyland auth revoke --db /data/auth-tokens.sqlite3 --token-id <public-id>
```

Replacement secrets are printed once. Update the MCP client before discarding them. Revoked
or expired credentials receive `401` with `WWW-Authenticate: Bearer`; valid play-only tokens
receive `403` when an admin tool is requested.

Never place tokens in MCP tool arguments, URLs, repository configuration, screenshots, or
logs. Use the client's protected secret/credential facility and normal bearer-header support.
