# Image and video generation

Bunnyland can illustrate a world with ComfyUI, OpenRouter, or a plugin generator: character
portraits, single-object renders, toon sprites, and on-request scene images for world events.
An independently configured ComfyUI workflow can also produce short event-video clips.
The simulation never blocks on this — image and video generation each run through their own
single-worker queue — and the engine only ever stores a small URL reference, never media bytes.

Each modality is **off** until its generator is explicitly selected. Setting
`COMFYUI_SERVER_URL` only configures the shared client; use
`BUNNYLAND_IMAGE_GENERATOR=comfyui`, `BUNNYLAND_VIDEO_GENERATOR=comfyui`, or both to submit
work to ComfyUI's own queue.

## Prerequisites and boundary

Complete [MCP server and local agents](mcp-local-agent.md), even if MCP is disabled. Install
the `imagegen` extra, choose a durable media directory, and decide which provider may receive
world descriptions. ComfyUI should remain on loopback or a private network; never expose its
workflow API directly to the internet.

Generated media is public presentation data once served by the web client. Prompts can still
contain community-authored names and descriptions, so review provider retention/data-use
terms and do not include private memories or operator notes in templates.

## Turning it on

Choose one server-wide fallback. Any purpose can override it independently:

```bash
BUNNYLAND_IMAGE_GENERATOR=in-memory       # comfyui | in-memory | openrouter | plugin name
BUNNYLAND_IMAGE_GENERATOR_PORTRAIT=openrouter
BUNNYLAND_IMAGE_GENERATOR_ENTITY=in-memory
BUNNYLAND_IMAGE_GENERATOR_SPRITE=comfyui
BUNNYLAND_IMAGE_GENERATOR_EVENT=openrouter
```

The equivalent YAML is:

```yaml
imagegen:
  generator: in-memory
  generators:
    portrait: openrouter
    sprite: comfyui
  openrouter_image_model: google/gemini-3.1-flash-lite-image
  video_generator: comfyui
  video_profile: event-video
```

For ComfyUI, set `COMFYUI_SERVER_URL` (the rest are optional):

```bash
COMFYUI_SERVER_URL=http://localhost:8188   # WHERE your ComfyUI server is
COMFYUI_USE_WEBSOCKET=1                     # watch progress over /ws (HTTP polling fallback)
COMFYUI_POLL_INTERVAL_SECONDS=1
COMFYUI_TIMEOUT_SECONDS=120
BUNNYLAND_MEDIA_DIR=/data/media             # where generated images and clips are written
BUNNYLAND_IMAGE_WORKFLOWS=sdxl             # WHICH workflow family (model) to use for images
BUNNYLAND_MEDIA_PROMPT_STYLE=              # force "tag" or "natural" (blank = family default)
BUNNYLAND_MEDIA_TEMPLATES=/data/media-workflows.json  # optional per-template overrides
BUNNYLAND_VIDEO_GENERATOR=comfyui            # image and video providers are selected separately
BUNNYLAND_VIDEO_PROFILE=event-video          # built-in ComfyUI LTX 2.3 T2V profile
BUNNYLAND_MEDIA_ENHANCER=stub              # "stub" (offline) or "llm" (uses OLLAMA_*)
BUNNYLAND_IMAGE_BACKFILL_SECONDS=5         # cadence of the portrait/sprite backfill
```

The prompt **enhancer** turns an entity or event into a model-ready prompt. The default
`stub` enhancer is deterministic and needs no network; set `BUNNYLAND_MEDIA_ENHANCER=llm`
to have an Ollama model write richer prompts (it reuses your `OLLAMA_HOST` /
`OLLAMA_CLOUD_API_KEY`). Plugins can register additional enhancers by name.

> **Discord avatars require a public URL.** Posting a character's portrait as a Discord
> avatar needs an absolute, reachable image URL, so set `BUNNYLAND_PUBLIC_BASE_URL`
> (e.g. `https://play.example.com`). Everything else — the web client and event-image
> uploads — works without it.

The `imagegen` extra provides the dependencies (`httpx`, `websockets`, `Pillow`):

```bash
uv sync --extra imagegen
```

`in-memory` produces deterministic abstract PNG artwork with no network service. It is useful
for offline demos and integration tests.

OpenRouter uses the official SDK's async chat image-output modality. It requires an explicit
model and API key so a deployment cannot accidentally select an unsuitable or expensive model:

```bash
BUNNYLAND_IMAGE_GENERATOR=openrouter
BUNNYLAND_IMAGE_OPENROUTER_MODEL=google/gemini-3.1-flash-lite-image
OPENROUTER_API_KEY=sk-or-...
```

