# Prompt Fragment Components

Bunnyland prompt fragments are projections from ECS state into short, deterministic lines
for a character prompt. Fragment providers still decide what is visible. Component methods
can format state after the provider has selected the entity/component that should be shown.
`PromptContext.persona` is the stable identity surface: the builder always includes
programmatic name, kind, and status facts, then appends plugin-provided persona fragments
for profile, relationships, and boundaries. Generic `prompt_fragments` remain in
`PromptContext.conditions` for changing mechanic state such as needs, weather, and local
services.
`PromptContext.social_cues` is a separate structured perception surface for nearby social
facts before prose narration: visible distress, recent arrivals/departures, nearby speech,
quiet characters, and unanswered player speech. These cues are derived from visible
characters plus recent room context; they are prompt facts, not world-state edits.
`ControllerDispatch` runs a deterministic persona contradiction guard over each tool call's
string arguments. It records name, relationship, and impossible self-claim issues on the
observable `Decision.persona_issues` while still submitting valid commands through the
normal command pipeline.
Memory-backed prompts keep recent notes and relevant recall separate. `PromptContext.notes`
shows the latest private notes, while `PromptContext.recall` keyword-searches the
character's memory collection using current location, visible entities, and recent room
context. Rendered recall lines include memory id, source, and score metadata for audit.
`PromptBuilder` bounds recall with `recall_limit`, `recall_budget_chars`, and
`recall_line_chars`; scored memories are considered in relevance order, low-priority noise
falls out first, and retained lines stay within the configured character budget.
`GoalDirectedAgent` uses the structured prompt context as a deterministic background
controller. It scores visible objects, visible characters, exits, and note-taking from
persona goals, contextual recall, current conditions, recent context, and notes. It emits
ordinary tool calls only when those scores line up with available prompt commands; dispatch
still resolves references, charges points, and lets handlers validate state changes.
`BehaviorProfileAgent` composes that goal policy with cheap fallback profiles: `idle`
waits, `social` opens friendly room speech, `timid` leaves when someone is nearby,
`aggressive` warns nearby characters, and `worker` picks up visible work items or moves to
the next available room. These profiles are deterministic controller policies, not new
verbs or hidden state mutation paths.
Relationship prompt facts feed the same cheap behavior layer. A visible character the
controller fears can trigger avoidance, fondness can trigger warm speech, and resentment or
dislike can trigger guarded speech before the generic profile fallback runs.

Narration follows the same boundary. `NarrationProjection` reads typed domain events,
`RoomSummaryProjection`, and per-character perception, then stores a volatile presentation
message for each viewer. It does not write ECS state. `SceneInput.facts` is the
visibility-filtered fact set a prose renderer consumes; source event ids and entity ids
make the presentation auditable without asking the model to decide what exists.
`SceneInput.clusters` groups visible event summaries by actor and room so lifecycle noise
does not become repeated prose beats. Deterministic salience weights keep important events
ahead of routine events; when a scene batch is noisy, low-salience event ids move to
`compressed_event_ids` with a compression fact instead of filling the prompt. Scenario
voice controls are stored as `NarrationVoice` metadata on the scene input. Voice changes
can alter renderer diction, but the structured facts and event ids are unchanged.
When renderer latency should not affect ticks, `NarrationProjection(non_blocking=True)`
queues delivery after the scene input is assembled. The queued job may use an async
renderer and falls back to deterministic `render_scene` on timeout or renderer failure;
the fallback is still a presentation of the same state facts, not a world-state update.
Use `evaluate_narration_quality(scene, text)` before subjective review of model prose. The
deterministic harness reports hidden-state leakage, obvious contradictions of visible
characters/objects/exits, omitted high-salience event summaries, and scenario voice drift.

## Context Shape

Component prompt methods receive a `ComponentPromptContext`:

```python
def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
    ...
```

The context deliberately stays small:

- `ctx.entity`: the entity carrying this component.
- `ctx.viewer`: the entity receiving the prompt, when known.
- `ctx.room`: the current room for `ctx.entity`, when known.
- `ctx.target`: an optional relationship target for edge-scoped formatting.
- `ctx.perspective`: prose style and future localization metadata.
- `ctx.can_view_private_state`: true when private component state is scoped to the
  prompt viewer, either because `ctx.entity` is the viewer or because `ctx.target` is.
- `ctx.room_siblings(component_type=None)`: lazy direct contents of `ctx.room`, excluding
  `ctx.entity`.
- `ctx.inventory_items(component_type=None)`: lazy direct contents of `ctx.entity`.

