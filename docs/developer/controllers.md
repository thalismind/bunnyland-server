# Behavior & scripted controllers

Most characters are driven by a human (Discord/web), an MCP agent, or an LLM agent. Two
additional controller kinds let you drive a character **deterministically, with no model
call**:

- **Behavioral** (`BehaviorControllerComponent`) — ticks a named [behavior tree](#behavior-trees)
  against the character's prompt context each turn and emits one tool call (or waits).
- **Scripted** (`ScriptedControllerComponent`) — replays a named, fixed sequence of tool
  calls turn by turn, optionally looping.

Both are *engine-driven*: like the LLM controller, the engine builds the character's prompt
context, asks the controller for a single tool call, then validates and costs the resulting
command on the next tick (see [`ControllerDispatch`](../../src/bunnyland/llm_agents/dispatch.py)).
They go through exactly the same reference resolution, persona checks, and cost gates as LLM
actions — they cannot bypass the rules. They are useful for background characters, demos,
tests, and reproducible playtests where a live model is unwanted.

Both reference their behaviour by name and persist as just that string; the actual trees and
scripts live in code-defined registries.

## Behavior trees

A behavior tree is ticked once per dispatch turn and yields a single `ToolCall` (or `None` to
wait). Nodes return `SUCCESS` or `FAILURE`; an `Action` node "succeeds" only when it produces
a tool call. The node types live in
[`llm_agents/behavior_tree.py`](../../src/bunnyland/llm_agents/behavior_tree.py):

- `Condition(predicate)` — succeeds (without acting) when `predicate(context)` is true.
- `Action(chooser)` — succeeds with the call `chooser(context)` returns, fails on `None`.
- `Sequence(*children)` — fails if any child fails; returns the first call produced.
- `Selector(*children)` — returns the first child that succeeds; fails if all fail.

Built-in trees: `idle` (always waits), `forager` (take a visible item, else move), `wanderer`
(take the first open exit), `greeter` (greet a visitor, else hold), and `guard` (warn a
visitor, else hold).

Register a custom tree once at startup:

```python
from bunnyland.llm_agents import register_behavior_tree
from bunnyland.llm_agents.behavior_tree import Action, BehaviorTree, Selector

register_behavior_tree(
    BehaviorTree("loiterer", Selector(Action(lambda ctx: None)))
)
```

## Scripts

A script is a fixed `tuple[ToolCall, ...]` replayed by `ScriptedAgent`. Built-in scripts are
deliberately minimal (`wait`, `patrol`, `greeter`); register world-specific scripts with
`register_script`:

```python
from bunnyland.llm_agents import register_script
from bunnyland.llm_agents import ToolCall

register_script(
    "north-loop",
    [ToolCall("move", {"direction": "north"}), ToolCall("move", {"direction": "south"})],
)
```

A scripted controller with `loop=True` repeats its sequence; otherwise the character waits
once the script is exhausted. Replay progress is tracked per character within the running
dispatch.

## Assigning these controllers

In a world proposal, set `controller` to `behavioral` or `scripted` and name the behaviour:

```python
CharacterSpec(key="forager", name="Forager", room_key="meadow",
             controller="behavioral", behavior_name="forager")
CharacterSpec(key="sentry", name="Sentry", room_key="gate",
             controller="scripted", script_name="north-loop", script_loop=True)
```

World validation rejects an unknown `behavior_name`/`script_name` at generation time. If a
name later becomes unresolvable (for example, after an admin patch), the dispatch logs it and
the character simply waits rather than crashing the game loop.

Like every controller, these can be swapped at runtime with the usual control verbs — control
changes bump the `ControlledBy` generation so stale commands are rejected.

## Loading definitions at runtime (the script editor)

Scripts and behavior trees can be authored as **data** and loaded into the registries while
the server runs — no code change or restart. The data models live in
[`llm_agents/specs.py`](../../src/bunnyland/llm_agents/specs.py):

- `ScriptSpec` — `{name, description, calls: [{name, arguments}]}`.
- `BehaviorTreeSpec` — `{name, description, root: <node>}`, where a node is
  `{kind: "sequence"|"selector"|"condition"|"action", ...}`. Composite nodes carry
  `children`; `condition`/`action` leaves name a **library** entry via `ref` and pass it
  `params`. Because trees can't carry code, leaves reference the fixed condition/action
  library rather than arbitrary callables.

Built-in leaf library:

- Conditions: `has_visible_objects`, `has_visible_characters`, `has_open_exit`.
- Actions: `take_first_item`, `move_first_exit`, `greet_first_character`,
  `warn_first_character`, `say` (params: `text` (required), `intent`, `approach`).

Extend the library from code with `register_condition(name, factory)` /
`register_action(name, factory)`, where a factory takes the leaf's JSON params and returns the
predicate/chooser.

### Server admin API

Start the server with `--controller-definitions <file.json>` to persist editor-loaded
definitions; they are re-registered on boot. The admin routes (gated like `/admin/world`):

- `GET /admin/controllers/definitions` — registered scripts/behaviors plus the authorable
  `condition_library`/`action_library` and the persisted `stored` set.
- `POST /admin/controllers/scripts` — body is a `ScriptSpec`.
- `POST /admin/controllers/behaviors` — body is a `BehaviorTreeSpec`.

Both POSTs validate (compile) the definition, register it into the live registries, persist it
to the store file, and return the updated listing. An invalid definition (unknown `ref`,
misplaced `ref`/`children`, bad params) returns `400`.

### MCP admin tools

The same actions are available over MCP: `list_controller_definitions_admin`,
`register_script_admin(name, calls, description)`, and
`register_behavior_admin(name, root, description)`. All require the MCP admin token.

### Persistence

`ControllerDefinitionStore` (a JSON file) holds the editor-loaded definitions. `load()`
re-registers everything on boot and skips any single entry that fails to compile (logged), so
one bad definition can't stop the server. Code-defined built-ins are not persisted — they are
always present in the registries. A store without a path is ephemeral (registers but does not
persist).