For a hosted service, prefer
`OPENROUTER_API_KEY_FILE=/etc/bunnyland/openrouter.key` over a literal variable. Keep the
file mode `0600`. Never put the key in the image template JSON, browser configuration, model
prompt, URL, repository, screenshot, or logs.

Install both optional dependency groups for OpenRouter image generation:

```bash
uv sync --extra imagegen --extra llm
```

Provider failures fail the job and are reported to clients. Bunnyland never silently switches
to a different generator.

## What gets generated, and when

- **Portraits** — every character always gets a portrait. A throttled backfill loop fills
  in any character that is missing one, one request at a time, so enabling image generation
  on an existing world gradually illustrates everyone without flooding ComfyUI.
- **Toon sprites** — when the `toonsim` pack is enabled, characters also get a transparent
  sprite (the alpha background is removed automatically).
- **Event images** — generated only when a player requests one (see the player guide). The
  first request for an event is generated and then reused for everyone; admins can force a
  regenerate.
- **Event videos** — generated only when a player requests a clip of the latest events in
  their room. Video generation is advertised separately from images and remains off unless
  `BUNNYLAND_VIDEO_GENERATOR` selects the video provider and
  `BUNNYLAND_VIDEO_PROFILE` selects one of its profiles.

Generated media **persists**: the reference is saved with the world, and nothing is
regenerated once an entity or event has that image or clip.

## Enabling short ComfyUI videos

ComfyUI video generation requires `COMFYUI_SERVER_URL`,
`BUNNYLAND_VIDEO_GENERATOR=comfyui`, and `BUNNYLAND_VIDEO_PROFILE`. The built-in
ComfyUI template `event-video` uses LTX 2.3 22B in text-to-video mode, generates synchronized
audio, and produces a five-second 25 fps clip. It loads:

- `ltx-2.3-22b-dev-fp8.safetensors` for the model, VAE, and audio VAE;
- `gemma_3_12B_it_fp4_mixed.safetensors` for text encoding;
- `ltx-2.3-22b-distilled-lora-384.safetensors` at model strength `0.5`; and
- `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` for latent upscaling.

Set the built-in template directly:

```bash
COMFYUI_SERVER_URL=http://localhost:8188
BUNNYLAND_VIDEO_GENERATOR=comfyui
BUNNYLAND_VIDEO_PROFILE=event-video
```

The LTX graph is provider-specific: Bunnyland only resolves it through the ComfyUI generator.
Selecting another provider for images does not send this graph to that provider.

To override it or add another ComfyUI video graph, set `BUNNYLAND_MEDIA_TEMPLATES` to a JSON
file. Template metadata must use `purpose: "event"` and `media: "video"`; the configured name
must match exactly:

```json
{
  "templates": [
    {
      "name": "event-video",
      "purpose": "event",
      "media": "video",
      "prompt_style": "natural",
      "width": 768,
      "height": 512,
      "output_node_id": "42",
      "graph": { "...": "the exported ComfyUI API workflow" },
      "slots": []
    }
  ]
}
```

Keep clip duration, frame rate, and codec fixed in the workflow graph. Bunnyland injects the
same `%PROMPT%`, `%NEGATIVE%`, `%SEED%`, `%WIDTH%`, and `%HEIGHT%` values used by image
templates. The output node may be a native ComfyUI video output or VideoHelperSuite's video
combine node; saved MP4 and WebM outputs are accepted. Bunnyland refuses to start when the
named template is absent, has another purpose, or declares image media.

With a custom template file in place:

```bash
COMFYUI_SERVER_URL=http://localhost:8188
BUNNYLAND_MEDIA_TEMPLATES=/data/media-workflows.json
BUNNYLAND_VIDEO_GENERATOR=comfyui
BUNNYLAND_VIDEO_PROFILE=event-video
```

`GET /v1/public/features` reports `image_generation` and `video_generation` independently.
Browser clients hide each corresponding control when its flag is false. Discord only accepts
the 🎬 reaction when video generation is advertised.

## Choosing a ComfyUI model family

A *workflow family* is a set of ComfyUI graphs (one per purpose: `portrait`, `entity`,
`sprite`, `event`) built around one base model. Pick the family with `BUNNYLAND_IMAGE_WORKFLOWS`
to match your GPU and quality target:

| Family (`BUNNYLAND_IMAGE_WORKFLOWS`) | Base model | Prompt style | VRAM | Notes |
|---|---|---|---|---|
| `anima` *(default)* | Anima (Qwen-CLIP + UNET + Bunnyland LoRA) | tag / score | lowest | best for small GPUs |
| `sdxl` | SDXL / Illustrious / Pony | tag | low–mid | two-pass + latent upscale |
| `klein` | Flux 2 Klein 9B | natural language | mid–high | |
| `flux2dev` | Flux.2 Dev | natural language | highest | best quality; optional Turbo LoRA |

