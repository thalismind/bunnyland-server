# Config wizard

The config wizard turns a verified local command into a repeatable `bunnyland.yml`. It can
also render the browser's `config.json`. Use it before writing a `systemd` unit or container
configuration by hand.

## Prerequisites

Complete [the first-server guide](running-a-server.md), stop that test server, and work from
the server repository. The Textual wizard needs the normal project environment; prompt mode
works in terminals where a full-screen interface is unavailable.

```bash
uv run bunnyland config-wizard
```

Alternatives:

```bash
uv run bunnyland config-wizard --cli
uv run bunnyland config-wizard --config bunnyland.yml --dry-run
```

Use `--non-interactive` to validate and rewrite an existing config without prompts:

```bash
uv run bunnyland config-wizard \
  --non-interactive \
  --config bunnyland.yml
```

## Work through the stages

The stage list starts with world setup, then moves through mechanics, integrations,
deployment, and access. Required fields are visible by default; **Advanced** reveals
lower-frequency settings. You can jump backward without losing current form values.

- **Apply** validates and writes the selected outputs.
- **Close** exits without applying changes.
- Each focusable `?` opens field-specific help.
- **Review** shows the resulting configuration or the next blocking validation error.

Choose a long-running world (`ticks: 0`) only after the local finite-tick test has passed.
Keep `server.api_host` at `127.0.0.1` for hosted deployments. Public access belongs at nginx,
not on the Uvicorn listener.

## Review outputs before using them

Render to temporary files first:

```bash
uv run bunnyland config-wizard \
  --config bunnyland.yml \
  --write-config /tmp/bunnyland.yml \
  --write-web-config /tmp/bunnyland.web.json \
  --dry-run
```

The server configuration is a typed YAML document with these top-level sections:
`server`, `world`, `plugins`, `addons`, `llm`, `discord`, `mcp`, `web`, `deployment`, and
`imagegen`. Unknown or misspelled fields are rejected. Start the server with:

```bash
uv run bunnyland serve --config bunnyland.yml
```

The generated web configuration points the browser at `/api/`. Preserve that same-origin
path when nginx is added later.

## Secret handling

Treat `bunnyland.yml` as a secret if the wizard places provider keys or a Discord token in
it. The writer sets mode `0600`, but you must also keep the file outside public web roots,
exclude it from Git and backups shared with untrusted people, and restrict its parent
directory.

For native service deployments, you can keep reusable credentials in root- or
service-owned files and expose their paths through these environment variables:

```text
OLLAMA_CLOUD_API_KEY_FILE=/etc/bunnyland/ollama.key
OPENROUTER_API_KEY_FILE=/etc/bunnyland/openrouter.key
DISCORD_TOKEN_FILE=/etc/bunnyland/discord.token
```

Do not use both a literal variable and its matching `_FILE` variable. Bunnyland rejects the
ambiguous credential source instead of guessing. Never put secret values in command-line
arguments, public `config.json`, URLs, screenshots, or world snapshots.

Authentication users and automation tokens are deliberately separate from the general
config: `server.auth_users_file` points at an Argon2 user inventory and `server.token_db`
points at the private SQLite token store. The next guide creates both.

## Plugin safety

The plugin stage imports only modules explicitly supplied with the wizard command. Already
loaded modules may be displayed, and unloaded candidates may be suggested, but the wizard
does not import suggestions automatically.

Preselect a trusted plugin by repeating `--plugin`:

```bash
uv run bunnyland config-wizard \
  --config bunnyland.yml \
  --plugin bunnyland.core_verbs \
  --plugin bunnyland.worldgen
```

External plugin modules execute Python in the server process. Install only packages whose
source and release provenance you trust.

## Validate after edits

After every manual edit:

```bash
uv run bunnyland config-wizard --config bunnyland.yml --dry-run
uv run bunnyland serve --config bunnyland.yml --ticks 1
```

The one-tick launch catches configuration that parses but cannot initialize its selected
plugins, providers, files, or ports. Do not run the second command against an active world's
save path; validate with a copy or a disposable world.

## Troubleshooting

### Textual cannot open

Use `--cli`. For unattended validation, use `--non-interactive --config bunnyland.yml`.

### The wizard refuses to save

Open **Review** and fix the reported field. Check absolute browser origins, numeric ports and
IDs, writable output directories, and required integration credentials.

### The server ignores a manual edit

Confirm that the service actually passes `--config` with the file you edited. If a CLI flag
or environment variable overrides the same field, remove the duplicate source and keep one
authoritative configuration path.

### The web client connects to the wrong server

Regenerate the web output and verify that `serverUrl` is `/api/`. Do not publish the private
server YAML as browser configuration.

[← Install and run your first server](running-a-server.md) ·
[Authentication, permissions, and moderation →](authentication-permissions-moderation.md)
