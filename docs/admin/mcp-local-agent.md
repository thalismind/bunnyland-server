# Connect a local agent to Bunnyland MCP

Start Bunnyland with MCP and persistent authentication state:

```bash
bunnyland serve --mcp --api-port 8765 \
  --auth-users-file data/auth-users.yml \
  --token-db data/auth-tokens.sqlite3
```

Provision a manual token for the agent:

```bash
bunnyland auth provision-token \
  --db data/auth-tokens.sqlite3 \
  --subject my-agent \
  --scope world:play
```

Add `--scope world:admin` only when the agent needs privileged projections or admin tools.
Configure the MCP endpoint as `http://127.0.0.1:8765/v1/mcp/` (or the hosted `/api/v1/mcp/` URL) and
set `Authorization: Bearer <printed-token>` using the agent client's protected secret store.

The token never appears in an MCP tool schema or argument. Character claim IDs and claim
secrets are still separate: the bearer token grants Bunnyland access, while claim credentials
select the character controlled by the agent.

Use `bunnyland auth list-tokens`, `replace-token`, and `revoke` for manual lifecycle
operations. Hosted nginx forwards the bearer header to FastAPI; it does not authenticate MCP
with Basic auth or inject another secret.
