# The TUI client

The TUI is the panel-based terminal client. It shows the current room on the left and your
player controls on the right, so you can play without memorizing command syntax.

It is built with Textual, so run it in a real terminal. It can host a world in this process
or connect to a running server over HTTP.

## Launch

The TUI needs the `tui` extra (`uv sync --extra tui`). Host a local world:

```bash
uv run -m bunnyland.tui            # or: bunnyland-tui
```

Connect to a running server:

```bash
bunnyland-tui --server http://localhost:8765
```

List available demo worlds and generators:

```bash
bunnyland-tui --list-generators
```

Useful local options include `--seed`, `--generator`, `--claim-fallback`, and
`--claim-timeout-minutes`.

## Pick a player

Use the player menu at the top of the right panel. Selecting a character claims control for
this TUI session, updates the action list, and follows that character's current room.

The status line shows the backend, world clock, and current player. If the server
connection drops, the activity log reports the failure once and reports when it reconnects.

## Read the room

The left panel has three sections:

- the room title and visible occupants or objects;
- doors leading out of the room;
- recent activity your character can perceive.

Selecting a door previews that destination room without moving your character. While you
are previewing another room, the title shows that you are spectating. Press `f` to follow
your player back to their current room.

When your character moves through an exit, the server sends a destination-room summary so
the TUI can immediately show what is in the new room.

## Use actions

The right panel shows your action and focus points, a search box, the action list, and
queued actions.

Type in **Search actions** to filter the action list by title, tool name, or command type.
Use **Clear** to reset the filter.

Choose an action from the list:

- targeted actions open a picker with valid nearby targets;
- text actions open a prompt for the message or note;
- actions you cannot afford are disabled until points recover.

The server still validates every submitted command. If the room changes, a target becomes
unreachable, or a command is no longer valid, the server rejects it even if the TUI had
shown the option.

## Queued actions

If you select an action before you have enough points, the TUI submits it with the normal
queue-on-insufficient-points behavior. The queued-action panel shows pending commands for
the selected character, including their lane, cost, and payload details when available.

Queued commands are character-scoped. Switching players updates the queue panel to the new
character's queue.

## Keyboard controls

| Key | Effect |
|-----|--------|
| `r` | refresh the world snapshot now |
| `f` | follow your selected player |
| `q` | quit |
| `Esc` | close a target or text prompt |

## Example session

```text
$ bunnyland-tui --generator apartment-demo
```

1. Pick a character from the player menu.
2. Search for `move`, choose **Move**, and select a door.
3. Read the destination room summary.
4. Search for `take`, choose **Take**, and select a nearby item.
5. Watch the queued-action panel if you run out of points.
