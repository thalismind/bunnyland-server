# Scripting

Bunnyland scripts are external content for deterministic tests, scripted world events,
and plugin-provided scenarios. They are not Python, and they are not ECS entities. A
script is a JSON-serializable definition loaded from plugin contributions or standalone
files, then executed by `ScriptRuntime`.

Scripts can submit normal game commands through `WorldActor` or apply explicit
admin-style world patches. Normal commands still go through the existing command queue,
controller generation checks, policy gates, point spending, handlers, consequences, and
domain events.

## Loading

Plugins can contribute scripts through `ContentContribution.scripts`:

```python
from bunnyland.plugins import ContentContribution, Plugin
from bunnyland.scripting import ScriptDefinition

script = ScriptDefinition.model_validate({...})

plugin = Plugin(
    id="example",
    name="Example",
    content=ContentContribution(scripts=(script, "examples/scripts/epoch_bell.json")),
)
```

Standalone files can be loaded directly:

```python
from bunnyland.scripting import install_scripting, load_scripts

scripts = load_scripts(["examples/scripts/epoch_bell.json"])
runtime = install_scripting(actor, scripts)
```

To collect scripts from enabled plugins:

```python
from bunnyland.scripting import collect_scripts, install_scripting

scripts = collect_scripts(enabled_plugins)
runtime = install_scripting(actor, scripts)
```

If a script patches plugin-defined components, pass a component registry that includes
those plugins:

```python
from bunnyland.persistence import type_registries

component_registry, _edge_registry = type_registries(enabled_plugins)
runtime = install_scripting(actor, scripts, component_registry=component_registry)
```

Script execution state is separate from world persistence:

```python
from bunnyland.scripting import load_script_state, write_script_state

write_script_state("script-state.json", runtime.state)
state = load_script_state("script-state.json")
runtime = install_scripting(actor, scripts, state=state)
```

## Script Shape

```json
{
  "id": "examples.epoch_bell",
  "name": "Epoch Bell",
  "version": "0.1.0",
  "bindings": {
    "garden": "entity_12"
  },
  "blocks": [
    {
      "name": "fifth-second-bell",
      "priority": 0,
      "execution": "once",
      "cooldown_seconds": 0,
      "trigger": {
        "epoch_at_least": 5
      },
      "actions": []
    }
  ]
}
```

Blocks run in deterministic order: `priority`, then script id, then block name. Lower
priority values run first.

## Triggers

Triggers can be composed with `all`, `any`, and `not`:

```json
{
  "all": [
    { "epoch_at_least": 5 },
    {
      "any": [
        { "event_type": "ActorMovedEvent" },
        { "tick": true }
      ]
    }
  ]
}
```

Supported leaf predicates:

- `tick`: true on every world tick.
- `epoch_at_least`: true when `actor.epoch >= value`.
- `event_type`: true when a captured domain event has that class name or fully-qualified class name.
- `event_fields`: exact field matches for the matching event.

Example:

```json
{
  "event_type": "ActorMovedEvent",
  "event_fields": {
    "to_room_id": "$garden"
  }
}
```

Values beginning with `$` are binding references. Bindings can come from the script,
from `install_scripting(..., bindings={...})`, or from patch operations that bind newly
created entities.

## Execution Policy

`execution` controls repeat behavior:

- `once`: the block runs at most once.
- `always`: the block can run whenever its trigger matches.

`cooldown_seconds` prevents a block from firing again until that many game seconds have
elapsed since its last firing.

## Queries

Actions target entities with `EntityQuery`:

```json
{
  "components": ["CharacterComponent"],
  "without_components": ["SuspendedComponent"],
  "identity_name": "Juniper",
  "identity_kind": "character",
  "tags": ["quest"],
  "room_title": "North Tunnel",
  "in_room": "$garden",
  "controller_kind": "llm"
}
```

Component names are Python class names. `controller_kind` matches the current controller
behind the character's `ControlledBy` edge and can be `discord`, `llm`, `suspended`, or
`unknown`.

Fanout is explicit through `TargetSelector.mode`:

- `one`: require exactly one match, otherwise the action fails.
- `first`: use the deterministic first match by entity id.
- `each`: run the action once per matched entity.

## Actions

### `submit_command`

`submit_command` resolves target characters and submits normal `SubmittedCommand`s.
The runtime fills `controller_id` and `controller_generation` from the character's live
`ControlledBy` edge when the action runs.

```json
{
  "kind": "submit_command",
  "target": {
    "mode": "first",
    "query": {
      "components": ["CharacterComponent"],
      "controller_kind": "llm"
    }
  },
  "command_type": "say",
  "payload": {
    "text": "A bell rings."
  },
  "cost": {
    "action": 0,
    "focus": 0
  },
  "lane": "world",
  "on_insufficient_points": "queue"
}
```

The command runs on the next tick because script actions execute at the end of the
current tick.

### `patch_world`

`patch_world` is an admin-style action for deterministic setup and scripted events. It
mutates the ECS directly while the actor owns the world lock. Keep patch operations
small and explicit.

Supported operations:

- `add_entity`
- `add_component`
- `set_component_fields`

Example:

```json
{
  "kind": "patch_world",
  "operations": [
    {
      "op": "add_entity",
      "bind": "arrival_marker",
      "contain_in": {
        "components": ["RoomComponent"],
        "room_title": "North Tunnel"
      },
      "components": [
        {
          "type": "IdentityComponent",
          "fields": {
            "name": "a chalk arrival mark",
            "kind": "marker"
          }
        }
      ]
    }
  ]
}
```

`set_component_fields` replaces the full immutable component using the existing
component as a base:

```json
{
  "op": "set_component_fields",
  "target": {
    "mode": "one",
    "query": {
      "components": ["RoomComponent"],
      "room_title": "North Tunnel"
    }
  },
  "component_type": "RoomComponent",
  "fields": {
    "safe": false
  }
}
```

## Examples

Example standalone scripts live in `examples/scripts/`:

- `epoch_bell.json`: at epoch 5, the first LLM-controlled character says a line.
- `move_arrival_patch.json`: after the first move event, add a marker in North Tunnel.
- `llm_only_prompt.json`: at epoch 10, every LLM-controlled character says a line.

`examples/script-world-sets.json` pairs those scripts with deterministic world generator
names, seeds, and plugin ids.

## Current Limits

- Scripts are external runtime content; they are not saved inside the ECS world.
- Domain event triggers see events captured during the current tick. Commands submitted
  by scripts execute on the next tick.
- Multi-variable joins are intentionally not implemented yet. Use explicit `each` fanout
  and separate actions instead of implicit Cartesian products.
- `patch_world` supports only simple component/entity patches. More operations should be
  added as named, schema-validated patch types rather than a free-form mutation language.
