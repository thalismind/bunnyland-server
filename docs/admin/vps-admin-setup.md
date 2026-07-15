# VPS administration setup

> The standalone `scripts/vps-docker-setup` flow is retired. Hosted authentication requires
> the coordinated server, nginx, credential-file, token-database, and backup configuration in
> the `bunnyland-vps` Ansible playbook.

## Prepare credentials

Store Bunnyland users and the operator bearer token in encrypted inventory. User records use
Argon2 password hashes and explicit scopes:

```yaml
bunnyland_auth_users:
  - username: player1
    password_hash: "$argon2id$..."
    enabled: true
    scopes: [world:play]
bunnyland_operator_token: "blt_..."
```

Generate a password hash through stdin:

```bash
printf '%s\n' "$PASSWORD" | bunnyland auth hash-password --password-stdin
```

The playbook renders the user file and root-owned operator token with mode `0600`, mounts
both read-only, and persists `/data/auth-tokens.sqlite3`. Uvicorn accepts forwarded headers
only from the frontend's deterministic private address, and nginx overwrites the forwarded
client chain. Client IDs remain optional policy filters; they are not credentials and do
not authenticate a request.

## Validate and apply

From the `bunnyland-vps` checkout:

```bash
export ANSIBLE_VAULT_PASSWORD_FILE="$PWD/.ansible/vault-pass"
uv run ansible-playbook --syntax-check ansible/playbooks/vps.yml
uv run ansible-lint ansible/playbooks/vps.yml
uv run ansible-playbook --check --diff ansible/playbooks/vps.yml
uv run ansible-playbook ansible/playbooks/vps.yml
```

Verify the deployed bearer-token boundary with separately scoped tokens:

```bash
BUNNYLAND_DOMAIN=sandbox.example.com \
BUNNYLAND_PLAY_TOKEN=blt_... \
BUNNYLAND_OPERATOR_TOKEN=blt_... \
  ../bunnyland-server/scripts/vps-docker-verify
```

`BUNNYLAND_PLAYER_AUTH_REQUIRED` only controls frontend automatic connection and login
prompt behavior. It is not a server authorization switch; the server token store and route
scope checks enforce access.

## Backups and restore

When backups are enabled, configure an rclone destination whose remote type is `crypt`.
Plaintext remotes are rejected. Ordinary sync excludes `private/**` and live
`auth-tokens.sqlite3*` files; the backup job uploads a consistent SQLite snapshot separately.

For a clean-host restore, provision the rclone crypt configuration, restore ordinary data
and the encrypted token snapshot, then apply Ansible so vaulted inventory regenerates the
credential file and operator token. Confirm that a previously revoked token remains rejected
after restart.

If an older full-data backup ran, assume it contains credentials: rotate the operator token
and use a new encrypted destination for the next backup.

## Release and rollback

Do not deploy from historical Basic-auth results. Before cutover, require the exact server,
web, 3D/RL, aggregate Playwright, authenticated 40-WebSocket, MCP/Discord smoke,
backup/restore, and rollback gates documented in `bunnyland-vps/releases/`.

Rollback must restore the previous server and web images together while preserving the token
database. Re-run bearer-token verification after rollback; do not re-enable the retired
Basic-auth or admin-secret path.
