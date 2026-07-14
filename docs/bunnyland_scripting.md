# Bunnyland Scripting Catalogue

This is the detailed catalogue for Bunnyland's external script engine. It documents the
current implemented scripting model, runtime lifecycle, JSON schema, deterministic
selection rules, actions, persistence boundary, extension points, and known limits.

Use this document the same way `bunnyland_mechanics.md` is used for mechanics: as the
place to understand what exists, what concepts mean, and how new work should fit the
engine. The shorter developer guide in `docs/developer/scripting.md` is a quick usage
guide. This file is the fuller reference.

## 1. Purpose and Scope

Bunnyland scripts are deterministic runtime content. They let tests, demos, plugins, and
scenario authors express simple world behavior outside Python code.

Scripts are useful for:

- deterministic test fixtures;
- scripted tutorial beats;
- demo-world events;
- scheduled prompts;
- small world mutations;
- plugin-provided scenarios;
- reproducible playtest setup.

Scripts are not:

- Python plugins;
- ECS entities;
- persisted world components;
- a replacement for mechanics packs;
- a general-purpose rules engine;
- a free-form world editor language.

The key design constraint is that scripts sit beside the ECS and command pipeline. A
script can submit normal commands or apply small admin-style patches, but it does not own
truth. Durable simulation state still belongs in ECS components, edges, systems, command
handlers, consequences, and domain events.

## 2. Implemented Source Surface

The current script engine lives in:

```text
src/bunnyland/scripting/__init__.py
src/bunnyland/scripting/model.py
src/bunnyland/scripting/runtime.py
```

The direct tests live in:

```text
tests/test_scripting.py
```

Example standalone scripts live in:

```text
examples/scripts/epoch_bell.json
examples/scripts/move_arrival_patch.json
examples/scripts/llm_only_prompt.json
```

Example script/world pairings live in:

```text
examples/script-world-sets.json
```

The public import surface is exported from `bunnyland.scripting`:

```python
from bunnyland.scripting import (
    AddComponentPatch,
    AddEntityPatch,
    CommandCostSpec,
    ComponentSpec,
    EntityQuery,
    ExecutionPolicy,
    FanoutMode,
    PatchWorldAction,
    ScriptBlock,
    ScriptBlockState,
    ScriptDefinition,
    ScriptRuntime,
    ScriptRuntimeError,
    ScriptState,
    SetComponentFieldsPatch,
    SubmitCommandAction,
    TargetSelector,
    Trigger,
    collect_scripts,
    install_scripting,
    load_script,
    load_script_state,
    load_scripts,
    write_script_state,
)
```

## 3. Mental Model

A script file defines one `ScriptDefinition`. A script contains named `ScriptBlock`
objects. Each block has:

- a trigger;
- zero or more actions;
- a priority;
- an execution policy;
- an optional cooldown.

At runtime, `ScriptRuntime` subscribes to all domain events and registers an after-tick
hook on a `WorldActor`. At the end of each actor tick, the runtime:

1. snapshots captured domain events from that tick;
2. clears the event buffer;
3. copies current runtime bindings;
4. orders every script block deterministically;
5. skips blocks that are ineligible because of `once` or cooldown state;
6. evaluates each eligible block's trigger;
7. runs the block actions if the trigger matches;
8. records block execution state only if all actions in the block succeed;
9. records block errors without crashing the actor tick.

Commands submitted by scripts enter the normal `WorldActor` command queue. They are not
handled immediately by the script runtime. Because scripts run at the end of a tick, a
script-submitted command is processed on a later tick.

Admin-style patches are different: `patch_world` actions mutate the ECS immediately
inside the after-tick runtime path while the actor owns the world.

## 4. Runtime Lifecycle

### 4.1 Constructing a runtime

The direct constructor accepts scripts, bindings, state, and a component registry:

```python
runtime = ScriptRuntime(
    scripts,
    bindings={"garden": str(garden_id)},
    state=previous_state,
    component_registry=component_registry,
)
```

Constructor behavior:

