# Inventory and use

Inventory actions move portable items between the room, your character, and reachable
containers. Use actions operate on reachable items and mechanisms, sometimes with an item
from your inventory as the tool.

## Take, drop, and put

Pick up portable items from the current room, an open reachable inanimate container, or a
dead body:

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
- `take` never reaches into a living character's inventory, even when the character is
  visibly holding the item;
- an item must be in your inventory before you can drop or put it;
- name matching is case-insensitive and supports prefixes when the client resolves names.

Reaching into another character's inventory is a different physical and policy-sensitive
action. Worlds that enable the appropriate mechanic expose a separate `pickpocket` verb;
they do not change the meaning of ordinary `take`.

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

## Containers

Containers are world objects that can hold other items. Look or inspect first to find out
whether a container is reachable, open, closed, locked, or empty:

```text
!inspect oak chest
!open oak chest
!take brass key from oak chest
!put brass key in oak chest
!close oak chest
```

You can only remove from or add to containers your character can reach. Closed containers
usually need to be opened before inventory can move through them, and locked containers
need the right key or another package-specific way to unlock them. Container contents are
still server-side state: a client may offer a convenient target picker, but the command
must pass normal reachability and lock/open checks.

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
