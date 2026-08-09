# Authentication, permissions, and moderation

Bunnyland uses one authorization vocabulary across HTTP, WebSocket, Discord, and MCP. Human
logins come from a private YAML inventory. Automation uses opaque bearer tokens stored as
digests in SQLite. Character claim secrets are a separate, short-lived proof of control and
must never be treated as account credentials.

## Prerequisites

Complete the [config wizard](config-wizard.md). Decide which people are players and which
people are operators. Use separate accounts even on a small community server.

Create private directories:

```bash
install -d -m 0700 data/auth
```

On a multi-user host, make these directories owned by the dedicated Bunnyland service
account rather than your interactive login.

## Create human users

Generate an Argon2 hash from a protected prompt:

```bash
uv run bunnyland auth hash-password
```

Put the hash, not the password, in `data/auth/users.yml`:

```yaml
users:
  - username: player
    password_hash: '$argon2id$...'
    enabled: true
    scopes: [world:play]
  - username: operator
    password_hash: '$argon2id$...'
    enabled: true
    scopes: [world:admin]
```

Then restrict the file:

```bash
chmod 0600 data/auth/users.yml
```

`world:play` permits normal play and implies the narrower character profile/chat scopes.
`world:admin` permits privileged projections and operations and implies `world:play`. Avoid
giving both entries to an admin; `world:admin` already includes play access.

Start with the inventory and token database configured:

```bash
uv run bunnyland serve --config bunnyland.yml \
  --auth-users-file data/auth/users.yml \
  --token-db data/auth/tokens.sqlite3
```

The server reloads a valid user inventory while running. A malformed replacement is rejected
without silently accepting partial users. Keep the last valid file available for rollback.

## Provision automation tokens

Use bearer tokens for MCP clients and other non-browser automation:

```bash
uv run bunnyland auth provision-token \
  --db data/auth/tokens.sqlite3 \
  --subject local-agent \
  --scope world:play \
  --expires-days 90
```

The secret is printed once. Store it immediately in the client's protected credential store.
Do not put it in a world file, MCP arguments, a repository, or shell history.

Inspect metadata and rotate manually:

```bash
uv run bunnyland auth list-tokens --db data/auth/tokens.sqlite3
uv run bunnyland auth replace-token \
  --db data/auth/tokens.sqlite3 \
  --token-id TOKEN_ID
uv run bunnyland auth revoke \
  --db data/auth/tokens.sqlite3 \
  --token-id TOKEN_ID
```

Update the consumer with a replacement before discarding the one-time secret. Revoke the old
token after verifying the replacement. Use `--subject` with `revoke` only when you intend to
invalidate every token for that automation subject.

## Optional client-ID allowlists

`--player-client-id` and `--admin-client-id` (or the corresponding config fields) can restrict
which declared client IDs a scope may use. They are useful defense in depth, but
`X-Bunnyland-Client-Id` is caller-supplied metadata, not identity. A valid password session or
bearer token remains required.

## Moderate without crossing trust boundaries

The web moderation tool and Discord `!mod` commands operate on Bunnyland identities and
sessions. They do not ban someone from a Discord guild or operating system.

- **Kick** releases current claims, clears queued work, revokes active web sessions, and
  permits immediate sign-in.
- **Suspend** applies a finite UTC wall-clock restriction.
- **Ban** applies a restriction without an expiration.
- **Lift** removes a suspension or ban but does not restore sessions or claims.

Every action requires a reason and creates an append-only audit entry. Grant moderation only
through `world:admin` or the explicit Discord moderator user/role allowlists described in the
[Discord guide](discord-bot.md).

If the server cannot start, an operator can lift a known restriction offline:

```bash
uv run bunnyland moderation lift --help
```

Read the installed help before supplying a target; it is the authoritative argument contract
for the running version.

## Secret and file rules

Keep `users.yml`, `tokens.sqlite3`, provider keys, Discord tokens, backup encryption keys, and
TLS private keys outside the repository and web root. Use mode `0600` for files and `0700`
for parent directories. Back up the token database encrypted; never export plaintext bearer
tokens because Bunnyland does not store them.

Do not log `Authorization`, cookies, passwords, claim secrets, or first-frame WebSocket auth
payloads. A reverse proxy should forward these values, not print or replace them.

## Troubleshooting

### Login returns 401

Check the username, password, `enabled` flag, YAML readability, and server logs for a rejected
inventory reload. Regenerate an Argon2 hash rather than storing plaintext.

### A valid user receives 403

The identity is authenticated but lacks the required scope. Give players `world:play`; reserve
`world:admin` for operators. Restarting does not turn a play token into an admin token.

### A bearer token stops working

Use `list-tokens` to inspect expiry and revocation metadata. Provision or replace a token; do
not attempt to recover its original secret from SQLite.

### Moderation appears to affect the wrong service

Confirm the target namespace. Discord, web, and generic client identities are separate unless
your community has an explicit external account-linking process.

[← Config wizard](config-wizard.md) ·
[Hosting the web client securely →](hosting-web-client.md)