A family label may carry your own suffix — the base is the **first keyword** before the
first `-`. So `BUNNYLAND_IMAGE_WORKFLOWS=anima-my-server` still uses the `anima` base graphs;
the suffix is just a label for templates you override (below).

The enhancer formats prompts to the family's style (tag vs natural) automatically. To force
a style regardless of family, set `BUNNYLAND_MEDIA_PROMPT_STYLE=tag` or `natural`.

## Changing the model

Each family is a directory of JSON files shipped inside the package at
`bunnyland/imagegen/workflows/<family>/{portrait,entity,sprite,event}.json`. The simplest
customization is to keep a family but point it at a different checkpoint — copy the template
you want to change, edit the model field, and load it through `BUNNYLAND_MEDIA_TEMPLATES`
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

- **Flux / UNET families** — use `LoraLoaderModelOnly` (model only). The shipped `anima`
  family applies `testing/anima/bunnyland_vector_anima_v1_e20.safetensors` at model strength
  `0.9` between its Anima base UNET and sampler. The shipped `flux2dev`
  family already includes a Turbo LoRA wired through a switch: node `98:101`
  (`LoraLoaderModelOnly`) is toggled by the `Enable Turbo LoRA` boolean (`98:104`). Set its
  `value` to `true` (and the steps switch picks the 8-step turbo schedule) to enable it, or
  add your own `LoraLoaderModelOnly` before the guider.

## Admin controls

With a bearer token scoped for `world:admin`:

```bash
# Generate (or regenerate) an image for any entity or history record:
POST /v1/admin/world/generation-jobs
     {"kind": "image", "entity_id": "...",
      "purpose": "portrait|entity|sprite|event",
      "template": "", "alpha": false, "force": false}

# Generate a video for a history record:
POST /v1/admin/world/generation-jobs
     {"kind": "video", "entity_id": "...", "template": "", "force": false}

# Check a job:
GET  /v1/admin/world/generation-jobs/{job_id}
```

Generated files are served read-only at `GET /v1/public/media/{kind}/{name}`.

## Live provider validation

Live image, text/LLM, and video suites have independent flags and are not part of the
default test gate:

```bash
BUNNYLAND_LIVE_IMAGEGEN_COMFY=1 \
  uv run -m pytest -m live_imagegen_comfy

BUNNYLAND_LIVE_IMAGEGEN_OPENROUTER=1 \
  BUNNYLAND_LIVE_OPENROUTER_IMAGE_MODEL=google/gemini-3.1-flash-lite-image \
  uv run -m pytest -m live_imagegen_openrouter

BUNNYLAND_LIVE_LLM=1 \
  uv run -m pytest -m live_llm

BUNNYLAND_LIVE_VIDEOGEN_COMFY=1 \
  uv run -m pytest -m live_videogen_comfy
```

The two ComfyUI suites also need `COMFYUI_SERVER_URL`; enabling one does not enable the
other. The OpenRouter suite also needs `OPENROUTER_API_KEY` and always requires its separate
live model variable. Text/LLM credentials remain independent from both media suites.

## Troubleshooting

### Jobs time out or remain pending

Check reachability from the Bunnyland service account to `COMFYUI_SERVER_URL`, inspect the
ComfyUI queue, and confirm the selected workflow's model files exist. Increase the timeout
only after measuring a successful generation on the same hardware.

### ComfyUI works locally but not from the service

Keep ComfyUI private, but bind it to an address reachable on the private service network.
Check host/container network names and firewall policy; do not publish port 8188 as a fix.

### OpenRouter returns an unsupported-output error

Use an image-capable model currently available to your account and keep
`BUNNYLAND_IMAGE_OPENROUTER_MODEL` explicit. Bunnyland will not silently switch providers.

### Images work in the web client but not as Discord avatars

Set `BUNNYLAND_PUBLIC_BASE_URL` to the HTTPS Bunnyland origin and verify the resulting media
URL is reachable without a local hostname. Do not expose the media filesystem itself.

### Media disappears after a restart

Mount or configure a durable `BUNNYLAND_MEDIA_DIR` and include it in the consistent backup
set. A database/snapshot reference cannot recreate a deleted image file.

[← MCP server and local agents](mcp-local-agent.md) ·
[Backups, upgrades, observability, and recovery →](backups-upgrades-observability.md)
