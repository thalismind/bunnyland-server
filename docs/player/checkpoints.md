# Checkpoints

Checkpoints are special world objects that can save or reload the whole world. A world
builder has to place them intentionally, so not every server has them. They might appear as
a typewriter, red scroll, bonfire, terminal, shrine, guest book, or another object that
fits the setting.

## Find a checkpoint

Look around and inspect likely objects:

```text
!look
!inspect typewriter
```

If the object is a checkpoint, its prompt text describes it as a checkpoint with save and
reload available.

You must be able to reach the checkpoint. Usually that means it is in your room, in your
inventory, or in an open reachable container.

## Save

Save at a reachable checkpoint:

```text
!save-checkpoint typewriter
```

Natural phrasing may also work in clients that resolve natural commands:

```text
save at typewriter
save checkpoint red scroll
```

Saving writes the current world to the server's configured save file. If the server was
not started with a save file, the command is rejected.

## Reload

Reload from the configured save file at a reachable checkpoint:

```text
!reload-checkpoint bonfire
```

Natural phrasing may also work:

```text
reload from bonfire
reload checkpoint terminal
```

Reloading replaces the live world with the saved version. Changes made after the last save
are lost. Queued commands are also cleared, so characters start from the restored world
state.

## What to expect

- A checkpoint saves and reloads the whole world, not only your character.
- The server has one configured save file; checkpoints are not separate save slots.
- Any reachable checkpoint can reload the current save when the plugin is enabled.
- If the save file is missing, reload is rejected and the current world keeps running.
- If the checkpoint plugin is not enabled on that server, these verbs are unavailable.

