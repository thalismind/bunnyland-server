# Install and run your first server

This first run stays on your workstation and binds the API to loopback. It proves Python,
dependencies, world generation, the game loop, saving, and the health endpoint before any
public networking is involved.

## Prerequisites

- Python 3.12, 3.13, or 3.14
- `git`
- [`uv`](https://docs.astral.sh/uv/)
- a terminal on Linux, macOS, or Windows

No provider key, Discord token, domain, container runtime, or root access is needed.

## Install from source

Clone the server and create its locked environment:

```bash
git clone https://github.com/thalismind/bunnyland-server.git
cd bunnyland-server
uv sync --locked --extra server
```

`uv sync` is an installation step for people setting up the project. Once the environment is
created, normal starts use `uv run` and do not resynchronize dependencies.

## Prove the offline game loop

Run five deterministic ticks without an API or paid model:

```bash
uv run bunnyland serve --ticks 5
```

The log should list loaded plugins, generate a small world, advance five ticks, and exit
normally. Offline characters wait, but passive mechanics still advance. This is the smallest
useful installation check.

If the command cannot import `bunnyland`, confirm that you are in the repository root and
that the preceding `uv sync --locked --extra server` completed successfully.

## Start a loopback API and save the world

Create a private data directory, then run until interrupted:

```bash
mkdir -p data/worlds
uv run bunnyland serve \
  --generator lifesim-demo \
  --ticks 0 \
  --api-host 127.0.0.1 \
  --api-port 8765 \
  --save data/worlds/main.json \
  --autosave-every 20
```

In another terminal, check the anonymous readiness endpoint:

```bash
curl -i http://127.0.0.1:8765/v1/public/health
```

Expected result: HTTP `204 No Content`. A successful empty response is normal. Confirm that
the server is not listening on a public address; `127.0.0.1:8765` is intentional.

Stop with `Ctrl+C`. Bunnyland writes `data/worlds/main.json` on clean shutdown. Resume the
same world with:

```bash
uv run bunnyland serve \
  --load data/worlds/main.json \
  --save data/worlds/main.json \
  --ticks 0 \
  --api-host 127.0.0.1 \
  --api-port 8765
```

`--load` skips generation. Keep `--save` as well so later changes are persisted. Add
`--load-paused` when an operator needs to inspect a restored world before ticks resume.

## Inspect the command surface

The CLI is the source of truth for installed flags:

```bash
uv run bunnyland --help
uv run bunnyland serve --help
```

Do not copy provider, Discord, MCP, authentication, or public-hosting flags into this first
run. The following guides add each boundary separately so failures remain attributable.

## Troubleshooting

### Port 8765 is already in use

Stop the old process or choose another loopback port with `--api-port`. Update every local
client URL to match.

### The health request is refused

Keep the server terminal open and check its traceback. Verify that `--api-port 8765` was
present and that the log did not stop after a finite number of ticks.

### The save file does not appear

Use a writable directory, retain both `--save` and `--autosave-every`, and stop the process
cleanly. A forced process kill can occur between autosaves; that is why production also uses
external backups.

### A saved world will not load after an upgrade

Do not overwrite it. Run `uv run bunnyland migrate-world source.json migrated.json` to write
a separate migrated copy, then test the copy. The source file is never modified by that
command.

[← Server setup overview](server-setup.md) · [Config wizard →](config-wizard.md)
