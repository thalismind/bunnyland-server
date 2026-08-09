# Affordances, actions, and handlers

An affordance is a promise about what someone can do with an entity. Bunnyland keeps that
promise by exposing a typed action and validating it through a handler. This is the boundary
between evocative description and interactive world state.

## Start with existing verbs

Before inventing a new mechanic, check whether an installed action already expresses the
change:

- `look`, `inspect`, `move`, `take`, `drop`, `put`, `hold`, and `wear` handle ordinary
  presence and inventory;
- `use` handles core object affordances such as doors, buttons, locks, and keys;
- `read`, `write`, `eat`, `drink`, `rest`, `sleep`, `wake`, `say`, and `tell` work when the
  target and plugin state support them;
- sim packages add farming, crafting, work, travel, quest, civic, survival, and other verbs.

The live action catalogue is authoritative. An installed plugin registers components,
actions, schemas, and prompt fragments together. In the world editor, choose component and
edge types from that catalogue rather than copying a type from a world that used different
plugins.

## Think in state transitions

Write every interaction as:

```text
preconditions → attempted action → authoritative state change → visible event/evidence
```

For repairing the lantern:

```text
character can reach lantern + carries dry wick + oil is available
→ repair or use action
→ supplies consumed, lantern state repaired and lit
→ repair event, changed description/state, ferry notice updated
```

This exposes missing design. If there is no component that represents “repaired,” the
handler has nowhere durable to put the result. If no event or projection changes, observers
cannot know it happened. If supplies do not change, the action can create value from nothing.

## Use `use` for supported object affordances

The core `use` handler inspects reachable target components. It can toggle a door, press a
button, or unlock matching lock state with a key. It rejects unreachable items, targets, and
tools before applying a change.

Do not expect one generic `use` action to infer arbitrary fiction. A sentence like “this
shell summons the ferryman” does not create a summoning mechanic. Either express the effect
with an existing mechanism, use a deterministic script that reacts to an authoritative
event, or add a plugin action and handler.

## Prefer specific verbs for consequential choices

Use a specific action when its parameters, costs, rejection reasons, or outcomes differ
meaningfully from ordinary use. `accept-quest`, `fulfill-obligation`, `repair`, `trade`, and
`travel` communicate more than an opaque use target.

A well-designed handler should:

1. reject invalid or missing ids;
2. check reachability and required state;
3. validate tools, resources, permissions, and policy;
4. plan one atomic mutation;
5. emit a typed event describing what actually happened;
6. leave inspectable state for important consequences.

Handlers are rules, not narrative shortcuts. Human, scripted, behavior-tree, MCP, and LLM
controllers all submit the same action and pass through the same validation.

## Choose between components, scripts, and plugins

| Need | Best tool |
|------|-----------|
| Existing door, food, tool, quest, or sim behavior | attach the registered component and relationships |
| One-time or scheduled setup using existing commands | external script |
| Small deterministic world patch after an event | external script, with care |
| Reusable new verb or state machine | plugin component, action definition, handler, events, tests |
| Pure presentation | description or client display metadata |

Scripts can submit normal commands or apply narrow patches. A submitted command remains
subject to ordinary rules; a patch is an admin mutation and should not impersonate a
character action. Use a plugin when the behavior needs reusable validation, prompt context,
systems, or consequences.

## Make failure playable

Rejection is part of interaction design. “It is locked,” “matching key is required,” and
“target is not reachable” tell a player which world condition prevented the action. A vague
“nothing happens” is suitable only when no actionable distinction should be revealed.

Place enough evidence to recover:

- a lock visually matches or names its key family;
- an empty oil reservoir is inspectable;
- a tool requirement appears on a manual or workbench;
- policy or faction restrictions are visible before a costly attempt;
- another route or supplier can be discovered.

Do not turn a rejected action into a silent wait or an unrequested alternative. The player or
agent should decide what to try next.

## Account for cost and repetition

Actions may consume world or focus points. Expensive interactions should earn their cost
through consequence, information, or progress. Test the second and tenth use, not only the
first:

- Can a reward be claimed twice?
- Does each press spawn another permanent item?
- Does repair consume supplies only once?
- Can two characters race through the same transition safely?
- Does a failed attempt mutate partial state?

Atomic handlers and idempotent completion rules keep a persistent world healthy.

## Interaction review

- Every promised affordance maps to an installed action and real state.
- Each important action has explicit preconditions and persistent consequences.
- Generic `use` is reserved for supported component affordances.
- New mechanics use a plugin rather than prose inference.
- Rejections explain the blocking condition without choosing for the player.
- Human and autonomous controllers share the same validation path.
- Repeat and concurrency tests cannot duplicate rewards or leak entities.

Next, organize longer arcs in [Quests, goals, and obligations](world-building-quests.md).
