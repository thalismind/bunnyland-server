# Items, clues, and environmental storytelling

Items are where setting prose becomes reachable evidence. A lantern can block a route, oil
can become a contested resource, a ledger can preserve history, and medicine can make a
delivery objectively complete.

## Give each important item a job

Use four broad jobs when reviewing props:

| Job | Example | Required quality |
|-----|---------|------------------|
| Texture | wet ferry rope | reinforces place without implying a mechanic |
| Evidence | old crossing ledger | can be inspected or read repeatedly |
| Resource | lamp oil | scarce, portable, and consumed or transferred |
| Mechanism | ferry lantern | has visible state and a supported interaction |

An item can perform more than one job. The ledger provides atmosphere, evidence, and a way
to alter what characters believe. Decorative items are welcome, but a room full of generic
props can bury the objects that matter.

## Model physical identity first

Most objects begin with:

- `IdentityComponent` for a stable target name and kind;
- `DescriptionComponent` for short, long, and appearance text;
- one `Contains` edge from their physical parent.

Then add only the components that grant real state or affordances:

| Component | Meaning |
|-----------|---------|
| `PortableComponent` | characters can pick the object up |
| `HoldableComponent` or `WearableComponent` | it can be actively equipped |
| `ContainerComponent` | it can hold other entities |
| `ReadableComponent` | it carries persistent text that can be read |
| `WritableComponent` | characters can change its physical writing |
| `DoorComponent` | use toggles a door's open state |
| `ButtonComponent` | use presses or releases a mechanism control |
| `LockableComponent` and `KeyComponent` | a matching key can unlock it |
| Food, drink, fuel, tool, or package components | installed plugins expose their matching verbs |

Names and descriptions never grant mechanics. Calling something “an edible apple” does not
make `eat` work. Calling a brass disc “the lantern key” does not make it unlock anything.
Use the live editor catalogue to attach the component registered by the enabled plugin.

## Design containment as part of the story

Where an item begins changes the problem:

- in a room, it is immediately visible and reachable;
- in an open transparent container, it may be visible but still nested;
- in a locked container, the lock and key become part of the interaction;
- in a character's inventory, access becomes a social or control question;
- attached to a mechanism, it should not also appear loose elsewhere.

For Lantern Ferry, keep the dry wick in a work chest, oil in Fen's inventory or store
container, medicine in Rowan's inventory, and the ledger at the shrine. This distributes the
solution across physical, social, and informational play.

## Write clues that survive interpretation

A clue should identify what it is evidence **of**, without dictating the conclusion. Good
physical evidence has:

- a stable location or custody trail;
- inspectable text or state;
- names that match the people and places elsewhere in the world;
- enough specificity to influence a decision;
- a way to remain available or leave a record after being moved.

The crossing ledger might say that Fen delivered oil on the date Sable remembers being
abandoned. That proves a delivery was recorded. It does not prove who altered the lamp or why
the supplies disappeared.

Use readable signs, maps, labels, notices, receipts, and ledgers for required information.
Use flavor descriptions for mood. If reading is a required action, add readable state rather
than hiding the only clue in the generic long description.

## Make mutable state visible

If an object changes, players should be able to inspect the result. The lantern's component
state can determine whether it is lit or usable; a delivery ledger can gain a receipt; a
container can become empty; a button can stay pressed.

Avoid prose that permanently says “the chest is locked” when `ContainerComponent.locked` can
change. Let structured state remain authoritative and use derived projections, persistent
writing, or event consequences to describe it.

## Plan ownership and consumption

Decide what happens after use:

- Is the item consumed, depleted, damaged, or unchanged?
- Does it move to another inventory or container?
- Can it stack with identical supplies?
- Can the action be repeated safely?
- What evidence remains after the item disappears?

Consumables and spawned rewards need lifecycle discipline. Repeating a system or script
should not create an unbounded pile of one-use entities. Prefer quantities or stacks where
the mechanic supports them, and remove or transform exhausted entities through their
authoritative handler.

## Item review

- Every important item has a clear texture, evidence, resource, or mechanism job.
- Mechanical claims are backed by installed components, not names alone.
- Every object has one physical parent.
- Required clues remain readable and use consistent names.
- Mutable prose cannot contradict mutable component state.
- Consumption, transfer, depletion, and repetition have defined outcomes.
- Repeated play cannot leak endless temporary or supply entities.

The static world is now readable. Next, make its objects respond through
[Affordances, actions, and handlers](world-building-interactions.md).
