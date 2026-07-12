# The Web REPL client

The Web REPL is the browser version of the terminal line REPL. It connects to a running
Bunnyland server, claims a character with a web controller, and lets you play by typing
commands into a single prompt.

Use it when you want keyboard-first play without installing the terminal client. If you
prefer a graphical room view with sprites and click-to-move, use
[Bunnyland Toon](../toonsim.md) instead.

## Open it

Open the Bunnyland web welcome page and choose **Web REPL**, or open the page directly:

```text
web-repl.html
```

Hosted deployments usually fill the **Server** field from their web config. For a local
server, enter the API URL, such as:

```text
http://127.0.0.1:8765
```

Click **Connect Live**. The browser reads the player-facing projections only: the claim
lobby, your selected character's room view, queued commands, and recent perceivable
events.

## Pick a player

Choose a character from the **Player** menu, or type:

```text
> play Pib
```

The browser claims that character with a web controller. The fallback controls in the
toolbar decide what happens when the claim expires or the browser stops controlling the
character:

- **Suspend** leaves the character idle.
- **LLM** hands the character back to an LLM controller.

Names resolve case-insensitively and by prefix, so `play Pi` can find `Pib`.

## Useful meta commands

| Command | Effect |
|---------|--------|
| `who` | list available player characters |
| `play <name>` | claim a character |
| `look` | show your current room, visible targets, exits, and carried items |
| `inventory` (`inv`) | show what you carry |
| `points` | show current action and focus points |
| `queued` | show commands waiting to run |
| `help [command]` | list commands, or show one command's parameters |
| `refresh` | reload the player view now |
| `clear` | clear the browser transcript |

## Type actions

Named commands use canonical `command parameter=value` syntax:

```text
> move direction=north
> take item_id=a brass key
> say text=Hello, burrow.
```

The Web REPL also accepts the same concise natural forms as the terminal REPL for common
actions:

```text
> go north
> take brass key
> say Hello, burrow.
> tell Marlow psst
```

Entity names resolve against your visible target groups: nearby characters, room items,
inventory, exits, and other reachable entities the server exposes in your character
projection. If a name does not match, the client reports that before posting the command.
The server still performs the authoritative validation for reachability, permissions,
points, and action rules.

## Click names and use history

Visible names in the transcript are clickable. Clicking a character, item, or exit inserts
its display name into the input so you can finish a command without retyping a long label.

The prompt supports basic command history:

- Up moves to the previous command.
- Down moves forward through history.
- Tab fills the command line when there is exactly one completion.

The suggestion list is built from the live action definitions and visible targets in your
current character projection.

## Live feedback

The transcript shows command acknowledgements and recent events your character can
perceive. High-frequency bookkeeping events are hidden so speech, movement, rejections,
and meaningful world activity are easier to notice.

**Connect Live** opens the claim-authenticated player stream. The client reconnects after a
temporary interruption and uses the character-scoped recent-event endpoint as a fallback,
deduplicating entries when the stream returns. Disclosed fact lines are perspective- and
detail-filtered, so ordinary activity emphasizes important changes rather than repeating
normal component state.

If a command costs more action or focus points than you currently have, the Web REPL posts
it with `on_insufficient_points=queue`, matching the Toon and terminal clients. The server
decides whether to queue or reject it.
