# Client guides

Bunnyland clients all drive the same server-side verbs and validation. Pick the surface
that fits how you want to play:

- **[Terminal TUI](tui.md)** - a panel-based terminal client with room lists, an action
  menu, action search, an action form for arguments, and a queued-action panel.
- **[Terminal REPL](repl.md)** - a compact terminal command line with clickable targets,
  command history, and tab completion.
- **[Terminal character chat](chat.md)** - a focused local-or-remote character picker and
  conversation client, with an optional line-oriented mode.
- **[Web TUI](https://sandbox.bunnyland.dev/web-tui.html)** - a browser version of the
  panel-based TUI with room lists, action search, target pickers, and queued actions.
- **[Web REPL](https://sandbox.bunnyland.dev/web-repl.html)** - a browser command line
  with the same typed command style as the terminal REPL.
- **[Toon client](../toonsim.md)** - the sprite-based web client from the web repo.
- **[MCP-controlled play](mcp.md)** - an agent-oriented tool loop for discovering actions,
  resolving entity ids, submitting commands, and observing asynchronous outcomes.

The clients can present different controls, but submitted commands still go through the
same authoritative server checks. A menu entry or clickable target is a convenience, not a
shortcut around reachability, permissions, points, or command validation.

Remote clients share a claim-authenticated live update stream. Chat, character sheets, Toon,
Web TUI, Web REPL, and their terminal counterparts refresh the selected character after
perceivable events. The live stream is best-effort: after a sequence gap, queue overflow,
or reconnect, clients replace their local state with a fresh character projection rather
than replaying queued frames. The recent activity feed is bounded and reports when it
cannot cover the requested interval; manual refresh remains available at any time.

Action menus are built from the server's installed action registry and current target
groups. If that metadata is temporarily unavailable, clients show an empty or disabled
action state rather than an outdated built-in verb list.

## Content warnings

The Terminal TUI and REPL, Web TUI and REPL, Toon client, and 3D player show a content
warning before joining a flagged world. The warning combines the tags declared by every
installed world plugin with tags added to the world's policy by its administrators. The
client does not claim a character until you choose **Accept and Join**.

The same public world resource includes the world's title and descriptive welcome or
message-of-the-day text. Administrators store those values in the world's singleton
`WorldInfoComponent`, along with any additional `content_flags`, so they travel with saved
and transferred worlds.

Browser clients can remember the displayed flags after acceptance. That preference is
shared by Bunnyland clients in the same browser profile. If the world's flag set changes,
the client checks the new set before the next claim and shows any flags that are not
ignored.

Terminal users can ignore known flags in
`$XDG_CONFIG_HOME/bunnyland/terminal.yml` (normally
`~/.config/bunnyland/terminal.yml`):

```yaml
ignored_content_flags:
  - adult:violence
  - pvp
```

For a one-off launch, repeat `--ignore-content-flag` or pass a comma-separated list:

```bash
uv run --all-extras bunnyland tui --ignore-content-flag adult:violence --ignore-content-flag pvp
uv run --all-extras bunnyland repl --ignore-content-flag adult:violence,pvp
```

Saved and command-line ignores are combined. Ignoring a flag suppresses its warning; it
does not enable a mechanic or change the world's boundary policy.

## Quick comparison

| Client | Played in | Best for | How you act |
|--------|-----------|----------|-------------|
| Terminal TUI | Terminal | browsing a room and picking actions without memorizing command syntax | choose a player, search or select an action, then fill its argument form |
| Terminal REPL | Terminal | keyboard-first play, scripts, and fast command entry | type canonical or natural commands, with tab completion and clickable names |
| Terminal chat | Terminal | focused conversations and native character sheets | choose a character, type a message, and observe any game action it chooses |
| Web TUI | Web | browsing a room and picking actions from a browser | choose a player, search or select an action, then fill its argument form in the browser |
| Web REPL | Web | keyboard-first play from a browser | type commands against a live server, with clickable visible names |
| Toon client | Web | visual room play with sprites and mouse movement | click in the room or use the web action menu |
| MCP | Agent client | structured, autonomous play without reading server internals | discover actions and target ids, submit a command, then observe its later outcome |

## Running local or remote

The terminal clients can either host a local world in their own process or connect to a
running Bunnyland server:

```bash
uv run --all-extras bunnyland tui --generator apartment-demo
uv run --all-extras bunnyland repl --generator apartment-demo
uv run --all-extras bunnyland chat --generator apartment-demo

uv run --all-extras bunnyland tui --server http://localhost:8765
uv run --all-extras bunnyland repl --server http://localhost:8765
uv run --all-extras bunnyland chat --server http://localhost:8765/v1
```

Use `--list-generators` in either terminal client to see grouped demo worlds and
algorithmic generators:

```bash
uv run --all-extras bunnyland tui --list-generators
uv run --all-extras bunnyland repl --list-generators
```

The web clients connect to a running HTTP server from the browser. See
[Toon client](../toonsim.md), [Web TUI](https://sandbox.bunnyland.dev/web-tui.html),
and [Web REPL](https://sandbox.bunnyland.dev/web-repl.html) for details.
