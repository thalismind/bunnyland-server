# Getting started

Start here if you are new to Bunnyland. The first actions are the same across clients:
look at the room, move through exits, handle nearby items, keep hunger and thirst under
control, and use focus actions for private notes and recall.

Player-facing examples in these guides use Discord message syntax. Engine notation omits
the `!` because Discord has already stripped the prefix before dispatch; for example,
engine logs or tests may show `say Hello` for the Discord message `!say Hello`.

## First few turns

A simple first play sequence looks like this:

```text
!look
!say Hello.
!take three berries
!eat three berries
!go north
!look
!inspect Juniper
```

If a client gives you buttons, menus, clickable targets, or sprites, those controls still
submit the same server-side verbs. Server validation decides whether the character can
reach the target, spend the points, and complete the action.

Room summaries and ordinary turns emphasize what matters now. Detailed inspection can show
additional status facts that would be noise every turn—for example, a calm need meter or a
normal mechanism state. Not seeing “not hungry” in the ordinary view does not mean the state
is missing; inspect yourself or open a detailed character/status view when you want the full
picture.

## Basic guides

- [Movement and looking](movement-and-looking.md) covers room summaries, narration,
  target visibility, exits, and moving between rooms.
- [Inventory and use](inventory-and-use.md) covers taking, dropping, putting, holding,
  wearing, using, unlocking, opening, closing, writing, and talking.
- [Hunger and thirst](hunger-and-thirst.md) covers eating, drinking, consumables,
  renewable water sources, and need decay.
- [Focus, notes, and memories](focus-notes-and-memories.md) covers private notes,
  remembering, reflecting, contextual recall, and forgetting.
- [MCP-controlled play](clients/mcp.md) covers the end-to-end character claim, action
  discovery, command submission, and asynchronous outcome loop for agent clients.
