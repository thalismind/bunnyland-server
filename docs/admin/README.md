# Admin & controllers

## Controllers

A **character** is a persistent entity. Who acts for it is a separate, swappable
**controller** entity, linked by a `ControlledBy` edge. The built-in controller kinds are:

- **LLM** (`LLMControllerComponent`) — an Ollama or OpenRouter agent decides its actions.
- **Discord** (`DiscordControllerComponent`) — a person drives it (see the
  [Discord bot](discord-bot.md)).
- **MCP** (`MCPControllerComponent`) — an agentic MCP client drives it through the
  [MCP server](mcp-server.md). For workstation clients, see the
  [local coding-agent setup](mcp-local-agent.md).
- **Behavioral** (`BehaviorControllerComponent`) — a deterministic, model-free controller
  that ticks a named behavior tree (e.g. `forager`, `wanderer`, `guard`) against the
  character's prompt context each turn. No LLM call is made. See the
  [behavior & scripted controllers](../developer/controllers.md) developer guide.
- **Scripted** (`ScriptedControllerComponent`) — replays a named, fixed sequence of tool
  calls turn by turn, optionally looping. No LLM call is made. See the
  [behavior & scripted controllers](../developer/controllers.md) developer guide.
- **Suspended** (`SuspendedControllerComponent`) — a no-op. The character still regenerates
  and is affected by the world, but takes no actions. A freshly generated "claimable"
  character starts suspended.

Every control change bumps a **generation** counter on the edge. Commands carry the
generation they were created under, so a command from a controller that has since been
replaced is rejected as stale. This is what makes hand-off safe.

## Claiming and handing off characters: control verbs

Control changes are themselves commands, submitted to the actor like any other — but they
are special: **free** (no points), and they **bypass** the generation/cost/state gates so
hand-off and resume always work. The new controller goes in the payload as `controller_id`.

| Verb              | Effect                                                              |
|-------------------|--------------------------------------------------------------------|
| `take-control`    | Point the character at a (human/Discord) controller.               |
| `release-to-llm`  | Hand the character back to an LLM controller.                      |
| `suspend`         | Mark the character suspended under a no-op controller (`reason`).  |
| `resume`          | Clear suspension and assign an active controller.                  |

```python
from bunnyland.core import CommandCost, Lane, build_submitted_command, spawn_entity
from bunnyland.core.controllers import DiscordControllerComponent

# A human takes over a character.
human = spawn_entity(
    actor.world, [DiscordControllerComponent(discord_user_id=123, default_channel_id=456)]
)
cmd = build_submitted_command(
    character_id=str(character_id),
    controller_id=str(character_id),   # ignored for control verbs
    controller_generation=-1,          # bypassed for control verbs
    command_type="take-control",
    cost=CommandCost(),                # free
    lane=Lane.WORLD,
    payload={"controller_id": str(human.id)},
)
await actor.submit(cmd)
await actor.tick(0.0)                  # processed on the next tick
```

`suspend` takes an extra `reason`:

```python
payload={"controller_id": str(no_op_controller.id), "reason": "afk"}
```

Each change emits a `ControllerChangedEvent` (with the new `generation` and
`controller_kind`) you can subscribe to for audit/logging.

For a quick setup (outside the command pipeline) you can also call
`actor.assign_controller(character_id, controller_id)` and `actor.suspend(...)` directly —
that's what world generation uses. The control verbs are the in-world, multi-actor-safe path.

## Plugins

The world actor always provides the core spine (clock, regeneration, downed/death). Optional
behaviour is added by **plugins**; the builtins are:

| Plugin id               | Provides                                                       |
|-------------------------|---------------------------------------------------------------|
| `bunnyland.core_verbs`  | move, take, put, use, write, sleep/wake/wait, say, tell, threaded conversations |
| `bunnyland.lifesim`     | daily needs, eat/drink, self-care, homes, work, family, aging |
| `bunnyland.memory`      | take-note / remember (private, focus-lane)                    |
| `bunnyland.worldgen`    | the `oneshot` and `recursive` world generators                |
| `bunnyland.environment` | day/night light cycle, calendar, weather                      |
| `bunnyland.mechanisms`  | door auto-close and momentary-button reset timers             |
| `bunnyland.social`      | social bonds that grow through speech (affinity/trust/fear)   |
| `bunnyland.policy`      | boundary/consent gate (flirting etc.); denied always wins     |
| `bunnyland.colonysim`   | resources, stockpiles, work, recipes, health, rooms, wealth  |
| `bunnyland.gardensim`   | crops, trees, machines, animals, fishing, mining, bundles    |
| `bunnyland.barbariansim` | combat, stamina, exposure, gear durability, poison, corruption |
| `bunnyland.dragonsim`   | discovery, map markers, encounter zones, quests, factions     |
| `bunnyland.daggersim`   | rumors, travel, guilds, banks, law, property, spells, dungeons |
| `bunnyland.voidsim`     | ships, pressure, fabrication, salvage, cargo, docking, jumps  |
| `bunnyland.nukesim`     | radiation, mutation pressure, scavenging, settlement salvage  |
| `bunnyland.dinosim`     | fossils, clone eggs, hatching, taming, feed stores, kaiju     |
| `bunnyland.mcp`         | optional HTTP MCP endpoint for agentic clients                |

