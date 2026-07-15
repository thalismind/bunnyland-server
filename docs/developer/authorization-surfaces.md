# Authorization Surfaces

This document defines the conventions for authentication and authorization across
Bunnyland transports. OpenAPI is the canonical reference for concrete HTTP operations,
request bodies, and response schemas; contributor documentation should explain policy
and extension patterns rather than reproduce that catalog.

## Identity and scopes

Interactive users are individually provisioned with Argon2 password hashes. There is no
shared player password or shared administrator password. A successful login issues an
opaque bearer token for that user, and the private token store records only its digest,
subject, scopes, rotation state, expiry, and revocation state.

The authorization vocabulary is deliberately small:

- `world:play` permits player-facing world interaction.
- `world:admin` permits administrative world operation and implies `world:play`.

Use `/play` for the player-facing HTTP zone because it names the capability and matches
`world:play`. Do not introduce parallel role names such as `/player`, `player:*`, or
transport-specific equivalents.

Character claims are an additional object-level authorization check. A valid play scope
does not grant access to another character's private state. See
[Security Principals And Claims](security-principals.md) for the claim model.

## One policy across transports

REST, WebSocket, and MCP must use the same scope constants, scope normalization, token
validation, client-ID admission rules, and revocation store. They differ only where the
transport requires a different authentication ceremony.

| Surface | Coarse authorization | Fine authorization |
| --- | --- | --- |
| HTTP | One prefix classifier and middleware enforce the zone scope. A startup audit rejects unzoned routes. | Handlers enforce object-level rules such as character claims. |
| WebSocket | The same prefix classifier selects the required scope; the first frame completes bearer authentication. | The shared handshake and stream logic enforce source conflicts, client ID, claims, origin, and continuing revocation. |
| MCP | The HTTP transport requires an authenticated play-capable principal. | Every tool, prompt, and resource declares scopes and a central wrapper enforces them. |

An absent principal, missing policy declaration, unknown scope, conflicting bearer
sources, or revoked credential fails closed. Names and suffixes such as `_admin` are
descriptive only and never confer access.

## HTTP zones

Application routes belong to exactly one zone: public, session lifecycle, play, admin,
or MCP transport. The zone prefix is the coarse authorization boundary. Unknown routes
return `404`; registering a core or addon route outside a known zone is a startup error.

The public zone is only for intentionally anonymous, non-sensitive resources. Health is
readiness-only. Operational status and capability metadata require play scope. The admin
zone is authoritative for administrative HTTP operations, so individual handlers should
not duplicate its scope check.

Browser clients are same-origin. Cross-origin server overrides, socket targets, media
URLs, and configuration values are rejected. Explicit CORS configuration is a secondary
browser defense, not an alternative to bearer authentication and TLS. Non-browser
clients may connect remotely only over HTTPS, except for loopback development. MCP DNS
rebinding protection derives its allowed Host and Origin values from that same validated
origin list; terminal MCP clients may omit Origin but do not bypass Host validation.

## Addon conventions

HTTP addons contribute routes through a typed public, play, or admin router. Registrars
receive only the router for the selected zone and define local paths beneath it. Absolute
paths, cross-zone paths, and direct registration on the FastAPI application are invalid.
Mixed addons provide separate contributions for each zone.

MCP contributions are independent of HTTP zone contributions. Every contributed tool,
prompt, and resource must declare its required scope set when it is registered. The MCP
wrapper reads the authenticated request principal and applies the declared policy. It
must reject execution when request context or policy is absent.

## Review and test contract

Changes to a protected capability should be tested on every transport that exposes it.
The expected matrix is consistent: anonymous callers receive `401`; play credentials can
use play capabilities but receive `403` for admin capabilities; admin credentials can use
both. WebSocket tests additionally cover first-frame source conflicts, origin, client ID,
claims, and mid-stream revocation. MCP tests use the real streamable HTTP transport and
cover missing request context and undeclared addon policy.

The generated route matrix is the regression check that every HTTP and WebSocket route
has exactly one declared surface. OpenAPI remains the endpoint and payload reference.
