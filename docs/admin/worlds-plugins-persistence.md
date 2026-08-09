# Worlds, plugins, persistence, and snapshots

A public Bunnyland world is more than one JSON file. Its consistent state can include the
world snapshot, automation token database, persistent memory, controller definitions, and
generated media. Choose those paths and plugin surfaces before inviting players.

## Prerequisites

Complete the [secure web-hosting guide](hosting-web-client.md). Make a copy of every existing
world before changing generators, plugins, or schema versions.

## Create or select a world

Built-in demo generators are the simplest production seed because their mechanics are known:

```bash
uv run bunnyland serve \
  --generator lifesim-demo \
  --ticks 0 \
  --api-host 127.0.0.1 \
  --api-port 8765 \
  --save data/worlds/main.json \
  --autosave-every 20
```

For generated worlds, choose `oneshot` or `recursive`, give a specific seed, and cap recursive
growth with `--max-rooms`. LLM generation is added in the next guide; first prove the same
persistence paths with a deterministic world.

## Choose plugins deliberately

Without `--plugin`, Bunnyland loads built-ins marked `default_enabled`. A repeated explicit
plugin list replaces that default selection:

```bash
uv run bunnyland serve \
  --plugin bunnyland.core_verbs \
  --plugin bunnyland.worldgen \
  --plugin bunnyland.lifesim \
  --plugin bunnyland.memory \
  --ticks 1
```

Use `--extra-plugin` to add one plugin without replacing the normal set. This is the right
shape for optional operational metrics:

```bash
uv run bunnyland serve --extra-plugin bunnyland.world_health --ticks 1
```

External plugin wheels execute inside the server process and can read its state and
credentials. Install only trusted releases. Dependencies must be present at process start;
do not hot-add an unknown package to an active community world.

Starter packs (`peaceful`, `fantastic`, and `futuristic`) are named plugin presets. They are
convenient for new worlds but do not replace reviewing the enabled mechanics:

```bash
uv run bunnyland serve --starter-pack peaceful --ticks 1
```

## Configure durable state

For a long-running native service, use explicit paths:

```text
/var/lib/bunnyland/worlds/main.json
/var/lib/bunnyland/tokens.sqlite3
/var/lib/bunnyland/memory/
/var/lib/bunnyland/controllers.json
/var/lib/bunnyland/media/
```

Example launch fields:

```bash
uv run bunnyland serve \
  --load /var/lib/bunnyland/worlds/main.json \
  --save /var/lib/bunnyland/worlds/main.json \
  --autosave-every 20 \
  --memory-backend chroma \
  --memory-path /var/lib/bunnyland/memory \
  --controller-definitions /var/lib/bunnyland/controllers.json \
  --token-db /var/lib/bunnyland/tokens.sqlite3 \
  --ticks 0
```

Use `--memory-backend json` with a JSON file when you want a simpler portable persistent
memory store. `in-memory` is suitable for demos but is lost at restart.

Autosave frequency is measured in ticks. Choose it with the tick interval and acceptable
loss window in mind. Autosave is not a backup: filesystem loss, operator error, or corrupted
new state can affect both the working file and recent autosaves.

## Take snapshots safely

For the clearest consistency point:

1. Put the service in a maintenance window or start a restored copy with `--load-paused`.
2. Stop Bunnyland cleanly so the final `--save` completes.
3. Copy the world, token database, memory store, controller definitions, and media manifest as
   one set.
4. Hash the copied files and encrypt the archive.
5. Restart and verify the public health endpoint.

If your storage platform supports atomic volume snapshots, quiesce application writes first
and snapshot all state volumes together. Copying a live SQLite or Chroma directory file by
file is not a consistency guarantee.

## Migrate without overwriting the source

When an upgraded server reports an older world schema:

```bash
uv run bunnyland migrate-world \
  backups/world-before-upgrade.json \
  restore/world-migrated.json
```

The command writes a destination and never modifies the source. Start the migrated copy on a
loopback test server, inspect it, run representative actions, save, restart, and inspect again
before replacing the production path.

## Troubleshooting

### A plugin ID is unknown

Check spelling and installation with `uv run bunnyland serve --help` and the startup plugin
list. External packages must expose the `bunnyland.plugins` entry point in the same installed
environment as the server.

### The service starts a new world instead of resuming

Confirm the active config contains `world.load`, or the service has `--load`, and that the
service account can read the exact path. Keep `--save` pointed at the intended durable file.

### Memory disappears after restart

`in-memory` is intentionally ephemeral. Select `json` or `chroma`, provide `--memory-path`,
and include that path in the backup set.

### A snapshot loads but behavior changed

Compare enabled plugins, their versions/config, controller definitions, and server version.
The world file alone does not reproduce an installation with a different mechanic surface.

[← Hosting the web client securely](hosting-web-client.md) ·
[LLM providers and character controllers →](llm-providers-controllers.md)
