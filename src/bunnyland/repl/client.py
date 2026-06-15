"""Command handling for the Bunnyland REPL — the I/O-free core behind the Textual app.

It reuses the TUI's snapshot backends (``LocalBackend``/``RemoteBackend``) and read-only
``World`` model, and accepts two input styles:

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
from typing import TYPE_CHECKING, Any

from rich.style import Style
from rich.text import Text

from ..core.actions import ActionDefinition, definitions_by_tool_name
from ..llm_agents.dispatch import suggest_names
from ..llm_agents.natural_language import NaturalCommandParser
from ..tui.backend import Backend
from ..tui.model import World, entity_icon, entity_name, fmt_points, has
from .completion import complete_line, reference_candidates

if TYPE_CHECKING:
    from ..worldgen import WorldGenerator

META_COMMANDS = (
    "help", "who", "look", "inventory", "points", "play", "refresh", "quit", "exit"
)

# Events that would drown out narration rather than describe activity: command lifecycle
# (the "» …" echo already confirms your command), continuous point/need/affect telemetry
# (points are shown in the status bar), and perception/look bookkeeping. ``CommandRejected``
# is deliberately kept so a failed action tells you why instead of silently doing nothing.
_UNNARRATED_EVENT_TYPES = frozenset({
    "CommandSubmittedEvent", "CommandAcceptedEvent", "CommandQueuedEvent",
    "CommandExecutedEvent", "CommandExpiredEvent",
    "ActionPointsChangedEvent", "FocusPointsChangedEvent", "EncumbranceChangedEvent",
    "PainChangedEvent", "BleedingChangedEvent", "AttentionShiftedEvent", "AffectChangedEvent",
    "EntitySeenEvent", "RoomLookedEvent", "RoomQualityUpdatedEvent", "HungerChangedEvent",
    "ThirstChangedEvent", "DailyNeedChangedEvent", "SkillXPChangedEvent",
})

# Fields on every ``DomainEvent``; the rest of a serialized event is its specific payload.
_EVENT_BASE_KEYS = frozenset({
    "event_id", "world_epoch", "created_at", "visibility", "actor_id", "room_id",
    "target_ids", "causation_id", "correlation_id",
})


def _humanize_event_type(event_type: str) -> str:
    """``ResourceGatheredEvent`` -> ``Resource gathered`` (splits on CamelCase)."""
    name = event_type.removesuffix("Event")
    words: list[str] = []
    current = ""
    for char in name:
        if char.isupper() and current:
            words.append(current)
            current = char
        else:
            current += char
    if current:
        words.append(current)
    return " ".join(words).capitalize()


def history_path() -> Path:
    """The REPL history file, beside the TUI's persistent client id."""
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "bunnyland" / "repl-history"


def available_generators() -> list[WorldGenerator]:
    """The world generators (demo worlds) a local game can use, from the enabled plugins —
    the same registry ``LocalBackend`` resolves ``--generator`` against, sorted by name."""
    from ..plugins import bunnyland_plugins, select
    from ..worldgen import collect_generators

    plugins = select(list(bunnyland_plugins()), None)
    return sorted(collect_generators(plugins).values(), key=lambda generator: generator.name)


