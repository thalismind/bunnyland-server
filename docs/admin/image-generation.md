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
COMFYUI_SERVER_URL=http://localhost:8188   # WHERE your ComfyUI server is
COMFYUI_USE_WEBSOCKET=1                     # watch progress over /ws (HTTP polling fallback)
COMFYUI_POLL_INTERVAL_SECONDS=1
COMFYUI_TIMEOUT_SECONDS=120
BUNNYLAND_MEDIA_DIR=/data/media             # where generated images are written
BUNNYLAND_IMAGE_WORKFLOWS=sdxl             # WHICH workflow family (model) to use for images
BUNNYLAND_IMAGE_PROMPT_STYLE=              # force "tag" or "natural" (blank = family default)
BUNNYLAND_IMAGE_TEMPLATES=/data/image-workflows.json  # optional per-template overrides
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

## Choosing a model family

A *workflow family* is a set of ComfyUI graphs (one per purpose: `portrait`, `entity`,
`sprite`, `event`) built around one base model. Pick the family with `BUNNYLAND_IMAGE_WORKFLOWS`
to match your GPU and quality target:

| Family (`BUNNYLAND_IMAGE_WORKFLOWS`) | Base model | Prompt style | VRAM | Notes |
|---|---|---|---|---|
| `anima` *(default)* | Anima (Qwen-CLIP + UNET) | tag / score | lowest | best for small GPUs |
| `sdxl` | SDXL / Illustrious / Pony | tag | low–mid | two-pass + latent upscale |
| `klein` | Flux 2 Klein 9B | natural language | mid–high | |
| `flux2dev` | Flux.2 Dev | natural language | highest | best quality; optional Turbo LoRA |

A family label may carry your own suffix — the base is the **first keyword** before the
first `-`. So `BUNNYLAND_IMAGE_WORKFLOWS=anima-my-server` still uses the `anima` base graphs;
the suffix is just a label for templates you override (below).

The enhancer formats prompts to the family's style (tag vs natural) automatically. To force
a style regardless of family, set `BUNNYLAND_IMAGE_PROMPT_STYLE=tag` or `natural`.

## Changing the model

Each family is a directory of JSON files shipped inside the package at
`bunnyland/imagegen/workflows/<family>/{portrait,entity,sprite,event}.json`. The simplest
customization is to keep a family but point it at a different checkpoint — copy the template
you want to change, edit the model field, and load it through `BUNNYLAND_IMAGE_TEMPLATES`
(a `{"templates": [...]}` file whose entries **shadow** the shipped defaults by `name`):

- **SDXL/Illustrious/Pony**: change `ckpt_name` in the `CheckpointLoaderSimple` node (`10`).
  Any SDXL-architecture checkpoint works with the same graph.
- **Anima / Klein / Flux.2 Dev**: change `unet_name` in the `UNETLoader` node (and, if you
  switch CLIP/VAE, `clip_name`/`vae_name`).

A template is a ComfyUI API-format graph plus a small map of where to inject the prompt,
seed, and size. Values are filled two ways: literal tokens inside a string field
(`%PROMPT%`, `%NEGATIVE%`), and numeric-safe `slots` that set a node field by path
(`%SEED%`, `%WIDTH%`, `%HEIGHT%`). Example (SDXL):

```json
{
  "templates": [
    {
      "name": "portrait", "purpose": "portrait", "prompt_style": "tag",
      "width": 832, "height": 1216, "output_node_id": "84",
      "graph": { "10": {"inputs": {"ckpt_name": "your-model.safetensors"}, "...": "..." } },
      "slots": [
        {"node_id": "87", "field_path": ["inputs", "noise_seed"], "token": "%SEED%"},
        {"node_id": "30", "field_path": ["inputs", "width"], "token": "%WIDTH%"},
        {"node_id": "30", "field_path": ["inputs", "height"], "token": "%HEIGHT%"}
      ]
    }
  ]
}
```

To export a graph from ComfyUI, enable **Settings → Enable dev mode options** and use
**Save (API Format)** — that JSON goes under `graph`. Keep one `SaveImage` node and point
`output_node_id` at it.

## Adding LoRAs

A LoRA is an extra node inserted between the model loader and the samplers, with the model
(and, for SDXL, the CLIP) rewired through it:

- **SDXL** — add a `LoraLoader` that takes `model` and `clip` from the checkpoint (`10`),
  then point the samplers' `model` and the text-encoders' `clip` at the LoRA node instead:

  ```json
  "11": {"class_type": "LoraLoader",
         "inputs": {"lora_name": "my_style.safetensors", "strength_model": 0.8,
                    "strength_clip": 0.8, "model": ["10", 0], "clip": ["10", 1]}}
  ```
  Then change `KSampler` `model` inputs to `["11", 0]` and `CLIPTextEncode` `clip` inputs to
  `["11", 1]`. Stack multiple LoRAs by chaining `LoraLoader` nodes.

- **Flux / UNET families** — use `LoraLoaderModelOnly` (model only). The shipped `flux2dev`
  family already includes a Turbo LoRA wired through a switch: node `98:101`
  (`LoraLoaderModelOnly`) is toggled by the `Enable Turbo LoRA` boolean (`98:104`). Set its
  `value` to `true` (and the steps switch picks the 8-step turbo schedule) to enable it, or
  add your own `LoraLoaderModelOnly` before the guider.

## Admin controls

With a bearer token scoped for `world:admin`:

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