- `scripts` are stored as a tuple.
- Runtime-level `bindings` are copied first.
- Each script's own `bindings` are merged into the runtime bindings.
- Later script bindings can overwrite earlier binding names during construction.
- `state` defaults to a new empty `ScriptState`.
- `errors` starts as an empty list.
- `_events` starts as an empty event buffer.
- `component_registry` defaults to the built-in persistence type registry.

### 4.2 Installing on a WorldActor

```python
runtime = ScriptRuntime([script]).install(actor)
```

or:

```python
runtime = install_scripting(actor, [script], bindings={"room": str(room_id)})
```

Installation does two things:

- subscribes `runtime._capture_event` to `DomainEvent`;
- registers `runtime.run_tick` as an after-tick callback.

The runtime does not replace existing handlers, systems, controllers, or plugins. It only
observes events and runs after the actor tick.

### 4.3 Adding scripts after construction

```python
runtime.add_script(script)
```

This appends the script and merges that script's bindings into the runtime binding map.
It does not reset existing block state or errors.

### 4.4 Error handling

If a block action raises `ScriptRuntimeError`, the runtime appends a string to
`runtime.errors`:

```text
<script_id>:<block_name>: <error message>
```

The failed block is not marked fired. Later blocks can still run. The runtime does not
raise the error out of the actor tick.

Direct helper calls can still raise `ScriptRuntimeError` when used outside `run_tick`.
Tests intentionally exercise both paths.

## 5. Script Definition Schema

The top-level model is `ScriptDefinition`:

```json
{
  "id": "examples.epoch_bell",
  "name": "Epoch Bell",
  "version": "0.1.0",
  "bindings": {
    "garden": "entity_12"
  },
  "blocks": []
}
```

Fields:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | string | required | Stable script identifier. Used in block state keys. |
| `name` | string | `""` | Human-readable script name. |
| `version` | string | `"0.1.0"` | Script content version. Informational today. |
| `bindings` | object | `{}` | Named string values available as `$name` references. |
| `blocks` | array | `[]` | Ordered content units evaluated by the runtime. |

Guidelines:

- Use stable reverse-DNS-like or package-like ids, such as `examples.epoch_bell`.
- Do not rename a script id casually. It changes script state keys.
- Keep script bindings small and explicit.
- Prefer world-specific entity ids in install-time bindings when generated ids vary.

## 6. Script Blocks

The block model is `ScriptBlock`:

```json
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
```

Fields:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | string | required | Stable block name within the script. |
| `trigger` | object | required | Predicate deciding whether the block fires. |
| `actions` | array | `[]` | Actions to run when the block fires. |
| `priority` | integer | `0` | Lower values run first. |
| `execution` | `"once"` or `"always"` | `"once"` | Repeat policy. |
| `cooldown_seconds` | integer | `0` | Minimum game epoch spacing between firings. |

Block state keys use:

```text
<script_id>:<block_name>
```

For example:

```text
examples.epoch_bell:fifth-second-bell
```

Do not rename blocks casually if script state must survive reloads.

## 7. Deterministic Block Ordering

Every tick, the runtime flattens all blocks from all scripts and sorts them by:

```text
priority, script id, block name
```

Lower priority values run first. Ties are resolved by script id and block name. This
means execution is stable across runs as long as script ids and block names are stable.

Use priority only when one block must create bindings or world state before another
block runs in the same tick. Otherwise, leave `priority` at `0`.

## 8. Execution Policy and Cooldowns

### 8.1 `once`

`once` is the default. A `once` block fires at most one time. If its state count is
greater than zero, the runtime skips it before trigger evaluation.

```json
{
  "execution": "once"
}
```

### 8.2 `always`

`always` allows a block to fire every time it is eligible and its trigger matches.

```json
{
  "execution": "always"
}
```

Use `always` carefully. Pair it with a cooldown unless firing every tick is intentional.

### 8.3 `cooldown_seconds`

Cooldowns use the actor's game epoch. If a block last fired at epoch `5` and has
`cooldown_seconds` of `10`, it is ineligible until epoch `15`.