def format_generator_lines(generators: list[WorldGenerator]) -> list[str]:
    """Human-readable lines for ``--list-generators``: a name (flagging seed-less ones) and
    an indented description where one is set."""
    lines: list[str] = []
    for generator in generators:
        suffix = "" if generator.uses_seed else "  (ignores --seed)"
        lines.append(f"{generator.name}{suffix}")
        if generator.description:
            lines.append(f"    {generator.description}")
    return lines


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
        self._defs = definitions_by_tool_name()
        self._seen_event_ids: set[str] = set()

    # ── data ──────────────────────────────────────────────────────────────────
    async def refresh(self) -> None:
        self.world = World.parse(await self.backend.fetch_snapshot())
        if self.player_id and self.player_id not in self.world.entities:
            self.player_id = ""
            self.control = None

    async def select_player(self, name: str) -> str:
        characters = self.world.characters()
        candidates = [(entity_name(c), c["id"]) for c in characters]
        chosen = resolve_name(name, self.world, candidates)
        character = self.world.get(chosen)
        if character is None or not has(character, "CharacterComponent"):
            return f"No such player: {name!r}. Try 'who'."
        self.control = await self.backend.claim(chosen, self.world)
        if self.control is None:
            return f"Could not claim {entity_name(character)}."
        self.player_id = chosen
        await self.refresh()
        return f"You are now {entity_name(character)}."

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
        rendered: list[Text] = []
        current: set[str] = set()
        for message in messages:
            event = message.get("data", message).get("event", {})
            event_id = event.get("event_id")
            if event_id is None:  # cannot de-duplicate without an id; skip rather than repeat
                continue
            current.add(event_id)
            if event_id in self._seen_event_ids:
                continue
            event_type = message.get("data", message).get("event_type")
            if event_type in _UNNARRATED_EVENT_TYPES:
                continue
            # You always see your own actions (many are system-visibility, e.g. take/move);
            # others' activity is shown only when its visibility/scope lets you perceive it.
            own = bool(self.player_id) and event.get("actor_id") == self.player_id
            if own or self._perceives(event):
                rendered.append(self._render_event(message.get("data", message)))
        self._seen_event_ids = current
        return rendered

    def _perceives(self, event: dict) -> bool:
        """Whether the player would perceive *another* character's event, by its visibility
        and scope — room events only in the player's room, directed/private only when they
        involve them. (Your own events are surfaced separately in :meth:`drain_events`.)"""
        visibility = event.get("visibility")
        if visibility == "public":
            return True
        if visibility == "room":
            return bool(self.player_id) and event.get("room_id") == self.world.room_of(
                self.player_id
            )
        if visibility == "directed":
            return bool(self.player_id) and (
                self.player_id == event.get("actor_id")
                or self.player_id in (event.get("target_ids") or ())
            )
        if visibility == "private":
            return bool(self.player_id) and self.player_id == event.get("actor_id")
        return False  # system and unknown visibilities are not narrated

    def _render_event(self, data: dict) -> Text:
        event = data.get("event", {})
        label = _humanize_event_type(str(data.get("event_type", "Event")))
        actor = self.name_for(event.get("actor_id") or "") if event.get("actor_id") else None
        details: list[str] = []
        for key, value in event.items():
            if key in _EVENT_BASE_KEYS or value in (None, "", (), []):
                continue
            if key.endswith("_ids"):
                names = [self.name_for(str(item)) for item in value]
                names = [name for name in names if name]
                if names:
                    details.append(", ".join(names))
            elif key.endswith("_id"):
                name = self.name_for(str(value))
                if name is not None:
                    details.append(name)
            else:
                details.append(f"{key.replace('_', ' ')} {value}")
        line = f"{actor}: {label}" if actor else label
        if details:
            line += f" — {'; '.join(details)}"
        return Text(line, style="dim italic")

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
            return Text("Pick a player first: play <name>.")
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

        await self.backend.submit({
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
        characters = self.world.characters()
        if not characters:
            return Text("No players.")
        out = Text()
        for index, character in enumerate(characters):
            if index:
                out.append("\n")
            out.append(f"  {entity_icon(character)} ")
            out.append_text(link(entity_name(character), character["id"]))
            if character["id"] == self.player_id:
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

    def render_help(self, topic: str) -> Text:
        if topic and topic in self._defs:
            definition = self._defs[topic]
            keys = ", ".join(definition.arg_keys) or "(none)"
            return Text(
                f"{topic} — {definition.title or definition.command_type}\n  parameters: {keys}"
            )
        commands = ", ".join(sorted(self._defs))
        meta = ", ".join(m for m in META_COMMANDS if m != "exit")
        return Text(
            "Commands (try 'help <command>' for parameters):\n"
            f"  {commands}\n"
            f"Meta: {meta}\n"
            "Forms: 'move direction=north' (named) or 'go north' (natural). "
            "Click a highlighted target to drop its name into the input."
        )

    # ── completion ────────────────────────────────────────────────────────────
    def complete(self, line: str) -> list[str]:
        return complete_line(
            line,
            definitions=self._defs,
            # ``look``/``inventory`` are both tools and meta commands; list each word once.
            commands=tuple(dict.fromkeys((*self._defs, *META_COMMANDS))),
            entity_names=[name for name, _ in reference_candidates(self.world, self.player_id)],
            players=[entity_name(c) for c in self.world.characters()],
        )
