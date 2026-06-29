# Security Principals And Claims

This document defines the naming convention for Bunnyland control security. Keep these
terms consistent in API models, components, tools, docs, local storage, and tests.

## Names

Use these suffixes exactly:

- `*_id`: public stable identifier.
- `*_kind`: public category string.
- `*_secret`: bearer secret. Secrets never enter ECS, world snapshots, query params, or
  persisted world files.

The current claim fields are:

- `client_kind`: public current client category, such as `web`, `mcp`, or `discord`.
  This is metadata about the attached client/controller kind, not the ownership proof.
- `client_id`: public persistent client identifier. This is safe to store in ECS and
  show in admin snapshots. The same `client_id` can move between client kinds.
  Server admins may optionally restrict accepted player and admin client IDs with
  role-scoped allowlists; this is a coarse admission check, not the ownership proof.
- `claim_id`: public server-issued claim identifier. This is safe to store in ECS and
  persist. Clients must never choose claim IDs for new claims.
- `claim_secret`: private bearer secret for the claim. This is only held by the client
  and the server's in-memory claim-secret registry.

Do not use `agent_id` for MCP clients. MCP callers are clients in the security model, so
MCP tool arguments and controller metadata use `client_id`. LLM agents remain an
implementation detail of LLM controllers and are not claiming clients.

## Graph Model

A character is controlled through a controller entity:

```text
Character <- ControlledBy -> Controller
```

A claimed controller carries public claim metadata:

```text
Controller + ClaimedComponent(client_kind, client_id, claim_id, character_id)
```

The client and claim secret live outside ECS:

```text
(client_id, claim_id) -> claim_secret
```

The `claim_secret` mapping is process-local in v1. Because the world is persisted but
secrets are not, startup removes persisted `ClaimedComponent` entries that do not have a
matching in-memory secret. This makes claims non-persistent across server restart for
now, while preserving the rule that secrets never enter persisted ECS data.

## Authorization Rule

Private character data requires all of:

- `client_id`
- `claim_id`
- `claim_secret`

`client_kind` is not an authorization factor. A valid `client_id`, `claim_id`, and
`claim_secret` can move the claim between web, MCP, Discord, and future client kinds.
New claims always receive a server-generated `claim_id`; client-supplied claim IDs are
accepted only when validating an existing claim.

Private data includes room perspective, queued commands, MCP prompt/context, scene image
requests, command submission, and any character-private state. Admin endpoints remain
privileged separately.

External command endpoints must reject unclaimed characters. In-world controllers such
as LLM, scripted, and behavioral controllers act through the world actor rather than
through bearer-secret client endpoints.

Send `claim_secret` in a header, cookie, or separate MCP tool parameter. Never put it in a
query string, ECS component, persisted world file, or generic command payload object.

## Claim And Release

Claiming attaches `ClaimedComponent` to the current controller or transfers it to the new
client controller. A character with an active claim cannot be claimed by another client.
HTTP and MCP clients reclaim by presenting the matching `claim_id` and `claim_secret`.
Discord commands authenticate the same `client_id` through Discord's user identity; portable
handoff from Discord to HTTP/MCP still requires the bearer secret.

Controller release and claim release are different operations:

- Controller release transfers active control to a fallback controller and keeps the
  claim.
- Claim release removes `ClaimedComponent` and revokes the in-memory `claim_secret`.

Claims can move between any controller entities. Web, MCP, Discord, LLM, suspended,
scripted, behavioral, and future controllers are all controller entities for transfer
purposes. The claim system should not special-case controller kinds except when creating
built-in fallback controllers such as `suspend` or `llm`.

## Persistence Plan

v1 keeps claim secrets only in memory. A restart drops public claim components that no
longer have a process-local secret.

A future persistent implementation can replace the in-memory registry with another
backend, but it must preserve this boundary: ECS stores public claim metadata only, and
claim secrets remain outside persisted world snapshots.
