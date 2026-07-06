# Bunnyland Plugins

Bunnyland mechanics are packaged as plugins. A world can run the full catalogue, a
small starter pack, or a custom set of plugin IDs selected at startup. Plugins contribute
ECS components, systems, verbs, prompt fragments, worldgen hooks, runtime services, and
admin/server routers.

Run out-of-tree plugins with repeated `--module` flags:

```bash
bunnyland serve --module bunnyland_3d --module bunnyland_rl ...
```

## Builtin Foundation Plugins

- `bunnyland.core_verbs`: movement, looking, inventory, object use, talking, waiting,
  sleeping, waking, and other baseline verbs.
- `bunnyland.checkpoints`: opt-in save/reload checkpoint entities and verbs. Disabled
  by default; enable explicitly and intentionally place checkpoint objects.
- `bunnyland.worldgen`: deterministic demo generators plus recursive worldgen expansion.
- `bunnyland.environment`: time of day, weather, light, fire, and environmental pressure.
- `bunnyland.mechanisms`: doors, buttons, switches, locks, and other interactive machinery.
- `bunnyland.memory`: private notes and recall.
- `bunnyland.history`: world history records for events and images.
- `bunnyland.social`: social bonds and relationship state.
- `bunnyland.policy`: world and character boundaries.
- `bunnyland.persona`: goals, traits, and promptable personality state.
- `bunnyland.storyteller`: paced incidents and cross-pack event pressure.
- `bunnyland.toonsim`: sprite/rendering metadata for 2D clients.
- `bunnyland.imagegen`: image generation request and storage hooks.
- `bunnyland.mcp`: MCP-facing runtime integration.

## Builtin Sim Packs

- `bunnyland.lifesim`: needs, moods, whims, homes, routines, careers, businesses,
  relationships, pregnancy, family, inheritance, skills, and aging policy.
- `bunnyland.colonysim`: work priorities, jobs, crafting recipes, workstations,
  resource gathering, ownership, reservations, prisoners, and colony-style task loops.
- `bunnyland.gardensim`: soil, tilling, crops, watering, fertilizer, seasons,
  harvesting, trees, tapping, sap, and farm chores.
- `bunnyland.barbariansim`: survival combat, stamina, exposure, gear durability,
  buildings, purges, rituals, danger zones, bosses, treasure, poison, and corruption.
- `bunnyland.dragonsim`: radiant quests, objectives, factions, reputation,
  persuasion, crime, artifacts, magic, shouts, beast threats, and map discovery.
- `bunnyland.daggersim`: procedural RPG frontier expansion, rumors, travel logistics,
  guilds, institutions, services, banking, law, custom classes, spells, etiquette,
  pacification, afflictions, and dungeons.
- `bunnyland.voidsim`: ships, stations, habitat modules, airlocks, pressure, life
  support, power grids, repair, docking, crew morale, drones, AI, xenobiology,
  emergencies, passengers, customs, mining, insurance, and mortgages.
- `bunnyland.nukesim`: radiation, shielding, mutation pressure, suppressants,
  salvage, old-world artifacts, tech, schematics, field repair, chems, beacons,
  trader routes, raider pressure, and terminals.
- `bunnyland.neonsim`: districts, access control, surveillance, evidence,
  hacking, counter-intrusion traces, heat/wanted pressure, cybernetics, fixers,
  corporate intrigue, and cyberpunk site generation.
- `bunnyland.dinosim`: fossil discovery, species identification, cloning,
  incubation, eggs, imprinting, juvenile care, brooding, aquatic creatures,
  containment panic, tracking, taming, companion commands, enclosures, escapes,
  and kaiju incidents.

Starter packs provide coarse bundles:

- `peaceful`: `bunnyland.core_verbs`, `bunnyland.worldgen`, `bunnyland.lifesim`,
  `bunnyland.colonysim`, and `bunnyland.gardensim`.
- `fantastic`: `peaceful` plus `bunnyland.barbariansim` and `bunnyland.dragonsim`.
- `futuristic`: `peaceful` plus `bunnyland.barbariansim`, `bunnyland.voidsim`, and
  `bunnyland.nukesim`.

## Out-of-Tree Plugins

Out-of-tree plugins live in their own repositories and are loaded with repeated `--module`
flags (for example `--module bunnyland_spectersim`). Their plugin ids use the same
`bunnyland.*` namespace as the builtins.

### Addons

Larger standalone extensions, each shipping its own client/dashboard and a substantial
feature set:

