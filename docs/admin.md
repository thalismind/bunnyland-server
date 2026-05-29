# Admin & controllers

## Controllers

A **character** is a persistent entity. Who acts for it is a separate, swappable
**controller** entity, linked by a `ControlledBy` edge. There are three kinds:

- **LLM** (`LLMControllerComponent`) — an Ollama agent decides its actions.
- **Discord** (`DiscordControllerComponent`) — a person drives it (see the
  [Discord bot](discord-bot.md)).
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

| Plugin id              | Provides                                              |
|------------------------|------------------------------------------------------|
| `bunnyland.core_verbs` | move, take, put, use, write, sleep/wake/wait, say, tell |
| `bunnyland.lifesim`    | hunger/thirst components + systems, eat/drink, affect |
| `bunnyland.memory`     | take-note / remember (private, focus-lane)           |
| `bunnyland.worldgen`   | the `oneshot` and `recursive` world generators       |

### Enabling a subset

By default all `default_enabled` plugins load. Restrict with repeated `--plugin`:

```bash
uv run bunnyland serve --plugin bunnyland.core_verbs --plugin bunnyland.worldgen
```

Dependencies are resolved automatically (e.g. `lifesim` and `memory` depend on
`core_verbs`). A verb whose plugin isn't loaded simply has no handler, and commands for it
are rejected — disabling a plugin cleanly removes its surface.

### Loading external plugins

Point `--module` at any importable module exposing `bunnyland_plugins()`:

```bash
uv run bunnyland serve --module mygame.content --generator arena
```

This is how you add your own verbs, components, mechanics, or world generators. See
[world creation](world-creation.md) for a generator example, and
`src/bunnyland/plugins/builtin.py` for the builtin plugin definitions.

## Observing the world

Subscribe to typed events on `actor.bus` for monitoring or moderation — for example
`CommandRejectedEvent`, `ControllerChangedEvent`, `SpeechSaidEvent`, `ActorMovedEvent`,
`CharacterDiedEvent`. `--verbose` (see [running a server](running-a-server.md)) logs
decisions and rejections at INFO.
