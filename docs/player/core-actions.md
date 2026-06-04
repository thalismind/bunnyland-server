# How to use core actions

Core actions are the shared verbs every controller uses. In Discord, prefix them with `!`.

## Look and move

Start by claiming a character and checking the room:

```text
!claim Juniper
!look
```

The room summary shows visible characters, objects, inventory, and exits. Move by
direction when an exit is listed:

```text
!move north
!look
```

## Carry and place items

Take portable objects from the room or an open reachable container:

```text
!take smooth pebble
```

Put carried items into an open container, or drop them into the current room:

```text
!put smooth pebble in woven basket
!take smooth pebble
!drop smooth pebble
```

## Use and write

Use reachable mechanisms and objects:

```text
!use burrow door with brass key
!use burrow door
```

The first command can unlock a matching lock. The second can open or close the door.

Write on reachable writable objects:

```text
!write Meet at dawn on blank sign
```

Writing changes the physical object, unlike private notes.

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

Talk to the room or a present character:

```text
!say thank you Hazel
!tell Hazel please guard the basket
```

Speech is world state. Relationship and mood systems can react to what was said and how it
was interpreted.
