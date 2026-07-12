# Movement and looking

Looking and movement are the first loop in most Bunnyland worlds. Looking tells you what
your character can currently perceive. Moving changes the room your character occupies and
then clients can render the destination room.

## Look around

Looking is read-only. It shows your current room summary, visible characters and objects,
exits, and inventory. It does not spend an action or change the world.

In Discord, use:

```text
!look
```

In the web inspector, terminal clients, or an agent prompt, the same information appears
as the current room summary:

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

If something is not shown in the room summary or your inventory, your character usually
cannot target it by name.

## Inspect details

Inspect a specific reachable object, character, or mechanism for more detail:

```text
!inspect woven basket
!inspect brass door
!inspect Juniper
```

Inspecting is useful when an object may have readable text, a lock, a mechanism state, a
crafted mark, or other details that do not fit in the room summary.

Inspection also requests a higher detail level. Bunnyland assigns each visible fact a
non-negative detail score: `0` is critical, ordinary turns include through `10`, closer
inspection includes informative facts around `20`, and detailed status includes through
`30`. A need such as hunger can move between those bands as it becomes more important, so a
calm “not hungry” fact stays out of normal turns but appears when you inspect yourself in
detail. Privacy and perception still apply: inspecting another character does not reveal
their private thoughts, memories, or hidden meters.

## Doors and locks

Some exits are connected to doors or other mechanisms. If movement fails because a route
is closed or locked, inspect the door and use the reachable controls before moving again:

```text
!inspect brass door
!open brass door
!unlock brass door with brass key
!open brass door
!go north
```

A door may need to be unlocked before it can open, and some worlds use package-specific
mechanisms instead of a normal key. The server checks reachability, lock state, and the
item used as the tool, so client buttons and target pickers are only shortcuts for the
same validated commands. See [Inventory and use](inventory-and-use.md) for more examples
of using items and tools.

## Move

Move through an exit by direction:

```text
!go north
!move south
```

Movement follows an exit from your current room to the destination room. It fails if
there is no matching exit, if the exit is blocked by world state, or if your character is
not currently in a room.

Moving creates an in-world movement event and a short-lived movement noise in the
destination room. Other systems can react to that. After the actor moves, clients should
show the destination room so you can immediately choose the next interaction.

Connected web and remote terminal clients receive player-scoped live updates. Speech,
movement, action results, and disclosed event facts should appear without a manual refresh;
if the live connection drops, clients reconnect and temporarily use the recent-activity
fallback without duplicating events.

## Narration

Some clients and scenarios can show narration after a turn. Narration is a presentation
of what your character can currently perceive: nearby events, the room summary, visible
characters and objects, and exits. It does not create facts or change the world.

If another character acts in a different room, or an object is hidden from your character,
that remote or hidden fact should not appear in your narration.