The lazy helpers only resolve entities when called. They cache their result for that context
so multiple component methods in the same prompt build can share the same snapshot.

Use `PerspectivePhrase` when a component needs first-, second-, and third-person variants.
It works for static phrase tables and simple named templates:

```python
LOW_FUEL = PerspectivePhrase(
    "My fuel is low: {current}/{maximum}.",
    "Your fuel is low: {current}/{maximum}.",
    "Their fuel is low: {current}/{maximum}.",
)

line = LOW_FUEL.render(ctx.perspective, current=2, maximum=10)
```

This helper is intentionally small. It reduces phrase-map boilerplate, but it does not make
large prompt migrations free: supporting multiple perspectives still means carrying more
text variants than a second-person-only provider. Prefer it when perspective differences are
real; keep a single literal string when all perspectives should say exactly the same thing.

## Responsibility Split

Fragment providers own selection and access:

- current character, current room, reachable entities, world markers, and relationship targets;
- reachability checks and hidden/private state checks;
- world queries and aggregate scans;
- resolving entity ids stored in component fields;
- sorting and preserving provider-level output order.

Component methods own formatting:

- convert this component's own fields into prompt lines;
- use `ctx.entity`, `ctx.room`, or `ctx.target` when the provider has already selected them;
- use `ctx.room_siblings(...)` or `ctx.inventory_items(...)` only when that local context is
  genuinely needed;
- return `()` when no line should be visible.

Do not put `World` queries, reachability rules, relationship traversal, or mutation inside
component prompt methods. If a line needs unrelated entities, broad aggregates, or id
resolution, keep it in the provider or a projection/helper.

## Private And Abstract State

Some components describe internal or abstract state: traits, preferences, goals, memories,
private plans, hidden attitudes, and similar data. These should usually be visible only when
the prompt viewer is the same entity being described:

```python
def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
    if not ctx.is_first_person:
        return ()
    ...
```

`ctx.is_first_person` is about access, not grammar. A self prompt may still use second-person
prose (`You are brave.`) while counting as first-person access because `ctx.viewer` is
`ctx.entity`.

Use `ctx.can_view_private_state` for private records that live on linked entities rather
than on the character itself. Bills, loans, known spells, accepted contracts, map markers,
heard rumors, installed implants, and similar relationship-owned or target-specific records
usually pass the viewer as `ctx.target`; they should remain visible to that viewer while
being hidden from an observer context where the target is someone else.

Visibility rules of thumb:

- Source-private state: feelings, traits, goals, skills, reputation, diseases, criminal
  heat, active plans, and relationship edges from the described entity use
  `if not ctx.is_first_person: return ()`.
- Target-private state: records or room/entity annotations that describe `ctx.target`'s
  progress, ownership, or knowledge use `if not ctx.can_view_private_state: return ()`
  before formatting the private line.
- Public or physical state: visible room objects, machine state, hazards, resources,
  doors, sites, public services, and broadly observable creature/room state can remain
  visible when the provider has selected that entity.
- Mixed state: keep the public line visible, but gate only the viewer-specific tag or
  state. Examples include showing an artifact as unidentified to outsiders while only the
  viewer sees their identified/studied/read status, or hiding an "installed" implant line
  unless the install target is the prompt viewer.

Physical or externally visible state, such as hunger pressure, injuries, carried items, or a
machine status, can be visible to other viewers if the provider has selected that entity and
the mechanic allows it.

## Migration Checklist

When migrating a large fragment provider:

1. Move pure one-component lines first.
2. Preserve existing strings and sorting unless the change intentionally tests new perspective
   behavior.
3. Keep provider logic for `reachable_ids(...)`, `container_of(...)`, relationship traversal,
   world marker scans, and component-field id resolution.
4. Add `if not ctx.is_first_person: return ()` to abstract/private component methods.
5. Use `ctx.room_siblings(...)` or `ctx.inventory_items(...)` for local direct contents only.
6. For edge-scoped text, have the provider pass the target entity through `ctx.target`.
7. Add focused component-method tests before migrating a whole provider.
8. Use `PerspectivePhrase` for repeated perspective variants, especially in table-driven
   component messages.

Good component-local candidates:

- `TraitSetComponent` formatting its own traits.
- `HungerComponent` formatting its own meter band.
- A visible `MachineComponent` formatting its own online/offline state.

Keep these provider-level:

- `OrbitComponent` resolving `body_id` to another entity name.
- stockpile load that scans contained resources;
- quest/contract visibility based on the viewer id;
- lines that combine multiple unrelated components or world queries.
