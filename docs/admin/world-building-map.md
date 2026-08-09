# Regions, rooms, and routes

A Bunnyland map is a graph, not a painted backdrop. Rooms are places where characters can be
present and act. Regions organize larger geography. Directed exits say which movement is
actually possible.

## Choose the right scale

Make a room when location changes what a character can perceive, reach, or do. Two areas can
share a room when moving between them would add no meaningful decision. Split them when the
boundary affects privacy, danger, weather, access, social context, or available objects.

For the Lantern Ferry, a useful first map is:

```text
Store Room — Village Bank — Ferry Landing — Lantern Platform
                    |
                Reed Path
                    |
                Marsh Shrine
```

Six rooms are enough for a route choice, a social hub, a supply source, a mechanism, and a
secret-bearing location. More rooms would increase travel and prompt context before they add
story.

## Build regions as readable hierarchy

A region entity uses `RegionComponent`. A region contains rooms or smaller regions through a
`Contains` edge whose `mode` is `region`.

Useful region kinds include district, village, province, biome, building, floor, ship, deck,
planet, dungeon level, or jurisdiction. The `kind` field is setting data rather than a fixed
taxonomy.

For the example:

| Region | Kind | Contents | Narrative job |
|--------|------|----------|---------------|
| Bracken Reach | district | village and marsh regions | names the whole scenario |
| Ferry Village | village | store, bank, landing | social and commercial pressure |
| Reedwater Marsh | wetland | reed path, shrine, platform | weather, isolation, hidden history |

Do not use a region as physical inventory. Region containment groups geography; room,
inventory, and container containment describe physical reachability.

## Give every room a job

At minimum, a room normally carries:

- `RoomComponent` for its stable targetable title, biome, indoor/private/safe state;
- `DescriptionComponent` for sensory and explanatory prose when the title is not enough;
- containment edges to its visible contents;
- outgoing `ExitTo` edges for movement.

Write a one-line job before writing description:

| Room | Job |
|------|-----|
| Village Bank | introduce the public problem and connect three routes |
| Store Room | hold oil and stage the trust conflict |
| Ferry Landing | show the closed crossing and stranded courier |
| Lantern Platform | host the repair interaction |
| Reed Path | expose weather and alternate evidence |
| Marsh Shrine | hold the ledger and old promise |

If two rooms have the same job, merge them or give them different constraints.

## Write descriptions for decisions

The short description should establish the room quickly. The long description can name
landmarks, state, and sensory details. Do not claim mutable facts that components may later
contradict. “The lantern hangs from a black iron hook” is stable; “the lantern burns brightly”
becomes wrong as soon as it is extinguished unless a projection derives that line from state.

Put critical directions in persistent objects or exit labels as well as prose. A returning
player should be able to reconstruct the route at the junction where the decision occurs.

## Connect routes deliberately

`ExitTo` is directed. A normal two-way path needs one edge in each direction. This supports
real one-way travel such as drops, portals, turnstiles, or evacuation routes, but it also makes
accidental one-way exits possible.

Each exit can carry:

| Field | Use |
|-------|-----|
| `direction` | stable command word such as east, downriver, or gangway |
| `label` | human-readable destination or route name |
| `locked` | whether normal movement is blocked |
| `hidden` | whether undiscovered projections omit it |
| `action_cost` | relative effort to traverse it |

Use consistent names. If a quest says “Lantern Platform,” the room title, sign, dialogue, and
exit label should not alternate among “light tower,” “beacon,” and “upper dock.” Colorful
synonyms are good prose but poor navigation keys.

## Place contents with `Contains`

Containment is an edge from container to contained entity:

- region to room uses `region`;
- room to visible occupant or object uses `room_content`;
- character to carried item uses `inventory`;
- container to stored item uses `container`.

An entity should have one physical parent. If the oil flask appears in both the store and
Sable's inventory, you have duplicated state rather than established two points of view.

## Reveal topology through the world

Add signs, directories, maps, posted schedules, landmarks, and residents who can repeat
directions. These survive across browser, terminal, Discord, and LLM projections better than
client-only highlights.

Use hidden exits for discoveries, not for mandatory information with no clue. A concealed
marsh path might be suggested by muddy footprints, a map, local dialogue, and a `hidden`
route. If the path is the only way to finish the scenario, provide more than one recoverable
clue.

## Map review

- Every room has a distinct gameplay or narrative job.
- Region hierarchy clarifies the setting without changing physical reachability.
- Ordinary routes have reciprocal exits.
- Intentional one-way routes have an in-world warning or recovery path.
- Required destinations use consistent names everywhere.
- Objects and characters have exactly one physical containment parent.
- Required routes can be rediscovered after the first visit.
- Travel length creates decisions rather than empty delay.

Next, populate the map with people in
[Characters and dramatic roles](world-building-characters.md).
