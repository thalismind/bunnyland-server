# Image generation (ComfyUI)

Bunnyland can illustrate a world by generating pictures with a [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
server: character portraits, single-object renders, toon sprites, and on-request scene
images for world events. The simulation never blocks on this — generation runs on a
background worker, one job at a time — and the engine only ever stores a small URL
reference, never image bytes.

Image generation is **off** until you point Bunnyland at a ComfyUI server.

## Turning it on

Set `COMFYUI_SERVER_URL` (the rest are optional):

```bash
COMFYUI_SERVER_URL=http://localhost:8188   # your ComfyUI server
COMFYUI_USE_WEBSOCKET=1                     # watch progress over /ws (HTTP polling fallback)
COMFYUI_POLL_INTERVAL_SECONDS=1
COMFYUI_TIMEOUT_SECONDS=120
BUNNYLAND_MEDIA_DIR=/data/media             # where generated images are written
BUNNYLAND_IMAGE_TEMPLATES=/data/image-workflows.json  # optional player/admin workflows
BUNNYLAND_IMAGE_ENHANCER=stub              # "stub" (offline) or "llm" (uses OLLAMA_*)
BUNNYLAND_IMAGE_BACKFILL_SECONDS=5         # cadence of the portrait/sprite backfill
```

The prompt **enhancer** turns an entity or event into a model-ready prompt. The default
`stub` enhancer is deterministic and needs no network; set `BUNNYLAND_IMAGE_ENHANCER=llm`
to have an Ollama model write richer prompts (it reuses your `OLLAMA_HOST` /
`OLLAMA_CLOUD_API_KEY`). Plugins can register additional enhancers by name.

> **Discord avatars require a public URL.** Posting a character's portrait as a Discord
> avatar needs an absolute, reachable image URL, so set `BUNNYLAND_PUBLIC_BASE_URL`
> (e.g. `https://sandbox.example.com`). Everything else — the web client and event-image
> uploads — works without it.

The `imagegen` extra provides the dependencies (`httpx`, `websockets`, `Pillow`):

```bash
uv sync --extra imagegen
```

## What gets generated, and when

- **Portraits** — every character always gets a portrait. A throttled backfill loop fills
  in any character that is missing one, one request at a time, so enabling image generation
  on an existing world gradually illustrates everyone without flooding ComfyUI.
- **Toon sprites** — when the `toonsim` pack is enabled, characters also get a transparent
  sprite (the alpha background is removed automatically).
- **Event images** — generated only when a player requests one (see the player guide). The
  first request for an event is generated and then reused for everyone; admins can force a
  regenerate.

Generated images **persist**: the reference is saved with the world, and nothing is
regenerated once an entity or event has an image.

## Workflows

A workflow is a ComfyUI graph (the API-format JSON) plus a small map of where to inject the
prompt, seed, and dimensions. Bunnyland ships a default workflow for each purpose
(`portrait`, `entity`, `sprite`, `event`). To use your own models or graphs, provide a
templates file at `BUNNYLAND_IMAGE_TEMPLATES`:

```json
{
  "templates": [
    {
      "name": "portrait",
      "purpose": "portrait",
      "prompt_style": "natural",
      "width": 832,
      "height": 1216,
      "output_node_id": "9",
      "graph": { "...": "your ComfyUI API graph..." },
      "slots": [
        {"node_id": "6", "field_path": ["inputs", "text"], "token": "%PROMPT%"},
        {"node_id": "7", "field_path": ["inputs", "text"], "token": "%NEGATIVE%"},
        {"node_id": "3", "field_path": ["inputs", "seed"], "token": "%SEED%"},
        {"node_id": "5", "field_path": ["inputs", "width"], "token": "%WIDTH%"},
        {"node_id": "5", "field_path": ["inputs", "height"], "token": "%HEIGHT%"}
      ]
    }
  ]
}
```

- `prompt_style` is `tag` (comma-separated WD14/danbooru tags, for SDXL-era models) or
  `natural` (a sentence, for Flux/Qwen-era models). The enhancer formats its output to
  match, using a few catalogued examples so the format stays correct.
- A `slot` writes a value into one node field by path (kept numeric-safe for seed/size).
  You can also embed the literal tokens (`%PROMPT%`, `%NEGATIVE%`, `%SEED%`, `%WIDTH%`,
  `%HEIGHT%`) directly in a node's text field.
- A user template **shadows** the shipped default of the same name; only your templates are
  written back to the file.

To export a workflow from ComfyUI, enable **Settings → Enable dev mode options** and use
**Save (API Format)**; that JSON is what goes under `graph`.

## Admin controls

With an admin token (`X-Bunnyland-Admin-Token`):

```bash
# Generate (or regenerate) an image for any entity or history record:
POST /admin/world/generate-image
     {"entity_id": "...", "purpose": "portrait|entity|sprite|event",
      "template": "", "alpha": false, "force": false}

# Check a job:
GET  /admin/world/generate-image/{job_id}
```

Generated files are served read-only at `GET /media/{kind}/{name}`.

## Coming soon

Event and interaction **videos** are planned; the data model already reserves space for
them, but only images are generated today.