```json
{
  "execution": "always",
  "cooldown_seconds": 10
}
```

Cooldowns also affect `once` blocks, but a `once` block already stops after the first
successful firing.

## 9. Triggers

`Trigger` is a composable predicate. It must define at least one predicate through
validation.

Supported trigger fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `all` | array of triggers | True when every child trigger is true. |
| `any` | array of triggers | True when at least one child trigger is true. |
| `not` | trigger | True when the child trigger is false. |
| `tick` | boolean | True on every after-tick evaluation. |
| `epoch_at_least` | integer | True when `actor.epoch >= value`. |
| `event_type` | string | True when a captured domain event type matches. |
| `event_fields` | object | Exact field matches applied to event model data. |

### 9.1 Tick trigger

```json
{
  "tick": true
}
```

This trigger is true on every runtime after-tick evaluation.

### 9.2 Epoch trigger

```json
{
  "epoch_at_least": 5
}
```

This trigger is true once the actor's epoch is at least the given integer value.

The comparison is inclusive. If the actor jumps from epoch `0` to epoch `5`, the trigger
matches at epoch `5`.

### 9.3 Event type trigger

```json
{
  "event_type": "ActorMovedEvent"
}
```

`event_type` can match either:

- the event class name, such as `SpeechSaidEvent`;
- the fully-qualified class name, such as `bunnyland.core.events.SpeechSaidEvent`.

The runtime sees domain events captured during the current tick. It does not search old
events.

### 9.4 Event field matching

```json
{
  "event_type": "SpeechSaidEvent",
  "event_fields": {
    "text": "hello",
    "room_id": "$room"
  }
}
```

The runtime calls `event.model_dump()` and compares fields exactly. Bound values are
resolved before comparison. There is no substring, regex, numeric range, or nested query
language today.

### 9.5 Composed triggers

```json
{
  "all": [
    { "epoch_at_least": 5 },
    {
      "any": [
        { "event_type": "ActorMovedEvent" },
        { "tick": true }
      ]
    },
    {
      "not": {
        "epoch_at_least": 999
      }
    }
  ]
}
```

Composition short-circuits according to normal Python `all`, `any`, and `not`
semantics.

## 10. Bindings

Bindings are named string values. They are referenced in scripts with `$name`.

Bindings can come from:

- runtime construction;
- `install_scripting(..., bindings={...})`;
- `ScriptDefinition.bindings`;
- selectors with `bind`;
- `add_entity` operations with `bind`.

Value resolution rules:

- a string beginning with `$` is looked up by binding name without the dollar sign;
- if no binding exists, the original string is left unchanged;
- dictionaries are resolved recursively;
- lists are resolved recursively;
- other values are returned unchanged.

Example:

```json
{
  "payload": {
    "target_id": "$arrival_marker",
    "text": ["literal", "$room"]
  }
}
```

If `room` is bound to `entity_12`, this resolves to:

```json
{
  "target_id": "$arrival_marker",
  "text": ["literal", "entity_12"]
}
```

`target_id` stays unresolved if `arrival_marker` has not been bound yet.

### 10.1 Binding lifetime

During one tick, each fired block starts with a copy of current bindings. New bindings
created by selectors or patches are visible to later actions in the same block.

After a block succeeds, new bindings created during that block are merged into
`runtime.bindings` and into the tick-local binding copy used by later blocks.

If a block fails, it is not marked fired and its new bindings are not committed.

### 10.2 Binding names

Use short, semantic names:

```text
room
actor
arrival_marker
quest_item
```

Avoid reusing generic names across unrelated blocks when later blocks depend on them.
The default selector bind is `actor`, so set `bind` explicitly when that would be
misleading.

## 11. Entity Queries

Actions find entities through `EntityQuery`.

```json
{
  "id": "$room",
  "components": ["RoomComponent"],
  "without_components": ["CharacterComponent"],
  "identity_name": "Juniper",
  "identity_kind": "character",
  "tags": ["friend", "scout"],
  "room_title": "Mosslit Burrow",
  "in_room": "$room",
  "controller_kind": "llm"
}
```

Fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Direct entity id or binding reference. |
| `components` | array of strings | Required component class names. |
| `without_components` | array of strings | Component class names that must be absent. |
| `identity_name` | string | Exact `IdentityComponent.name` match. |
| `identity_kind` | string | Exact `IdentityComponent.kind` match. |
| `tags` | array of strings | Required subset of `IdentityComponent.tags`. |
| `room_title` | string | Exact `RoomComponent.title` match. |
| `in_room` | string | Entity id or binding reference for the containing room. |
| `controller_kind` | string | Current controller kind for a character. |

Query behavior:

- If `id` is present, the candidate set is only that entity.
- If `id` is invalid or missing from the world, the query returns no matches.
- If `id` is absent, all world entities are candidates.
- Component names resolve through the runtime component registry.
- Unknown component names raise `ScriptRuntimeError`.
- Results are sorted by entity id string.

### 11.1 Component filters

```json
{
  "components": ["CharacterComponent"],
  "without_components": ["PortableComponent"]
}
```

`components` requires every listed component. `without_components` rejects any entity
with a listed component.

Component names are Python class names registered in the component registry, not plugin
ids or action names.

### 11.2 Identity filters

```json
{
  "identity_name": "Hazel",
  "identity_kind": "character",
  "tags": ["friend"]
}
```

Any identity-related filter requires the entity to have `IdentityComponent`. Tags are a
subset check: an entity with `("friend", "scout")` matches `["friend"]`.

### 11.3 Room title filter

```json
{
  "room_title": "North Tunnel"
}
```

This requires `RoomComponent` and exact title equality.

### 11.4 Containment filter

```json
{
  "in_room": "$garden"
}
```

This compares the entity's current container id against the resolved room id using
`container_of(entity)`. Invalid room ids do not match anything.

### 11.5 Controller-kind filter

```json
{
  "components": ["CharacterComponent"],
  "controller_kind": "llm"
}
```

Supported values:

```text
discord
llm
suspended
unknown
```

The runtime follows the character's current `ControlledBy` edge. If there is no
controller, or if the controller entity is missing, the internal kind is `None` and will
not match any `controller_kind`.

`unknown` means the character has a controller entity, but that entity lacks the known
Discord, LLM, or suspended controller components.

### 11.6 Bounded graph selectors

Trusted scripts can use a graph selector when one entity filter is not enough:

```json
{
  "graph": {
    "terms": [
      {"kind": "edge", "source": "room", "edge": "Contains", "target": "person"},
      {"kind": "component", "variable": "person", "component": "CharacterComponent"}
    ],
    "bindings": {"room": "$room"},
    "select": ["room", "person"]
  },
  "target_variable": "person",
  "mode": "each"
}
```

Component and edge names must be exported by enabled plugins. Every selected variable is
available to the action as a binding. Queries must be connected and stay within eight terms,
six variables, 100 rows, and 10,000 candidate expansions. OR, negation, optional terms,
recursive traversal, numeric comparisons, and arbitrary predicates are not supported.
Legacy `EntityQuery` selector JSON is unchanged.

## 12. Target Selectors and Fanout

Actions do not use queries directly. They use `TargetSelector`, which wraps a query with
fanout behavior.

```json
{
  "mode": "one",
  "bind": "actor",
  "query": {
    "components": ["CharacterComponent"],
    "identity_name": "Juniper"
  }
}
```

