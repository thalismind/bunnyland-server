# The REPL client

The REPL is a compact terminal client: a scrolling log of output above a single command
line you type into. It is lighter than the panel-based Textual TUI but built on the same
toolkit, so it gets rich text, clickable targets, and good keyboard/accessibility support.

Like the TUI it can host a world in this process (no network port) or drive a running
server over HTTP through the web controller, and it reuses the same backends, so anything
the TUI can do, the REPL can too. The header keeps a live status line — who you are playing,
the connection, your action/focus points, and the world clock.

## Launch

The REPL needs the `repl` extra (`uv sync --extra repl`). Host a local world:

```bash
uv run -m bunnyland.repl            # or: bunnyland-repl
```

Connect to a running server:

```bash
bunnyland-repl --server http://localhost:8765
```

List the demo worlds / generators you can pass to `--generator`:

```bash
bunnyland-repl --list-generators
```

Useful options mirror the TUI: `--seed`, `--generator`, `--claim-fallback`, and
`--claim-timeout-minutes`. (It is a full-screen terminal app, so run it in a real
terminal, not through a pipe.)

## Pick a player

List the characters in the world, then take control of one:

```text
> who
  🐰 Juniper
  🐰 Pib
> play Pib
You are now Pib.
```

Names resolve case-insensitively and by prefix (`play Pi` finds `Pib`), the same way the
server resolves the names you type in any command.

## Two ways to give a command

**Named** (canonical) — `command parameter=value`:

```text
> move direction=north
> take item_id=a brass key
> say text=Hello, burrow.
```

**Natural** (convenience) — the same concise phrasing the Discord and agent clients accept:

```text
> go north
> take brass key
> say Hello, burrow.
```

Multi-word values (entity names like `a brass key`) are fine in both forms. Entity names you
type are resolved against what your character can currently reach; if a name doesn't match,
the REPL says so and suggests nearby names instead of submitting a doomed command.

## Click a target

Characters, items, rooms, containers, and exits in the output are shown as highlighted
links. Click one to drop its name into the command line at the cursor — handy for composing
a command without typing a long name:

```text
> take ▮          (then click "a brass key" in the log)
> take a brass key▮
```

## Tab completion

Press Tab to complete, in order:

- a **command** at the start of the line (`mo` → `move`);
- a **parameter name** after the command (`move ` → `direction=`, `exit_id=`);
- a **parameter value** after `=` — reachable entity names for entity parameters, or the
  enumerated choices for others (`move direction=` → `north`, `south`, …).

When several completions are possible the line fills in as far as they agree and the choices
are listed in the log. `help` completes command names and `play` completes player names.

## Live narration

The log surfaces things happening around you as they occur — speech, movement, and other
activity your character can perceive in its current room (room-scoped events from elsewhere
are not shown). High-frequency bookkeeping (point/need changes already in the status bar) is
suppressed to keep the feed readable. If a `--server` connection drops, the failure is
reported once and a reconnect is noted when it recovers, rather than repeating every second.

## History

Up/Down walk previous commands, and history is saved to
`~/.config/bunnyland/repl-history` (honoring `XDG_CONFIG_HOME`) so it survives restarts.

## Meta commands

| Command            | Effect                                             |
|--------------------|----------------------------------------------------|
| `look`             | show your current room, its occupants, exits, and your inventory |
| `inventory` (`inv`) | a detailed list of what you carry, grouped into worn/held/carried |
| `who`              | list the characters you can play                   |
| `points`           | show your action/focus points                      |
| `play <name>`      | take control of a character                        |
| `help [command]`   | list commands, or show one command's parameters    |
| `refresh`          | re-fetch the world snapshot now                    |
| `quit` / `exit`    | leave (Ctrl-C also quits)                           |

## Example session

```text
> play Pib
You are now Pib.
> look
Parlor
  🐰 Pib (you)
  🐰 Marlow
  🍎 an apple
  exits: north → Hallway
  carrying: a brass key
> take apple
» take item_id=item:1
> go north
» move direction=north
> quit
```
