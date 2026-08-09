# Reading the world graph

The graph inspector is both a cartographer's table and a continuity debugger. It shows how
entities are actually connected, which can differ from what descriptions or memories claim.
Open the deployed inspector, authenticate for admin access, and connect to the live server or
load a snapshot file.

## Read each top-level view

| View | What it reveals | Questions to ask |
|------|-----------------|------------------|
| Map | rooms and directed exits | Are routes reciprocal, named, and intentionally gated? |
| Regions | geographic hierarchy | Does every room belong to the right place and scale? |
| Social | characters and social/categorical edges | Are bonds directed correctly and relationships plausible? |
| Quests | quests, objectives, rewards, status, acceptance | Is the arc structurally complete and current? |

Use the view that matches the design question. A complete map does not prove a valid quest
graph, and a clean social graph does not prove characters share a room.

## Drill into containment

Enter a room to see occupants, items, containers, and other contents. Enter a character to
see inventory and equipment. Open a container to follow nested contents.

Containment review catches common mistakes:

- an item with no physical parent;
- a character in the wrong room;
- one entity appearing under multiple parents;
- inventory accidentally marked as room content;
- a required item hidden inside an inaccessible or locked container;
- a region edge mistaken for physical reachability.

Turn on parent nodes when you need to understand how the selected entity fits into a larger
chain.

## Inspect components and outgoing edges

Selecting a node opens its ECS details. Compare structured state with the rendered story:

- Does the room description claim daylight while light state says otherwise?
- Is the “portable” wick actually carrying `PortableComponent`?
- Does a resolved quest still have an active goal on a participant?
- Does an overdue routine point to a place the character cannot know or reach?
- Does a controller badge match the intended human, LLM, scripted, behavioral, or suspended
  role?

Click relationship targets to follow causality. For a quest, inspect objective and reward
entities. For an obligation, follow debtor and creditor. For a character, follow controller,
home, social, ownership, and quest relationships.

## Use the event feed as a timeline

When connected live, enable events. The feed shows typed domain events independently of the
debounced graph refresh. Use it to correlate attempted play with authoritative change:

```text
character action
→ command result event
→ changed components or edges
→ consequence event
→ visible projection update
```

If dialogue announces a repair but no repair event or state change follows, the repair did
not happen. If an event fires repeatedly, inspect the driving component and whether completion
or cleanup ever changes it.

The feed is recent operational evidence, not permanent lore. Important outcomes still need
persistent state, records, history, or memory.

## Audit one expansion seam

Before adding content, select the anchor entity and trace outward:

1. For a new room, inspect the door, containing room, intended direction, and nearby region.
2. For a new character, inspect the room, existing cast, available controller, and needed
   resources.
3. For a new item, inspect the parent container, current custody, matching actions, and any
   quest dependency.
4. For a new event, inspect active incidents, open obligations, schedules, and current room
   population.

This context is exactly what a good LLM patch prompt should summarize.

## Look for graph smells

| Smell | Likely problem |
|-------|----------------|
| Many detached controllers | runtime controller cleanup or handoff lifecycle |
| Many uncontained portable items | spawn or consumption lifecycle |
| Several same-type edges to one singleton target role | missing cardinality enforcement |
| Quest children with no quest parent | orphaned objective or reward |
| Incident-spawned entities after resolution | cleanup consequence failure |
| Growing obligations with repetitive text | speech interpretation or resolution lifecycle |
| Rooms only reachable one way | accidental missing reciprocal exit |
| Character goal contradicts component state | stale authoring state |

Some entities, such as controllers, history records, obligations, and world services, are
intentionally not physically contained. “Uncontained” is only a smell when the entity's kind
should have an owner or parent.

## Inspector review

- Map, region, social, and quest views agree with the intended world.
- Containment paths explain where every physical entity is.
- Component state agrees with descriptions and claimed outcomes.
- Events correlate with real mutations and stop after completion.
- Controller badges and assignments match the intended cast.
- Expansion anchors have enough nearby context for a bounded addition.
- Unusual graph shapes have an explicit narrative or mechanical reason.

Next, use that context in [LLM-assisted world patches](world-building-llm-patches.md).