Fields:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query` | `EntityQuery` | required | Query to resolve. |
| `mode` | `"one"`, `"first"`, `"each"` | `"one"` | Fanout policy. |
| `bind` | string | `"actor"` | Binding name for selected entity ids. |

### 12.1 `one`

`one` requires exactly one match.

```json
{
  "mode": "one",
  "query": { "identity_name": "Juniper" }
}
```

If the query returns zero or more than one entity, the action fails with:

```text
selector '<bind>' expected one match, found <count>
```

### 12.2 `first`

`first` requires at least one match and uses the deterministic first entity by id.

```json
{
  "mode": "first",
  "query": { "components": ["CharacterComponent"] }
}
```

If there are no matches, the action fails with:

```text
selector '<bind>' found no matches
```

### 12.3 `each`

`each` runs the action once for every match.

```json
{
  "mode": "each",
  "query": {
    "components": ["CharacterComponent"],
    "controller_kind": "llm"
  }
}
```

Zero matches are allowed. In that case, the action performs no work and does not fail.

For `each`, the selector bind is updated before each per-target action. After the action
finishes, the last selected entity id remains in the block-local bindings. If there are
zero matches, no selector binding is added.

## 13. Actions

The current action union supports:

```text
submit_command
patch_world
```

Actions are discriminated by `kind`.

## 14. `submit_command`

`submit_command` submits normal Bunnyland commands for selected characters.

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
    "text": "A small brass bell rings on the fifth second."
  },
  "cost": {
    "action": 0,
    "focus": 0
  },
  "lane": "world",
  "on_insufficient_points": "queue",
  "expires_after_seconds": null
}
```

Fields:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `kind` | `"submit_command"` | required | Action discriminator. |
| `target` | `TargetSelector` | required | Characters that will submit the command. |
| `command_type` | string | required | Existing command type, such as `say` or `move`. |
| `payload` | object | `{}` | Command payload after binding resolution. |
| `cost` | object | action/focus zeroes | Command cost. |
| `lane` | command lane | `"world"` | Command queue lane. |
| `on_insufficient_points` | policy | `"queue"` | Command point handling policy. |
| `expires_after_seconds` | integer or null | `null` | Relative expiry from current actor epoch. |

Runtime behavior:

1. Resolve the target selector.
2. For each target, bind the selected character id to `target.bind`.
3. Read the character's current `ControlledBy` edge.
4. Fail if the character has no controller id or generation.
5. Resolve payload bindings.
6. Create a `SubmittedCommand`.
7. Submit it to `WorldActor.submit`.

Important consequences:

- Commands go through the normal command pipeline.
- Controller id and generation are taken from the live character at execution time.
- Policy gates, point spending, handlers, consequences, and events still apply later.
- A submitted command runs on a future tick, not inside the script action.

### 14.1 Command cost

```json
{
  "cost": {
    "action": 1,
    "focus": 0
  }
}
```

Costs are copied into `CommandCost`. The command pipeline decides whether the character
can pay, queues, rejects, or expires according to normal command behavior.

### 14.2 Expiration

```json
{
  "expires_after_seconds": 30
}
```

If present, the runtime computes:

```text
expires_at_epoch = actor.epoch + expires_after_seconds
```

If omitted or null, the submitted command has no script-provided expiration.

## 15. `patch_world`

`patch_world` applies small ECS mutations directly.

```json
{
  "kind": "patch_world",
  "operations": []
}
```

Supported operations:

```text
add_entity
add_component
set_component_fields
```

This action is intentionally narrow. Use it for deterministic setup and scripted events,
not for implementing reusable mechanics.

## 16. Patch Operation: `add_entity`

`add_entity` creates a new entity with optional components, optional containment, and an
optional binding.

```json
{
  "op": "add_entity",
  "bind": "arrival_marker",
  "contain_in": {
    "components": ["RoomComponent"],
    "room_title": "North Tunnel"
  },
  "containment_mode": "room_content",
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
```

Fields:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `op` | `"add_entity"` | required | Operation discriminator. |
| `bind` | string or null | `null` | Binding name for the new entity id. |
| `components` | array | `[]` | Components to construct on the new entity. |
| `contain_in` | `EntityQuery` or null | `null` | Container query. Must resolve to exactly one entity. |
| `containment_mode` | string | `"room_content"` | `ContainmentMode` value for the `Contains` edge. |

Runtime behavior:

1. Build every component from `ComponentSpec`.
2. Spawn the entity with `spawn_entity`.
3. If `bind` is present, bind it to the new entity id.
4. If `contain_in` is present, resolve it as an entity query.
5. Require exactly one container match.
6. Add a `Contains` relationship from the container to the new entity.

