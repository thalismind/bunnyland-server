# Running your own game

This guide is for semi-single-player Bunnyland: you run a private server, open the web
client, and explore your own world instead of joining a shared community server. Start with
the demo world first; once that works, generate a custom world from the browser.

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

If you have the web repo checked out locally, opening `bunnyland-web/index.html` also works.
Use the `Server` field if you need to enter `http://127.0.0.1:8765` manually.

Try a short first session:

1. Open the world view and connect live.
2. Pick a character or room in the entities list.
3. Look at the character's current room, inventory, needs, and nearby exits.
4. Watch the event feed while the server ticks.

The demo is useful because it proves the server, API, web client, and basic game loop work
before you spend time tuning a custom world. You do not need to claim a character for this
first check.

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
