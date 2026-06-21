"""Command handling for the Bunnyland REPL — the I/O-free core behind the Textual app.

It reuses the TUI's backends (``LocalBackend``/``RemoteBackend``) — reading the claim
lobby for the player picker and the player's own room projection for the world — and the
read-only ``World`` model, and accepts two input styles:

* named: ``move direction=north``, ``take item_id=a brass key`` — Tab completes the
  command, then each parameter name, then its value;
* natural: ``go north``, ``take brass key`` — parsed with the shared
  :class:`NaturalCommandParser`.

Both styles resolve human-readable names to entity ids client-side (the raw command
endpoint expects ids), exactly as the TUI sends the ids it picked. Command output is
returned as Rich :class:`~rich.text.Text`, with characters, items, rooms, containers, and
exits rendered as clickable links (``@click`` meta keyed by entity id) that the app turns
into "insert this name into the input" actions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.style import Style
from rich.text import Text

from ..core.actions import ActionDefinition, definitions_by_tool_name
from ..llm_agents.dispatch import suggest_names
from ..llm_agents.natural_language import NaturalCommandParser
from ..server.models import CharacterSummaryView
from ..terminal_generators import available_generators as available_generators
from ..terminal_generators import format_generator_lines as format_generator_lines
from ..tui import events as tui_events
from ..tui.backend import Backend
from ..tui.model import KIND_ICON, World, entity_icon, entity_name, fmt_points, has
from .completion import complete_line, reference_candidates

META_COMMANDS = (
    "help", "who", "look", "inventory", "points", "play", "refresh", "quit", "exit"
)


def _humanize_event_type(event_type: str) -> str:
    return tui_events._humanize_event_type(event_type)


def history_path() -> Path:
    """The REPL history file, beside the TUI's persistent client id."""
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "bunnyland" / "repl-history"


def link(label: str, entity_id: str) -> Text:
    """A clickable target: clicking inserts the target's name into the input. The action is
    keyed by entity id (which never contains quotes) so names with apostrophes are safe.

    The style is applied as a span (not the Text's base style) so it survives ``append_text``
    when the target is embedded in a larger line."""
    text = Text(label)
    text.stylize(
        Style(color="cyan", underline=True, meta={"@click": f"app.insert({entity_id!r})"})
    )
    return text


@dataclass(frozen=True)
class ParsedCommand:
    """A command line resolved to a tool name and its raw (unresolved) arguments."""

    tool: str
    arguments: dict[str, str] = field(default_factory=dict)


def parse_line(line: str, definitions: dict[str, ActionDefinition]) -> ParsedCommand | None:
    """Parse a command line into a :class:`ParsedCommand`.

    A known command followed by ``key=value`` tokens (or nothing) is the named form;
    value tokens without ``=`` extend the preceding value so multi-word names work. Any
    other input falls back to the natural-language parser.
    """
    tokens = line.split()
    if not tokens:
        return None
    command = tokens[0]
    named = command in definitions and (len(tokens) == 1 or "=" in tokens[1])
    if named:
        arguments: dict[str, str] = {}
        current = ""  # the first argument token always contains '=', so this is set before use
        for token in tokens[1:]:
            if "=" in token:
                key, _, value = token.partition("=")
                arguments[key] = value
                current = key
            else:  # a bare token continues the previous value (multi-word names)
                arguments[current] = f"{arguments[current]} {token}".strip()
        return ParsedCommand(definitions[command].name, arguments)

    call = NaturalCommandParser().parse(line)
    if call is None:
        return None
    return ParsedCommand(call.name, {k: v for k, v in call.arguments.items() if isinstance(v, str)})


def resolve_name(value: str, world: World, candidates: list[tuple[str, str]]) -> str:
    """Resolve a human-readable name to an entity id, mirroring the server's dispatch:
    valid ids pass through, then an exact (case-insensitive) name, then the shortest name
    with the query as a prefix. Unresolvable values are returned unchanged so the handler
    rejects them observably."""
    if value in world.entities:
        return value
    query = value.strip().lower()
    if not query:
        return value
    for name, entity_id in candidates:
        if name.lower() == query:
            return entity_id
    matches = sorted(
        (nc for nc in candidates if nc[0].lower().startswith(query)),
        key=lambda nc: (len(nc[0]), nc[0].lower()),
    )
    return matches[0][1] if matches else value