The sim packages (`bunnyland.lifesim`, `colonysim`, `gardensim`, `barbariansim`,
`dragonsim`, `daggersim`, `voidsim`, `nukesim`, `dinosim`) add their own components and
verbs. Implemented sims also include a ready-to-play `<sim>-demo` world generator — e.g.
`serve --generator voidsim-demo`. See [world creation](../developer/world-creation.md) for
the full list.

Each mechanic surfaces itself to characters where it can. Stable identity state, persona
profile, social bonds, and boundaries appear in the agent prompt's "Persona" block. Needs,
weather/time, and other changing mechanic state appear in "Currently", while room changes
(light, door state, ...) flow into the room summary an agent perceives.
Nearby social facts appear in the prompt's `Social cues` section: recent arrivals,
departures, room speech, visible distress, quiet nearby characters, and unanswered speech.
This is a structured prompt surface for controller attention; narration may describe the
same facts, but narration remains presentation rather than truth.
Agent decisions also carry advisory `persona_issues` when a tool call contradicts stable
persona facts, such as claiming another character's name, denying a known bond, or claiming
an impossible status. These issues are logged for review; valid commands still enter the
normal queue and are validated by handlers.
When a memory store is attached, prompts also include contextual `Recall` lines selected
from the character's private memory collection by matching current location, visible
entities, and recent room context. Recall entries include memory id, source, and score
metadata so operators can audit why a past note surfaced.
Recall is bounded by prompt-builder limits for entry count, total recall characters, and
per-memory line length. Higher-scored memories are considered first, so low-relevance noise
falls out before durable relevant entries.
The memory plugin also installs a bounded reflection loop. Once enough new non-reflection
private memories accumulate after the configured interval, the loop invokes the normal
`reflect` handler, stores a private reflection, and updates the character's
`last_reflection_epoch`.
For low-cost autonomy, `GoalDirectedAgent` can drive an LLM-controlled character without a
model call. It reads the same prompt facts an LLM would see, prefers actions tied to
goals, recalled memories, needs, visible people, visible objects, and available exits, and
then submits a normal tool call through controller dispatch. If the prompt does not
contain a clear goal or recall signal, the character waits instead of moving randomly.
`BehaviorProfileAgent` adds model-free fallback profiles for background population:
`idle`, `social`, `timid`, `aggressive`, and `worker`. Goal-directed actions still run
first; the profile only supplies a cheap default when the prompt has no stronger goal or
recall-driven action.
Relationship facts also influence those cheap profiles: fear tends toward avoidance,
fondness tends toward warm speech, and resentment or dislike tends toward guarded speech.
The controller still submits ordinary tool calls; the relationship state is prompt input,
not a bypass around command validation.
For saved worlds, `advance_offline_life(actor, elapsed_seconds)` can run a bounded offline
catch-up pass after reload. It uses cheap background controllers and normal command
validation, then the next save persists any resulting movement, inventory, needs, or memory
changes.

### Enabling a subset

By default all `default_enabled` plugins load. Restrict with repeated `--plugin`:

```bash
uv run bunnyland serve --plugin bunnyland.core_verbs --plugin bunnyland.worldgen
```

Starter packs are named startup presets for common plugin groups. They expand before the
world is generated or loaded, so the server imports and applies the pack's mechanics from
process start:

```bash
uv run bunnyland serve --starter-pack peaceful
```

The bundled packs are:

| Pack | Sim plugins |
|------|-------------|
| `peaceful` | `bunnyland.lifesim`, `bunnyland.colonysim`, `bunnyland.gardensim` |
| `fantastic` | `bunnyland.lifesim`, `bunnyland.colonysim`, `bunnyland.gardensim`, `bunnyland.barbariansim`, `bunnyland.dragonsim` |
| `futuristic` | `bunnyland.lifesim`, `bunnyland.colonysim`, `bunnyland.gardensim`, `bunnyland.barbariansim`, `bunnyland.voidsim`, `bunnyland.nukesim` |

