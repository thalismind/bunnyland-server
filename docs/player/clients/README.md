# Client guides

Bunnyland clients all drive the same server-side verbs and validation. Pick the surface
that fits how you want to play:

- **[Terminal TUI](tui.md)** - a panel-based terminal client with room lists, an action
  menu, action search, an action form for arguments, and a queued-action panel.
- **[Terminal REPL](repl.md)** - a compact terminal command line with clickable targets,
  command history, and tab completion.
- **[Web TUI](https://sandbox.bunnyland.dev/web-tui.html)** - a browser version of the
  panel-based TUI with room lists, action search, target pickers, and queued actions.
- **[Web REPL](https://sandbox.bunnyland.dev/web-repl.html)** - a browser command line
  with the same typed command style as the terminal REPL.
- **[Toon client](../toonsim.md)** - the sprite-based web client from the web repo.

The clients can present different controls, but submitted commands still go through the
same authoritative server checks. A menu entry or clickable target is a convenience, not a
shortcut around reachability, permissions, points, or command validation.

## Quick comparison

| Client | Best for | How you act |
|--------|----------|-------------|
| Terminal TUI | browsing a room and picking actions without memorizing command syntax | choose a player, search or select an action, then fill its argument form |
| Terminal REPL | keyboard-first play, scripts, and fast command entry | type canonical or natural commands, with tab completion and clickable names |
| Web TUI | browsing a room and picking actions from a browser | choose a player, search or select an action, then fill its argument form in the browser |
| Web REPL | keyboard-first play from a browser | type commands against a live server, with clickable visible names |
| Toon client | visual room play with sprites and mouse movement | click in the room or use the web action menu |

## Running local or remote

The terminal clients can either host a local world in their own process or connect to a
running Bunnyland server:

```bash
uv run --all-extras bunnyland-tui --generator apartment-demo
uv run --all-extras bunnyland-repl --generator apartment-demo

uv run --all-extras bunnyland-tui --server http://localhost:8765
uv run --all-extras bunnyland-repl --server http://localhost:8765
```

Use `--list-generators` in either terminal client to see grouped demo worlds and
algorithmic generators:

```bash
uv run --all-extras bunnyland-tui --list-generators
uv run --all-extras bunnyland-repl --list-generators
```

The web clients connect to a running HTTP server from the browser. See
[Toon client](../toonsim.md), [Web TUI](https://sandbox.bunnyland.dev/web-tui.html),
and [Web REPL](https://sandbox.bunnyland.dev/web-repl.html) for details.