class BunnylandRepl:
    """REPL state and command handling over a snapshot :class:`Backend`."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self.world = World()
        self.player_id = ""
        self.control: tuple[str, int] | None = None
        self.character_list: list[CharacterSummaryView] = []
        self._defs = definitions_by_tool_name()
        self._events = tui_events.EventNarrator()

    # ── data ──────────────────────────────────────────────────────────────────
    async def refresh(self) -> None:
        # The picker comes from the claim lobby; the world is only ever the player's own
        # perceived room (their character projection), never the admin-gated full snapshot.
        self.character_list = await self.backend.fetch_character_list()
        known_ids = {summary.character_id for summary in self.character_list}
        if self.player_id and self.player_id not in known_ids:
            self.player_id = ""
            self.control = None
        if self.player_id:
            projection = await self.backend.fetch_character_projection(self.player_id)
            if projection and projection.get("character_id") == self.player_id:
                self.world = World.parse(projection)
                projected_control = self.world.control(self.player_id)
                if self.control:
                    if projected_control and projected_control[0] == self.control[0]:
                        self.control = projected_control
                    else:
                        self.control = None
            else:
                self.world = World()
        else:
            self.world = World()

    async def select_player(self, name: str) -> str:
        candidates = [(summary.name, summary.character_id) for summary in self.character_list]
        ids = {summary.character_id for summary in self.character_list}
        chosen = name if name in ids else resolve_name(name, self.world, candidates)
        summary = next((s for s in self.character_list if s.character_id == chosen), None)
        if summary is None:
            return f"No such player: {name!r}. Try 'who'."
        self.control = await self.backend.claim(chosen, self.world)
        if self.control is None:
            return f"Could not claim {summary.name}."
        self.player_id = chosen
        await self.refresh()
        return f"You are now {summary.name}."

    def name_for(self, entity_id: str) -> str | None:
        """The display name of a reachable entity id, used by the app's click action."""
        entity = self.world.get(entity_id)
        return entity_name(entity) if entity else None

    def status_text(self) -> str:
        """A one-line status: who you are, the connection, your points, and the world clock."""
        who = entity_name(self.world.get(self.player_id)) if self.player_id else "no player"
        parts = [who, self.backend.label]
        if self.player_id:
            parts.append(self.render_points())
        parts.append(f"epoch {self.world.epoch}s")
        return " · ".join(parts)

    # ── perceived-event narration ───────────────────────────────────────────────
    def drain_events(self, messages: list[dict]) -> list[Text]:
        """Render the not-yet-seen events the current player can perceive, then mark the
        whole window seen. ``messages`` are ``recent_events()`` payloads."""
        return self._events.drain_events(
            messages,
            player_id=self.player_id,
            room_of=self.world.room_of,
            name_for=self.name_for,
        )

    # ── dispatch ──────────────────────────────────────────────────────────────
    async def dispatch(self, line: str) -> Text:
        line = line.strip()
        if not line:
            return Text("")
        verb, _, rest = line.partition(" ")
        rest = rest.strip()
        if verb == "help":
            return self.render_help(rest)
        if verb == "who":
            return self.render_players()
        if verb == "look":
            return self.render_room()
        if verb in {"inventory", "inv"}:
            return self.render_inventory()
        if verb == "points":
            return Text(self.render_points())
        if verb == "refresh":
            await self.refresh()
            return Text("Refreshed.")
        if verb == "play":
            if not rest:
                return Text("Usage: play <player name>")
            return Text(await self.select_player(rest))
        return await self._act(line, verb)

    async def _act(self, line: str, verb: str) -> Text:
        parsed = parse_line(line, self._defs)
        if parsed is None:
            return Text(f"I don't understand {verb!r}. Type 'help'.")
        if not self.player_id or self.control is None:
            if not self.player_id:
                return Text("Pick a player first: play <name>.")
            self.control = await self.backend.claim(self.player_id, self.world)
            if self.control is None:
                return Text(f"Could not claim {self.player_id}.")
        definition = self._defs[parsed.tool]
        candidates = reference_candidates(self.world, self.player_id)

        payload: dict[str, Any] = {}
        for key, value in parsed.arguments.items():
            if key in definition.reference_arg_keys:
                resolved = resolve_name(value, self.world, candidates)
                if resolved not in self.world.entities:
                    hints = suggest_names(value, candidates)
                    suffix = f" Did you mean: {', '.join(hints)}?" if hints else ""
                    label = key.removesuffix("_id").replace("_", " ")
                    return Text(f"I don't see {value!r} ({label}) here.{suffix}")
                payload[key] = resolved
            else:
                payload[key] = value

        result = await self.backend.submit({
            "character_id": self.player_id,
            "controller_id": self.control[0],
            "controller_generation": self.control[1],
            "command_type": definition.command_type,
            "payload": payload,
            "cost": {"action": definition.cost.action, "focus": definition.cost.focus},
            "lane": definition.lane.value,
            "on_insufficient_points": "queue",
        })
        detail = " ".join(f"{k}={v}" for k, v in payload.items())
        if not result.accepted:
            reason = result.reason or "command rejected"
            return Text(f"✗ {definition.command_type} — {reason}".rstrip(), style="dark_orange")
        return Text(f"» {definition.command_type} {detail}".rstrip(), style="green")

    # ── rendering ─────────────────────────────────────────────────────────────
    def render_room(self) -> Text:
        room_id = self.world.room_of(self.player_id) or self.world.first_room_id()
        room = self.world.get(room_id)
        if room is None:
            return Text("No room.")
        out = Text()
        out.append_text(link(entity_name(room), room["id"]))
        out.stylize("bold", 0, len(out))
        for member in self.world.room_members(room_id):
            if has(member, "RoomComponent") or has(member, "DoorComponent"):
                continue
            out.append(f"\n  {entity_icon(member)} ")
            out.append_text(link(entity_name(member), member["id"]))
            if member["id"] == self.player_id:
                out.append(" (you)")
        doors = self.world.doors(room_id)
        if doors:
            out.append("\n  exits: ")
            for index, (target_id, direction, dest) in enumerate(doors):
                if index:
                    out.append(", ")
                name = entity_name(dest) if dest else target_id
                out.append_text(link(f"{direction} → {name}" if direction else name, target_id))
        carried = self.world.carried(self.player_id) if self.player_id else []
        if carried:
            out.append("\n  carrying: ")
            for index, item in enumerate(carried):
                if index:
                    out.append(", ")
                out.append_text(link(entity_name(item), item["id"]))
        return out

    def render_inventory(self) -> Text:
        """A detailed inventory grouped into worn, held, and otherwise carried items, each
        clickable and tagged with its kind — fuller than the ``look`` summary line."""
        player = self.world.get(self.player_id) if self.player_id else None
        if player is None:
            return Text("Pick a player first: play <name>.")
        out = Text()
        for relationship, label in (("Wearing", "worn"), ("Holding", "held"),
                                    ("Contains", "carrying")):
            items = [self.world.get(edge["target"])
                     for edge in player["relationships"].get(relationship, [])]
            items = [item for item in items if item]
            if not items:
                continue
            if len(out):
                out.append("\n")
            out.append(f"{label}:")
            for item in items:
                out.append(f"\n  {entity_icon(item)} ")
                out.append_text(link(entity_name(item), item["id"]))
                kind = item["components"].get("IdentityComponent", {}).get("kind")
                if kind:
                    out.append(f" ({kind})")
        return out if len(out) else Text("You aren't carrying anything.")

    def render_players(self) -> Text:
        if not self.character_list:
            return Text("No players.")
        out = Text()
        for index, summary in enumerate(self.character_list):
            if index:
                out.append("\n")
            icon = KIND_ICON.get(summary.kind) or KIND_ICON["other"]
            out.append(f"  {icon} ")
            out.append_text(link(summary.name, summary.character_id))
            if summary.character_id == self.player_id:
                out.append(" (you)")
        return out

    def render_points(self) -> str:
        if not self.player_id:
            return "Pick a player first: play <name>."
        pts = self.world.points(self.player_id)
        return (
            f"AP {fmt_points(pts['ap'])}/{fmt_points(pts['ap_max'])}   "
            f"FP {fmt_points(pts['fp'])}/{fmt_points(pts['fp_max'])}"
        )

    def _availability(self) -> dict[str, dict]:
        """Per-command availability from the current projection, keyed by command type."""
        return {
            str(action.get("command_type")): action
            for action in (self.world.actions or [])
            if action.get("command_type")
        }

    def render_help(self, topic: str) -> Text:
        availability = self._availability()
        if topic and topic in self._defs:
            definition = self._defs[topic]
            keys = ", ".join(definition.arg_keys) or "(none)"
            out = Text(
                f"{topic} — {definition.title or definition.command_type}\n  parameters: {keys}"
            )
            info = availability.get(definition.command_type)
            if info is not None and not info.get("available", True):
                reason = info.get("unavailable_reason") or "unavailable"
                out.append(f"\n  unavailable: {reason}", style="dim")
            return out

        def is_available(tool: str) -> bool:
            info = availability.get(self._defs[tool].command_type)
            return True if info is None else bool(info.get("available", True))

        tools = sorted(self._defs)
        # Available commands first and prominent; unavailable ones still listed but dimmed,
        # since a player may still choose to queue them.
        available = [tool for tool in tools if is_available(tool)]
        unavailable = [tool for tool in tools if not is_available(tool)]
        meta = ", ".join(m for m in META_COMMANDS if m != "exit")
        out = Text("Commands (try 'help <command>' for parameters):\n")
        out.append(f"  {', '.join(available)}\n")
        if unavailable:
            out.append(f"  unavailable: {', '.join(unavailable)}\n", style="dim")
        out.append(f"Meta: {meta}\n")
        out.append(
            "Forms: 'move direction=north' (named) or 'go north' (natural). "
            "Click a highlighted target to drop its name into the input."
        )
        return out

    # ── completion ────────────────────────────────────────────────────────────
    def complete(self, line: str) -> list[str]:
        return complete_line(
            line,
            definitions=self._defs,
            # ``look``/``inventory`` are both tools and meta commands; list each word once.
            commands=tuple(dict.fromkeys((*self._defs, *META_COMMANDS))),
            entity_names=[name for name, _ in reference_candidates(self.world, self.player_id)],
            players=[summary.name for summary in self.character_list],
        )
