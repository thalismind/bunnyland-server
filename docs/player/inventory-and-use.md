# Inventory and use

Inventory actions move portable items between the room, your character, and reachable
containers. Use actions operate on reachable items and mechanisms, sometimes with an item
from your inventory as the tool.

## Take, drop, and put

Pick up portable items from the current room, your inventory, or an open reachable
container:

```text
!take a scrap of paper
!get three berries
!pick up brass key
```

Drop an item from your inventory into the current room:

```text
!drop a scrap of paper
```

Put an inventory item into a reachable open container:

```text
!put a scrap of paper in an oak chest
```

Inventory rules:

- non-portable items cannot be picked up;
- closed containers do not allow removal or adding;
- an item must be in your inventory before you can drop or put it;
- name matching is case-insensitive and supports prefixes when the client resolves names.

## Hold, wear, and remove

Hold tools and wear clothing from your inventory when an item supports it:

```text
!hold garden hoe
!unhold garden hoe
!wear straw hat
!remove straw hat
```

Holding and wearing are state changes on your character. They can matter to mechanics
that check equipped tools, clothing, armor, or other carried gear.

## Use objects

Use reachable mechanisms and objects:

```text
!use burrow door with brass key
!use burrow door
```

The first command can unlock a matching lock. The second can open or close the door.
For item-driven use, the item is the thing being used; the target is who or what it is
used on:

```text
!use first-aid kit
!use first-aid kit on Juniper
```

When an item use has no target, it usually means using the item on yourself, or using a
world item that does not need a separate target. If the phrasing would be ambiguous,
prefer `with` for a tool:

```text
!use locked crate with brass key
```

You can also address common affordances explicitly:

```text
!unlock burrow door with brass key
!open burrow door
!close burrow door
!lock burrow door with brass key
```

## Write and read marks

Write on reachable writable objects:

```text
!write Meet at dawn on blank sign
```

Writing changes the physical object, unlike private notes. Significant writing also
creates a physical mark, creator signature, and shared world history, so later prompts can
cite who marked an object after a save and reload. Inspecting the object still shows the
readable text.

## Rest, wait, and talk

Sleep changes your character's state until they wake:

```text
!sleep
!wake
```

Wait yields a turn:

```text
!wait
```

Speak to everyone awake and active in the room:

```text
!say Hello, burrow.
```

Talk directly to one present character:

```text