Failure cases:

- unknown component type;
- invalid component fields;
- `contain_in` resolves to zero or multiple entities;
- invalid `containment_mode`.

## 17. Patch Operation: `add_component`

`add_component` adds or replaces one component on selected entities.

```json
{
  "op": "add_component",
  "target": {
    "mode": "one",
    "query": {
      "identity_name": "Juniper"
    }
  },
  "component": {
    "type": "IdentityComponent",
    "fields": {
      "name": "Juniper",
      "kind": "character"
    }
  }
}
```

Runtime behavior:

1. Resolve the selector.
2. For each selected entity, bind `target.bind` to the entity id.
3. Build the component.
4. Apply it with `replace_component`.

Because Relics ECS allows only one component of each type per entity, this operation
replaces the existing component of that type if present. It does not create multiple
components of the same class.

Use this operation sparingly on existing core state. Prefer command handlers for normal
player-facing state changes.

## 18. Patch Operation: `set_component_fields`

`set_component_fields` replaces a component by copying the existing immutable component
and changing selected fields.

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

Runtime behavior:

1. Resolve the selector.
2. Resolve the component type.
3. For each selected entity, bind `target.bind` to the entity id.
4. Require the entity to already have the component.
5. Resolve field bindings.
6. Build a replacement with `dataclasses.replace`.
7. Apply it with `replace_component`.

Failure cases:

- selector failure for `one` or `first`;
- unknown component type;
- selected entity lacks the component;
- invalid field name or value for the component.

## 19. Component Specs

Patch operations construct components through `ComponentSpec`.

```json
{
  "type": "IdentityComponent",
  "fields": {
    "name": "arrival bell",
    "kind": "item"
  }
}
```

Fields:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `type` | string | required | Component class name in the registry. |
| `fields` | object | `{}` | Constructor fields after binding resolution. |

The runtime calls:

```python
component_type(**fields)
```

This means field names and values must match the component constructor exactly.

## 20. Component Registry

The script runtime needs a name-to-component registry for:

- query `components`;
- query `without_components`;
- `ComponentSpec.type`;
- `set_component_fields.component_type`.

By default, the runtime uses:

```python
type_registries()[0]
```

When plugin-defined components are involved, pass the registry built from enabled
plugins:

```python
from bunnyland.persistence import type_registries

component_registry, _edge_registry = type_registries(enabled_plugins)
runtime = install_scripting(
    actor,
    scripts,
    component_registry=component_registry,
)
```

If the registry does not contain a component name, the runtime raises:

```text
unknown component <Name>
```

## 21. Script State

Execution state is represented by `ScriptState`:

```json
{
  "blocks": {
    "examples.epoch_bell:fifth-second-bell": {
      "count": 1,
      "last_fired_epoch": 5
    }
  }
}
```

Each block has `ScriptBlockState`:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `count` | integer | `0` | Successful firing count. |
| `last_fired_epoch` | integer or null | `null` | Actor epoch at last successful firing. |

State is updated only after all actions in a block succeed.

## 22. Persistence Boundary

Script state is not stored inside the ECS world. Persist it separately:

```python
from bunnyland.scripting import load_script_state, write_script_state

write_script_state("script-state.json", runtime.state)
state = load_script_state("script-state.json")
runtime = install_scripting(actor, scripts, state=state)
```

Standalone helpers:

```python
script = load_script("examples/scripts/epoch_bell.json")
scripts = load_scripts(["examples/scripts/epoch_bell.json"])
write_script_state("script-state.json", runtime.state)
state = load_script_state("script-state.json")
```

The world save and script state can drift if one is restored without the other. Scenario
runners should version and restore them together when repeatability matters.

## 23. Plugin Contributions

Plugins can contribute scripts through `ContentContribution.scripts`.

Accepted contribution values:

- `ScriptDefinition` instances;
- paths as `str` or `Path`;
- mappings accepted by `ScriptDefinition.model_validate`.

Example:

