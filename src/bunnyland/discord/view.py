"""Discord-facing text views over server projections."""

from __future__ import annotations

from typing import Any

from ..core.components import IdentityComponent, RoomComponent
from ..core.ecs import container_of, parse_entity_id
from ..core.events import CommandExecutedEvent, CommandRejectedEvent, NotesSearchedEvent
from ..core.world_actor import WorldActor
from ..llm_agents.tools import action_definitions
from ..projections import RoomSummaryProjection
from .claim import discord_controlled_character

DISCORD_MESSAGE_LIMIT = 2000
HELP_MESSAGE_LIMIT = 1990
HELP_VERBS_PER_PAGE = 16

HUMAN_HELP_TEXT = "\n".join(
    [
        "Available commands:",
        "!help [humans|agents|command] - show help.",
        "!characters - list character names.",
        "!claim [character] - control a character.",
        "!fallback suspend|llm [minutes] - set timeout fallback and optional 5-60 minute timeout.",
        "!release - hand your character back to the LLM.",
        "!suspend - pause your character until they are claimed again.",
        "!look - show your current room.",
        "!<verb> ... - run any available world verb.",
        "Use key=value pairs or JSON for verbs without documented arguments.",
    ]
)
HELP_TEXT = HUMAN_HELP_TEXT

AGENT_HELP_LINES = [
    "Agent help:",
    "You are a character in a persistent ECS world, not an omniscient narrator.",
    (
        "Your prompt is your perspective: room, visible entities, memories, needs, "
        "and loaded mechanic context."
    ),
    (
        "Act by choosing one available verb/tool with explicit arguments. The engine "
        "validates cost, reachability, controller generation, policy, and state."
    ),
    ("Action points pay for physical/world actions and usually regenerate over time."),
    ("Focus points pay for private mental actions like notes, memory, and reflection."),
    (
        "Inputs are names, directions, free text, and other prompt-visible references. "
        "The server resolves entity names before commands run."
    ),
    ("Outputs are command results, events, updated prompts, memories, and visible world changes."),
    (
        "You cannot mutate ECS directly, inspect hidden state, bypass consent/policy, "
        "or do anything a human could not do through the same verbs."
    ),
    (
        "Prefer concrete, small actions. If context is missing, use look, say, remember, "
        "or another in-world action."
    ),
    "Use !help verbs for the full current verb list, or !help <verb> for one action.",
]
AGENT_HELP_TEXT = "\n".join(AGENT_HELP_LINES)


def _available_verbs(actor: WorldActor | None) -> tuple[str, ...]:
    if actor is None:
        return ()
    return actor.available_command_types()


def _wrapped_inline_lines(header: str, items: tuple[str, ...]) -> list[str]:
    lines = ["", header]
    current = ""
    for item in items:
        piece = item if not current else f", {item}"
        if current and len(current) + len(piece) > 900:
            lines.append(current)
            current = item
        else:
            current += piece
    if current:
        lines.append(current)
    return lines


def _verb_name_lines(actor: WorldActor | None) -> list[str]:
    verbs = _available_verbs(actor)
    if not verbs:
        return []
    return _wrapped_inline_lines("World verbs available now:", verbs)


def _actor_action_definitions(actor: WorldActor | None):
    extra = actor.action_definitions() if actor is not None else ()
    return action_definitions(extra)


def _tool_argument_index(actor: WorldActor | None) -> dict[str, str]:
    by_verb: dict[str, str] = {}
    for definition in _actor_action_definitions(actor):
        name = definition.name
        args = ", ".join(definition.arg_keys)
        summary = args or "no arguments"
        by_verb[name] = summary
        by_verb[name.replace("_", "-")] = summary
        by_verb[definition.command_type] = summary
    return by_verb


