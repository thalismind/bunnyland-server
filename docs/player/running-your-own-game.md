# Running your own game

This is a quick start for semi-single-player Bunnyland: run a private server, get a client
connected, and explore your own world instead of joining a shared community server. Start
with the demo world; once it works, choose a client and generate a custom world. To learn
any one client in depth, branch out to the [client guides](clients/README.md) this page
points to.

## Start the demo world

From a `bunnyland-server` checkout, run one command:

```bash
uv run --extra server bunnyland serve --generator apartment-demo --ticks 0 \
  --api-host 127.0.0.1 --api-port 8765
```

That starts a deterministic offline demo world on your machine. It does not require an LLM
key, and characters will wait instead of thinking on their own.

Open the web client:

```text
https://bunnyland.dev/?server=http://127.0.0.1:8765
```

The root page is the welcome/client chooser; open the **Inspector** for the entities list
and event feed used below. If you have the web repo checked out locally,
`bunnyland-web/inspector.html` works too — use its `Server` field to enter
`http://127.0.0.1:8765` manually.

Try a short first session:

1. Open the Inspector and connect live.
2. Pick a character or room in the entities list.
3. Look at the character's current room, inventory, needs, and nearby exits.
4. Watch the event feed while the server ticks.

The demo is useful because it proves the server, API, web client, and basic game loop work
before you spend time tuning a custom world. You do not need to claim a character for this
first check.

## Choose how to play

The Inspector above is a developer view of the whole world. To actually *play*, claim a
character in a player client pointed at your server (`http://127.0.0.1:8765`). Each client
is a different classic style, and they all drive the same server-validated verbs — a world
you play in one is the same world in any other:

- **Bunnyland Toon** — the web client. A room-at-a-time view with sprites, doors pinned to
  the walls, and click-to-move, in the spirit of a Flash-era browser game. Open it from the
  welcome page and connect, or pass `?server=`. See [the Toon client](toonsim.md).
- **Web REPL** — a browser command line for typed play without installing the terminal
  client. It claims a character through the same web controller path as Toon. See
  [the Web REPL](clients/web-repl.md).
- **Terminal TUI** — a full-screen panel client with a room list, action menu, action
  search, and queued actions, like a modern terminal MUD client. See
  [the TUI](clients/tui.md).
- **Terminal REPL** — a single command line with tab completion and clickable names, like a
  classic text MUD or interactive fiction. See [the REPL](clients/repl.md).
- **Discord** — play by typing commands in a channel when the server runs the Discord bot.

Browse [the client guides](clients/README.md) for launch commands, controls, and per-client
tips, then pick whichever surface fits how you like to play.

## Generate your own world

Once the demo is running, open the generator:

```text
https://bunnyland.dev/world-generator.html?server=http://127.0.0.1:8765
```

For a first custom world, choose:

- generator: `recursive`;
- seed: a short setting prompt, like `a flooded clockwork cathedral`;
- max rooms: `6`;
- reset: checked.

Click generate and watch the page stream the replacement world. When it finishes, return to
the main web client with the same server URL and start exploring the new setting.

Use [generating worlds](../admin/generating-worlds.md) when you want deeper admin details,
API examples, or a larger room budget.

## Keep a world

When you want the world to survive server restarts, stop the demo and restart with a save
file:

```bash
uv run --extra server bunnyland serve --generator apartment-demo --ticks 0 \
  --api-host 127.0.0.1 --api-port 8765 \
  --save private-world.json --autosave-every 20
```

After you generate a custom world from the browser, check `Save after generation` so the
replacement world is written to `private-world.json`.

Reload the saved world later:

```bash
uv run --extra server bunnyland serve --load private-world.json --ticks 0 \
  --api-host 127.0.0.1 --api-port 8765 \
  --save private-world.json --autosave-every 20
```

Admins can optionally run a bounded offline-life catch-up after loading a save. When that
is enabled, returning players may find that background characters made limited, ordinary
world changes while the server was down.

## Add LLM characters later

LLM characters are optional. Add them only after the offline loop works:

```bash
uv run --extra server --extra llm bunnyland serve --llm \
  --generator recursive --seed "a haunted greenhouse after midnight" --ticks 0 \
  --api-host 127.0.0.1 --api-port 8765 \
  --save private-world.json --autosave-every 20
```

Set `OLLAMA_CLOUD_API_KEY` or `OPENROUTER_API_KEY` in your environment first. With `--llm`,
world generation can use a stronger worldgen model while characters use a cheaper
controller model. See
[running a server](https://github.com/thalismind/bunnyland-server/blob/main/docs/admin/running-a-server.md#connecting-an-llm)
for provider options.
