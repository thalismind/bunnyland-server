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

`fortresssim` is still planned rather than shipped.

Starter packs provide coarse bundles:

- `peaceful`: core verbs, worldgen, life-sim, colony-sim, and garden-sim.
- `fantastic`: peaceful plus barbarian-sim and dragon-sim.
- `futuristic`: peaceful plus barbarian-sim, void-sim, and nuke-sim.

## Out-of-Tree Plugins

- `bunnyland-3d`: adds 3D transform, velocity, collider, render, and room-bounds
  components, a movement/collision system, 3D worldgen enrichment, and standalone
  `/3d/` admin/player dashboards. Repository:
  `thalis-github:thalismind/bunnyland-3d.git`.
- `bunnyland-rl`: adds reinforcement-learning controller components, RL controller
  dispatch registration, offline arena training, saved safetensors model artifacts,
  W&B tracking support, admin training/model APIs, and a standalone `/rl/` admin
  dashboard. It requires Bunnyland server `0.2.0` or newer. Repository:
  `thalis-github:thalismind/bunnyland-rl.git`.

The plugin server image should extend `ghcr.io/thalismind/bunnyland-server:main`.
Dashboard images should extend the published Bunnyland web image and copy their static
assets into a route-specific prefix such as `/3d/` or `/rl/`.