Each pack also includes `bunnyland.core_verbs` and `bunnyland.worldgen`, so the normal
startup generators remain available. You can set the same preset for Docker deployments
with `BUNNYLAND_STARTER_PACK=peaceful`.

Dependency order is resolved automatically, but selection is explicit. When you pass a
plugin list, include each required plugin yourself; missing requirements are logged as
errors and the server exits. The main built-in sim requirements are:

| Plugin | Required built-in layers |
|--------|--------------------------|
| `bunnyland.lifesim` | `bunnyland.core_verbs` |
| `bunnyland.colonysim` | `bunnyland.core_verbs`, `bunnyland.lifesim` |
| `bunnyland.gardensim` | `bunnyland.core_verbs`, `bunnyland.lifesim`, `bunnyland.colonysim` |
| `bunnyland.barbariansim` | `bunnyland.core_verbs`, `bunnyland.lifesim`, `bunnyland.colonysim`, `bunnyland.gardensim` |
| `bunnyland.dragonsim` | `bunnyland.core_verbs`, `bunnyland.lifesim` |
| `bunnyland.daggersim` | `bunnyland.core_verbs` |
| `bunnyland.voidsim` | `bunnyland.core_verbs`, `bunnyland.colonysim`, `bunnyland.barbariansim` |
| `bunnyland.nukesim` | `bunnyland.core_verbs`, `bunnyland.colonysim`, `bunnyland.barbariansim`, `bunnyland.voidsim` |
| `bunnyland.dinosim` | `bunnyland.core_verbs`, `bunnyland.lifesim`, `bunnyland.colonysim` |

Recommended plugins are logged as warnings and the server continues. A future
`--auto-load-requires` flag may add missing requirements automatically. A verb whose plugin
isn't loaded simply has no handler, and commands for it are rejected — disabling a plugin
cleanly removes its surface.

The MCP plugin is disabled by default. Prefer `--mcp` when running the HTTP API; it adds
`bunnyland.mcp` to the selected plugin set and mounts the MCP app on the same FastAPI
server under `/mcp`.

### Loading external plugins

Point `--module` at any importable module exposing `bunnyland_plugins()`:

```bash
uv run bunnyland serve --module mygame.content --generator arena
```

This is how you add your own verbs, components, mechanics, or world generators. See
[world creation](../developer/world-creation.md) for a generator example, and
`src/bunnyland/plugins/builtin.py` for the builtin plugin definitions.

## Saving, autosaving, and resetting

A world can be saved, autosaved, and reloaded with the server CLI. A reset can be a fresh
launch without `--load`, or an authenticated admin replacement through
`POST /admin/world/generate`. See [generating worlds](generating-worlds.md) for the web/API
flow and [saving & reloading](../developer/persistence.md) for the full persistence
behavior.

## Observing the world

Subscribe to typed events on `actor.bus` for monitoring or moderation — for example
`CommandRejectedEvent`, `ControllerChangedEvent`, `SpeechSaidEvent`, `ActorMovedEvent`,
or `CharacterDiedEvent`. `--verbose` (see [running a server](running-a-server.md)) logs
decisions and rejections at INFO.

`NarrationProjection` can also subscribe to the same bus and keep a volatile read-side
presentation transcript keyed by viewer id. It assembles scene facts from current ECS
projections and visible domain events. Each transcript entry keeps the structured
`SceneInput.facts`, event clusters, and source event ids for audit, and a renderer failure
is recorded on the projection without mutating the world. Noisy scene batches retain
high-salience events and record compressed low-salience event ids on the scene input.
Scenario voice controls change renderer diction only; audit facts and event ids stay the
same across voices.
Use `NarrationProjection(non_blocking=True)` when prose rendering may call a slow model.
The projection queues delivery from the already-assembled scene facts, exposes
`pending_deliveries()` for monitoring, and records timeout or renderer errors while
falling back to deterministic prose. This affects presentation delivery only; ticks and
ECS state continue through the normal command/event pipeline.
`evaluate_narration_quality(scene, text)` provides a deterministic audit pass for rendered
prose. It reports hidden-state leakage, contradictions of visible scene facts, omitted
high-salience events, and voice drift before any human or model-based quality review.

For external dashboards, the engine can also export OpenTelemetry metrics (world counts,
tick cadence, command accept/reject rates, LLM token usage) and traces (tick → command →
handler, controller → agent decision). It is off by default; see the
[OpenTelemetry section](running-a-server.md#observability-opentelemetry) of the
running-a-server guide for the `otel` extra and the `BUNNYLAND_OTEL_ENABLED` gate.