- **`bunnyland.3d`** — [bunnyland-3d](https://github.com/thalismind/bunnyland-3d): 3D
  transform/velocity/collider/render/room-bounds components, a movement and collision
  system, 3D worldgen enrichment, and standalone `/3d/` admin and player dashboards. Load
  with `--module bunnyland_3d`.
- **`bunnyland.rl`** — [bunnyland-rl](https://github.com/thalismind/bunnyland-rl):
  reinforcement-learning controller components, RL controller dispatch, offline arena
  training, safetensors model artifacts, Weights & Biases tracking, admin training/model
  APIs, and a standalone `/rl/` admin dashboard. Requires Bunnyland server `0.2.0` or newer.
  Load with `--module bunnyland_rl`.

### Sim packs

Focused content packs built on the shared plugin template (frozen ECS components, per-tick
consequences, prompt fragments, worldgen hooks, and player/AI verbs). Each is hosted at
`github.com/thalismind/bunnyland-plugin-<name>` and loaded with `--module bunnyland_<name>`:

- **`bunnyland.spectersim`** — [repo](https://github.com/thalismind/bunnyland-plugin-spectersim):
  paranormal monster-detecting devices (ghost detector + radio), plus
  a sanity dread meter and banishing rituals and wards.
- **`bunnyland.wildsim`** — [repo](https://github.com/thalismind/bunnyland-plugin-wildsim):
  wilderness survival — scent trails, cold/warmth exposure, campfires, and foraging.
- **`bunnyland.petsim`** — [repo](https://github.com/thalismind/bunnyland-plugin-petsim):
  companion creatures — following, taming, bonding and loyalty, tricks, and danger reactions.
- **`bunnyland.bardsim`** — [repo](https://github.com/thalismind/bunnyland-plugin-bardsim):
  music and performance — instruments, performing (audible through the hearing system), mood
  shifts, busking tips, and a learnable repertoire.
- **`bunnyland.anglersim`** — [repo](https://github.com/thalismind/bunnyland-plugin-anglersim):
  fishing — fishing spots, a deterministic catch table by biome and time of day, rarity
  tiers, bait, and a trophy log.
- **`bunnyland.hearthsim`** — [repo](https://github.com/thalismind/bunnyland-plugin-hearthsim):
  cooking and meals — recipes, stoves, timed meal buffs, freshness and spoilage, and shared
  feasts.
- **`bunnyland.dreamsim`** — [repo](https://github.com/thalismind/bunnyland-plugin-dreamsim):
  sleep and dreams — deterministic dreams on sleep, insight and omens, nightmares, and sleep
  quality.
- **`bunnyland.cartographysim`** — [repo](https://github.com/thalismind/bunnyland-plugin-cartographysim):
  maps and navigation — a field map, compass, landmarks, fast-travel, and fog of war.
- **`bunnyland.postsim`** — [repo](https://github.com/thalismind/bunnyland-plugin-postsim):
  mail and couriers — letters and parcels, mailboxes, couriers that carry mail across rooms
  over time, care packages, and return-to-sender.
- **`bunnyland.museumsim`** — [repo](https://github.com/thalismind/bunnyland-plugin-museumsim):
  collections and curation — collectible tagging, donation, appraisal, exhibits, and display
  cases.
- **`bunnyland.festivalsim`** — [repo](https://github.com/thalismind/bunnyland-plugin-festivalsim):
  seasonal festivals — a festival calendar, decorations, gift-giving, contests, and seasonal
  mood.
- **`bunnyland.fortunesim`** — [repo](https://github.com/thalismind/bunnyland-plugin-fortunesim):
  luck and superstition — a luck stat other packs can read, charms and talismans, omens,
  fortune-telling, and luck-warding rituals.
- **`bunnyland.aquasim`** — [repo](https://github.com/thalismind/bunnyland-plugin-aquasim):
  swimming and diving — submerged rooms, a breath meter with drowning, diving for treasure,
  currents and hazards, and a swim skill.
- **`bunnyland.starsim`** — [repo](https://github.com/thalismind/bunnyland-plugin-starsim):
  stargazing and astronomy — a calendar-driven night sky, constellations, celestial events
  with make-a-wish, and star navigation.
- **`bunnyland.cryptidsim`** — [repo](https://github.com/thalismind/bunnyland-plugin-cryptidsim):
  cryptozoology — rare, elusive creatures confirmed only through deterministic uncertain
  sightings, case files, and hedged field reports until enough clear looks confirm them.
- **`bunnyland.loresim`** — [repo](https://github.com/thalismind/bunnyland-plugin-loresim):
  pacifist field-naturalist observation — a bestiary journal, deterministic lore notes,
  discovery credit, expeditions, and published field guides, without ever capturing or
  harming a subject.

The plugin server image should extend `ghcr.io/thalismind/bunnyland-server:main`.
Dashboard images should extend the published Bunnyland web image and copy their static
assets into a route-specific prefix such as `/3d/` or `/rl/`.
