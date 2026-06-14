# Getting started

This guide covers the basic actions every player uses: looking around, moving between rooms, carrying items, and talking to other characters. These are core verbs, so they are available in normal worlds even before the larger sim packages matter.

## Look around

Looking is read-only. It shows your current room summary, visible characters and objects, exits, and inventory. It does not spend an action or change the world.

In Discord, use:

```text
!look
```

In the web inspector or an agent prompt, the same information appears as the current room summary:

```text
Location:
Mosslit Burrow

You can see:
- Juniper
- three berries
- a scrap of paper

Exits:
- north

You are carrying:
- a scrap of paper
```

If something is not shown in the room summary or your inventory, your character usually cannot target it by name.

## Narration

Some clients and scenarios can show narration after a turn. Narration is a presentation of
what your character can currently perceive: nearby events, the room summary, visible
characters and objects, and exits. It does not create facts or change the world.

If another character acts in a different room, or an object is hidden from your character,
that remote or hidden fact should not appear in your narration.

## Move

Move through an exit by direction:

```text
!go north
!move south
```

Movement follows an exit from your current room to the destination room. It fails if there is no matching exit, or if your character is not currently in a room.

Moving creates an in-world movement event and a short-lived movement noise in the destination room. Other systems can react to that.

## Use inventory

Pick up portable items from the current room, your inventory, or an open reachable container:

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

## Talk

Speak to everyone awake and active in the room:

```text
!say Hello, burrow.
```

Talk directly to one present character:

```text
!tell Juniper Meet me outside.
```

`!say` records room-scoped speech. `!tell` records directed speech and requires the target to be in the same room and able to hear you.

Speech has an inferred intent. Questions, apologies, requests, praise, and promises can be interpreted differently by social systems, while plain speech is neutral.

## First few turns

A simple first play sequence looks like this:

```text
!look
!say Hello.
!take three berries
!go north
!look
!drop three berries
```

Player-facing examples in these guides use Discord message syntax. Engine notation omits
the `!` because Discord has already stripped the prefix before dispatch; for example,
engine logs or tests may show `say Hello` for the Discord message `!say Hello`.
