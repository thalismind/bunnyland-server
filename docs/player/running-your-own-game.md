# Running your own game

This guide is for semi-single-player Bunnyland: you run a private server, claim one
character, and optionally let LLM-controlled characters keep acting around you. It is still
the normal server simulation, just scoped to your own world instead of a shared community
server.

## Start offline first

Run a short deterministic world to verify the install:

```bash
uv sync --extra server
uv run bunnyland serve --ticks 5 --api-host 127.0.0.1 --api-port 8765
```

Without `--llm`, generated LLM characters wait instead of thinking. This is useful for
learning the UI, testing mechanics, and playing a quiet solo session with explicit commands.

Open the web client, point it at `http://127.0.0.1:8765`, and use:

- `index.html` to inspect the live world;
- `world-editor.html` to patch, save, or inspect ECS details;
- `world-generator.html` to replace the current world with a new generated one.

## Keep the world running

For an ongoing private game, run forever and save the world:

```bash
mkdir -p worlds
uv run bunnyland serve --ticks 0 \
  --api-host 127.0.0.1 --api-port 8765 \
  --generator recursive --max-rooms 8 \
  --save worlds/private.json --autosave-every 20
```

Reload it later with:

```bash
uv run bunnyland serve --load worlds/private.json --ticks 0 \
  --api-host 127.0.0.1 --api-port 8765 \
  --save worlds/private.json --autosave-every 20
```

## Add LLM characters

Install the LLM extra and set a provider key:

```bash
uv sync --extra server --extra llm
echo 'OLLAMA_CLOUD_API_KEY=sk-...' > .env
uv run bunnyland serve --llm --generator recursive --max-rooms 8 --ticks 0 \
  --api-host 127.0.0.1 --api-port 8765 \
  --save worlds/private.json --autosave-every 20
```

With `--llm`, world generation can use a stronger worldgen model while characters use a
cheaper controller model. See [running a server](../admin/running-a-server.md#connecting-an-llm)
for Ollama and OpenRouter options.

## Claim a character

Generated worlds include at least one suspended, claimable character. In a Discord setup,
claim through the Discord bot. In a local/private setup, use the web inspector to identify
the character and controller ids, then submit normal commands through the API or use the
Discord test harness during development.

The important rule is that your character and LLM characters use the same world verbs:
move, look, take, eat, say, rest, and the sim-package verbs enabled for that world. If a
command would be illegal for you, it is illegal for the LLM too.

## Generate a new private world

Use [generating worlds](../admin/generating-worlds.md) when you want a fresh start. The web
generator page can list enabled generators, accept a seed/prompt, clear the current world,
and highlight the entities that appear in the replacement snapshot.
