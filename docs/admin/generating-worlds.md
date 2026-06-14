# Generating worlds

World generation is how you start a fresh Bunnyland setting. It can be a quiet private game,
a server-admin reset, or a deterministic demo for testing one sim package.

## Pick a generator

Enabled plugins contribute named generators. The built-in worldgen plugin provides:

| Generator | Use it for |
|-----------|------------|
| `empty` | A blank administrative reset with only the world clock. Not playable until patched or regenerated. |
| `clue-snack-demo` | A legally distinct comic mystery with snacks, a talking hound, and a fake haunting. |
| `dive-scheme-demo` | A legally distinct dysfunctional tavern sitcom full of bad schemes. |
| `gothic-count-demo` | A legally distinct gothic night-host castle with papers, secrets, and hunger. |
| `oneshot` | Small worlds generated in one proposal. Fastest and simplest. |
| `recursive` | Larger room graphs grown room-by-room with `--max-rooms`. Better for coherent explorable spaces. |
| `star-opera-demo` | A legally distinct star-opera rebellion at a desert port and rusty freighter. |

Implemented sim packages also provide deterministic demo worlds, such as `lifesim-demo`,
`gardensim-demo`, `daggersim-demo`, `voidsim-demo`, `nukesim-demo`, and `dinosim-demo`.
See [world creation](../developer/world-creation.md) for the full list.

## Generate from the web bundle

The web bundle's generator page is the preferred admin workflow for a running server because it
starts generation asynchronously and shows the world changing as entities appear.

Open `world-generator.html` from the Bunnyland web bundle. On the deployed frontend, the
server field is usually same-origin `/api`; locally it is commonly `http://127.0.0.1:8765`.

The page:

- lists generators from `GET /admin/world/generators`;
- accepts a seed/prompt and room budget;
- requires an explicit reset checkbox before replacing the live world;
- can request a save after generation when the server was started with `--save`;
- starts generation as a background job, then watches status and polls snapshots;
- highlights entity ids that were not present in the previous snapshot.

The reset endpoint clears the current world immediately and returns a job id. The
generator then adds entities while the page watches `/world/snapshot`, websocket domain
events, and `GET /admin/world/generation`. Completion is announced with
`WorldGenerationCompletedEvent`; failures are announced with `WorldGenerationFailedEvent`.

## Generate from the CLI at startup

For a private single-player-style world:

```bash
uv run bunnyland serve --generator recursive --seed "a flooded clockwork cathedral" \
  --max-rooms 8 --ticks 0 \
  --api-host 127.0.0.1 --api-port 8765 \
  --save worlds/cathedral.json --autosave-every 20
```

For a deterministic package demo:

```bash
uv run bunnyland serve --generator voidsim-demo --ticks 0 \
  --api-host 127.0.0.1 --api-port 8765 \
  --save worlds/void-demo.json --autosave-every 20
```

For a blank admin reset:

```bash
uv run bunnyland serve --generator empty --ticks 0 \
  --api-host 127.0.0.1 --api-port 8765 \
  --save worlds/blank.json
```

For LLM-generated worlds, add `--llm` and provider credentials as described in
[running a server](running-a-server.md#connecting-an-llm).

## Generate through the admin API

Protect `/admin/*` at the reverse proxy. These endpoints mutate or expose admin-only
control over the world.

List available generators:

```bash
curl -fsS -u editor:YOUR_PASSWORD \
  https://sandbox.example.com/api/admin/world/generators
```

Start replacing the running world:

```bash
curl -fsS -u editor:YOUR_PASSWORD \
  -H 'Content-Type: application/json' \
  -X POST https://sandbox.example.com/api/admin/world/generate \
  -d '{
    "seed": "a neon train station under winter rain",
    "generator": "recursive",
    "max_rooms": 8,
    "confirm_reset": true,
    "save": true
  }'
```

`confirm_reset` must be `true`. The endpoint clears the current ECS world and volatile
command queues, updates world metadata, starts an async generation job, broadcasts a fresh
snapshot on the websocket, and returns immediately. While the job runs, poll:

```bash
curl -fsS -u editor:YOUR_PASSWORD \
  https://sandbox.example.com/api/admin/world/generation
```

The status endpoint reports `running`, `succeeded`, `failed`, or `idle`. If `save` is true
and the server has a configured save path, the completed generated world is saved before
the status flips to `succeeded`.

Generated rooms, characters, items, events, and manual admin edits are applied as
validated world patches. The server preflights the whole patch before mutating ECS state,
so an invalid generated proposal fails without leaving partial rooms, entities, components,
or edges behind.

## After generation

Check the generated world before inviting players:

1. Open the inspector and confirm rooms, exits, food/water, and claimable characters exist.
2. Use the world editor to patch small issues rather than regenerating repeatedly.
3. Save the world once it is ready.
4. Record the seed, generator, max room budget, enabled plugins, and provider/model choices
   in server notes so the world is reproducible enough to reason about later.