```python
from bunnyland.plugins import ContentContribution, Plugin
from bunnyland.scripting import ScriptDefinition

script = ScriptDefinition.model_validate(
    {
        "id": "plugin.script",
        "blocks": [
            {
                "name": "tick",
                "trigger": {"tick": True},
            }
        ],
    }
)

plugin = Plugin(
    id="example",
    name="Example",
    content=ContentContribution(
        scripts=(
            script,
            "examples/scripts/epoch_bell.json",
            {
                "id": "plugin.mapping",
                "blocks": [{"name": "tick", "trigger": {"tick": True}}],
            },
        )
    ),
)
```

Collect scripts from enabled plugins:

```python
from bunnyland.scripting import collect_scripts

scripts = collect_scripts(enabled_plugins)
```

Unsupported contribution values raise `ScriptRuntimeError` with an unsupported
contribution message.

## 24. Relationship to the Command Engine

Scripts that use `submit_command` do not bypass normal command behavior.

The submitted command still carries:

- `command_id`;
- `character_id`;
- `controller_id`;
- `controller_generation`;
- `command_type`;
- `payload`;
- `cost`;
- `lane`;
- `on_insufficient_points`;
- `submitted_at_epoch`;
- `expires_at_epoch`.

The command then goes through the same world actor path as human, Discord, MCP, TUI, or
LLM commands.

This matters because handlers still enforce:

- reachability;
- point costs;
- controller generation;
- command queue behavior;
- validation order;
- policy gates;
- consequences;
- event emission.

Use `submit_command` whenever a script is trying to make a character do something that
already exists as a verb.

## 25. Relationship to ECS Patching

Scripts that use `patch_world` bypass command handlers. They directly add entities,
add or replace components, and change component fields.

This is acceptable for:

- deterministic setup;
- non-player scenario beats;
- adding a marker, clue, note, or prop;
- minor world state changes that have no player-facing command;
- tests that need specific state.

This is not appropriate for:

- implementing a reusable mechanic;
- bypassing validation that players must obey;
- changing shared state in complex ways;
- creating hidden second instances of the same component type;
- long-running simulation rules.

If behavior needs custom validation, commands, events, prompt fragments, systems, or
mechanics-package reuse, make it a plugin mechanic instead.

## 26. Determinism Rules

The engine keeps script behavior deterministic through:

- stable block ordering by priority, script id, and block name;
- query results sorted by entity id string;
- explicit fanout modes;
- exact trigger and field matching;
- explicit binding names;
- state keys derived from stable ids.

Avoid relying on:

- generated entity ids unless they are bound or passed in;
- broad `first` selectors over large worlds;
- room titles that may be generated differently;
- command side effects happening in the same tick as script submission;
- unversioned script id or block name changes.

## 27. Examples

### 27.1 Scheduled command

At epoch 5, the first LLM-controlled character says a line:

```json
{
  "id": "examples.epoch_bell",
  "name": "Epoch Bell",
  "version": "0.1.0",
  "blocks": [
    {
      "name": "fifth-second-bell",
      "trigger": {
        "epoch_at_least": 5
      },
      "execution": "once",
      "actions": [
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
            "text": "A small brass bell rings on the fifth second."
          }
        }
      ]
    }
  ]
}
```

### 27.2 Event-triggered patch

After the first move event, add an arrival marker in the North Tunnel:

```json
{
  "id": "examples.move_arrival_patch",
  "name": "Move Arrival Patch",
  "version": "0.1.0",
  "blocks": [
    {
      "name": "leave-arrival-marker",
      "trigger": {
        "event_type": "ActorMovedEvent"
      },
      "execution": "once",
      "actions": [
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
                },
                {
                  "type": "PortableComponent",
                  "fields": {
                    "can_pick_up": false
                  }
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

### 27.3 LLM-only fanout

At epoch 10, every LLM-controlled character says the same line:

```json
{
  "id": "examples.llm_only_prompt",
  "name": "LLM Only Prompt",
  "version": "0.1.0",
  "blocks": [
    {
      "name": "llm-character-notice",
      "trigger": {
        "epoch_at_least": 10
      },
      "execution": "once",
      "actions": [
        {
          "kind": "submit_command",
          "target": {
            "mode": "each",
            "query": {
              "components": ["CharacterComponent"],
              "controller_kind": "llm"
            }
          },
          "command_type": "say",
          "payload": {
            "text": "Only the LLM-controlled characters hear this scheduled prompt."
          }
        }
      ]
    }
  ]
}
```

## 28. Current Implemented Catalogue

### Models

```text
ExecutionPolicy
FanoutMode
EntityQuery
TargetSelector
Trigger
CommandCostSpec
SubmitCommandAction
ComponentSpec
AddEntityPatch
AddComponentPatch
SetComponentFieldsPatch
PatchWorldAction
ScriptBlock
ScriptDefinition
ScriptBlockState
ScriptState
```

### Runtime services

```text
ScriptRuntime
install_scripting
collect_scripts
load_script
load_scripts
write_script_state
load_script_state
```

### Trigger predicates

```text
tick
epoch_at_least
event_type
event_fields
all
any
not
```

### Action kinds

```text
submit_command
patch_world
```

### Patch operations

```text
add_entity
add_component
set_component_fields
```

### Selector fanout modes

```text
one
first
each
```

### Query filters

```text
id
components
without_components
identity_name
identity_kind
tags
room_title
in_room
controller_kind
```

## 29. Current Limits and Non-Goals

Implemented limits:

- Script definitions are JSON-serializable Pydantic models, not Python callbacks.
- Script execution state is separate from ECS world persistence.
- Domain event triggers only inspect events captured during the current tick.
- Commands submitted by scripts execute on a later tick.
- Event field matching is exact equality only.
- Entity queries do not support joins across multiple bound variables.
- Entity queries do not support numeric comparisons, regex matching, or nested component
  field predicates.
- `patch_world` supports only entity creation, component add/replace, and component field
  replacement.
- Patch operations do not emit custom script events.
- Script ids and block names are the only state-key namespace.
- There is no built-in migration system for script state.
- Runtime errors are accumulated as strings in `runtime.errors`.

Non-goals:

- Do not make scripts a second mechanics system.
- Do not implement complex validation in JSON when a command handler belongs in Python.
- Do not store scripts as components on world entities.
- Do not add free-form Python execution.
- Do not let scripts silently bypass player-visible rules for reusable gameplay.

## 30. Extension Guidance

When adding scripting features, keep these rules:

- Add schema-validated model fields or new discriminated action/patch types.
- Preserve deterministic ordering.
- Keep selector behavior explicit.
- Keep error messages stable enough for tests.
- Add direct tests in `tests/test_scripting.py`.
- Add example JSON when the feature is user-visible.
- Update this catalogue and `docs/developer/scripting.md`.
- If plugin-defined components are involved, test component registry behavior.
- Prefer named operations over generic mutation blobs.

Good future additions would be:

- more patch operations with narrow schemas;
- explicit event emission operations if tests need them;
- safer component field predicates;
- script-state migrations;
- script validation tooling;
- editor metadata for block editors.

Risky additions would be:

- arbitrary expression languages;
- implicit multi-entity joins;
- hidden global state;
- patch operations that bypass ECS helper invariants;
- stringly-typed mutations that can target any internal attribute.

## 31. Testing Expectations

For script engine changes, use `tests/test_scripting.py` as the first layer.

Cover:

- Pydantic model validation;
- trigger truth tables;
- event field matching;
- binding resolution;
- selector modes;
- query filters;
- controller-kind filters;
- command submission;
- patch operations;
- state round trips;
- plugin contribution collection;
- runtime error recording;
- unknown component and invalid operation rejection.

Use E2E tests only when the behavior requires full actor ticks, command processing, or
plugin/controller lifecycle.

Default focused command:

```bash
uv run -m pytest tests/test_scripting.py
```

Before merging code changes that affect scripting behavior, also run the repository
default checks:

```bash
scripts/test-all
uv run ruff check src tests
git diff --check
```