def _verb_detail_lines(actor: WorldActor | None, *, page: int = 1) -> list[str]:
    verbs = _available_verbs(actor)
    if not verbs:
        return []
    args_by_verb = _tool_argument_index(actor)
    page_count = max(1, (len(verbs) + HELP_VERBS_PER_PAGE - 1) // HELP_VERBS_PER_PAGE)
    page = max(1, min(page, page_count))
    start = (page - 1) * HELP_VERBS_PER_PAGE
    selected = verbs[start : start + HELP_VERBS_PER_PAGE]
    lines = [f"World verbs available now (page {page}/{page_count}):"]
    for verb in selected:
        args = args_by_verb.get(verb, "no documented arguments")
        lines.append(f"{verb}: {args}")
    if page < page_count:
        lines.append(f"Use !help verbs {page + 1} for the next page.")
    return lines


def split_discord_text(text: str, *, limit: int = HELP_MESSAGE_LIMIT) -> tuple[str, ...]:
    """Split a Discord message into chunks safely below the API content limit."""

    if limit <= 0 or limit > DISCORD_MESSAGE_LIMIT:
        raise ValueError("limit must be between 1 and Discord's message limit")
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        pending = line
        while len(pending) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(pending[:limit])
            pending = pending[limit:]
        candidate = pending if not current else f"{current}\n{pending}"
        if len(candidate) > limit:
            chunks.append(current)
            current = pending
        else:
            current = candidate
    if current:
        chunks.append(current)
    return tuple(chunks or ("",))


def _command_help(topic: str, actor: WorldActor | None = None) -> str:
    key = topic.strip().lower().replace("-", "_")
    available = set(_available_verbs(actor))
    for definition in _actor_action_definitions(actor):
        if key not in {definition.name, definition.name.replace("_", "-"), definition.command_type}:
            continue
        args = []
        for name, argument in (definition.arguments or {}).items():
            detail = argument.description or argument.title
            required = "required" if argument.required else "optional"
            args.append(f"- {name} ({argument.kind}, {required}){': ' + detail if detail else ''}")
        examples = [f"- {example.text}" for example in definition.examples]
        return "\n".join(
            [
                f"Help for `{definition.name}`:",
                definition.description
                or definition.title
                or f"Character action: {definition.name}",
                "Arguments:",
                *(args or ["- no arguments"]),
                *(["Examples:", *examples] if examples else []),
            ]
        )
    return "\n".join(
        [
            f"No detailed help is available for `{topic}` yet.",
            (
                "This command is available in the current world."
                if topic in available
                else "It may not be available in the current world."
            ),
            ("Try `!help humans`, `!help agents`, or `!help <verb>` for an available action verb."),
        ]
    )


def render_help(topic: str | None = None, actor: WorldActor | None = None) -> str:
    """Render Discord help by topic."""

    normalized = (topic or "humans").strip().lower()
    parts = normalized.split()
    head = parts[0] if parts else ""
    if normalized in {"", "human", "humans"}:
        return "\n".join([HUMAN_HELP_TEXT, *_verb_name_lines(actor)])
    if normalized in {"agent", "agents", "llm", "llms"}:
        return AGENT_HELP_TEXT
    if head in {"verb", "verbs", "commands", "actions"}:
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        lines = _verb_detail_lines(actor, page=page)
        if not lines:
            return "No world verbs are available."
        return "\n".join(lines).strip()
    return _command_help(normalized, actor)


def render_look(actor: WorldActor, discord_user_id: int) -> str:
    """Render the controlled character's current room via ``RoomSummaryProjection``."""

    found = discord_controlled_character(actor, discord_user_id)
    if found is None:
        return "You are not controlling a character yet."
    character_id, _controller_id, _generation = found
    room_id = container_of(actor.world.get_entity(character_id))
    if room_id is None:
        return "You are nowhere."
    summary = RoomSummaryProjection(actor.world).attach().summary(room_id, actor.epoch)
    return summary.visible_summary


def explain_rejection(reason: str) -> str:
    """Turn a terse gate rejection into player-facing guidance (no trailing period).

    Permission gates (points, consent, adult/world policy) reject with short reasons aimed
    at the engine; players need to know *what to do next*, so the known gate categories get
    a helpful suffix. Unrecognized reasons pass through unchanged.
    """

    lowered = reason.lower()
    if "insufficient points" in lowered:
        return (
            "you don't have enough action points for that right now — they regenerate "
            "over time, so wait a bit and try again"
        )
    if "has not consented to" in lowered:
        return f"{reason} — they would need to opt in before you can do that"
    if "is disabled in this world" in lowered:
        return f"{reason} — an admin has turned that off for this world"
    if "is not enabled here" in lowered:
        return f"{reason} — this world only allows it when everyone involved has opted in"
    return reason


def render_move_result(
    actor: WorldActor,
    discord_user_id: int,
    event: CommandExecutedEvent | CommandRejectedEvent,
) -> str:
    """Render a Discord response for a completed move command."""

    if isinstance(event, CommandRejectedEvent):
        return f"Move failed: {explain_rejection(event.reason)}."
    return "You are now in " + render_look(actor, discord_user_id)


def _entity_name(actor: WorldActor, raw_id: object) -> str | None:
    entity_id = parse_entity_id(str(raw_id))
    if entity_id is None or not actor.world.has_entity(entity_id):
        return None
    entity = actor.world.get_entity(entity_id)
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    if entity.has_component(RoomComponent):
        return entity.get_component(RoomComponent).title
    return str(entity_id)


def _display_value(actor: WorldActor, value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(_display_value(actor, item) for item in value)
    name = _entity_name(actor, value)
    if name is not None:
        return name
    return str(value)


def _display_key(key: str) -> str:
    label = key.removesuffix("_ids").removesuffix("_id")
    return label.replace("_", " ")


def _payload_summary(actor: WorldActor, payload: dict[str, Any]) -> str:
    items = [(key, value) for key, value in payload.items() if value not in (None, "")]
    if len(items) == 1:
        key, value = items[0]
        if key.endswith("_id") or key.endswith("_ids") or _entity_name(actor, value) is not None:
            return _display_value(actor, value)
    parts = [f"{_display_key(key)} {_display_value(actor, value)}" for key, value in items]
    return "; ".join(parts)


def _actor_context(actor: WorldActor, event: CommandExecutedEvent) -> str:
    actor_name = _entity_name(actor, event.actor_id) or "character"
    actor_id = parse_entity_id(event.actor_id or "")
    if actor_id is None or not actor.world.has_entity(actor_id):
        return actor_name
    room_id = container_of(actor.world.get_entity(actor_id))
    room_name = _entity_name(actor, room_id) if room_id is not None else None
    if room_name:
        return f"{actor_name} in {room_name}"
    return actor_name


def _humanize_event_type(event_type: str) -> str:
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


_DOMAIN_EVENT_SKIP_KEYS = frozenset(
    {
        "actor_id",
        "causation_id",
        "correlation_id",
        "created_at",
        "event_id",
        "event_type",
        "room_id",
        "target_ids",
        "visibility",
        "world_epoch",
    }
)


def _render_domain_event(actor: WorldActor, event: dict[str, Any]) -> str:
    if event.get("event_type") == "ShipSystemInspectedEvent":
        system = _entity_name(actor, event.get("system_id")) or str(event.get("system_id"))
        details = _payload_summary(
            actor,
            {
                key: event[key]
                for key in ("system_type", "integrity", "online")
                if key in event and event[key] not in (None, "", (), [])
            },
        )
        if details:
            return f"Inspect ship system complete: {system}. {details}."
        return f"Inspect ship system complete: {system}."
    label = _humanize_event_type(str(event.get("event_type", "GameEvent")))
    details = _payload_summary(
        actor,
        {
            key: value
            for key, value in event.items()
            if key not in _DOMAIN_EVENT_SKIP_KEYS
            and value not in (None, "", (), [])
            and not (key.endswith("_id") and _entity_name(actor, value) is None)
            and not (
                key.endswith("_ids") and all(_entity_name(actor, item) is None for item in value)
            )
        },
    )
    if details:
        return f"{label}: {details}."
    return f"{label}."


def _render_success(actor: WorldActor, event: CommandExecutedEvent) -> str:
    if event.result_events:
        return "\n".join(_render_domain_event(actor, item) for item in event.result_events)
    label = event.command_type.replace("-", " ")
    if event.payload:
        details = _payload_summary(actor, event.payload)
        return f"{label.capitalize()} complete: {details}."
    return f"{label.capitalize()} complete for {_actor_context(actor, event)}."


def render_action_result(
    actor: WorldActor,
    discord_user_id: int,
    tool: str,
    event: CommandExecutedEvent | CommandRejectedEvent,
) -> str:
    """Render a Discord confirmation for a completed action command."""

    if tool == "move":
        return render_move_result(actor, discord_user_id, event)
    label = tool.replace("_", " ")
    if isinstance(event, CommandRejectedEvent):
        return f"{label.capitalize()} failed: {explain_rejection(event.reason)}."
    return _render_success(actor, event)


def render_notes_search_result(event: NotesSearchedEvent) -> str:
    if not event.results:
        return "No matching notes."
    lines = [f"Notes for {event.query!r}:" if event.query else "Recent notes:"]
    for index, result in enumerate(event.results):
        note_id = event.note_ids[index] if index < len(event.note_ids) else ""
        prefix = f"- `{note_id}` " if note_id else "- "
        lines.append(f"{prefix}{result}")
    return "\n".join(lines)


__all__ = [
    "AGENT_HELP_TEXT",
    "DISCORD_MESSAGE_LIMIT",
    "HELP_TEXT",
    "HELP_MESSAGE_LIMIT",
    "HUMAN_HELP_TEXT",
    "explain_rejection",
    "render_action_result",
    "render_help",
    "render_look",
    "render_move_result",
    "render_notes_search_result",
    "split_discord_text",
]
