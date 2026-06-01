"""Discord-facing text views over server projections."""

from __future__ import annotations

from ..core.ecs import container_of
from ..core.events import CommandExecutedEvent, CommandRejectedEvent
from ..core.world_actor import WorldActor
from ..llm_agents.tools import tool_schemas
from ..projections import RoomSummaryProjection
from .claim import discord_controlled_character

HUMAN_HELP_TEXT = "\n".join(
    [
        "Available commands:",
        "!help [humans|agents|command] - show help.",
        "!characters - list character names.",
        "!claim [character] - control a character.",
        "!look - show your current room.",
        "!move <direction> - move through an exit.",
        "!say <text> - speak in the room.",
        "!take <item> - pick up an item.",
    ]
)
HELP_TEXT = HUMAN_HELP_TEXT

AGENT_HELP_LINES = [
    "Agent rules:",
    "You are a character inside a persistent ECS world, not an omniscient narrator.",
    (
        "Your prompt is your character's perspective: current room, visible entities, "
        "memories, needs, and mechanic-specific context."
    ),
    (
        "Act by choosing one available verb/tool with explicit arguments; the engine "
        "validates cost, reachability, controller generation, policy, and state."
    ),
    (
        "Action points pay for physical/world actions and usually regenerate over time. "
        "Focus points pay for private mental actions like notes, memory, and reflection."
    ),
    (
        "Inputs are names, directions, free text, and other prompt-visible references. "
        "Entity names are resolved by the server before commands run."
    ),
    (
        "Outputs are queued command results, domain events, updated prompts, memories, "
        "and world state changes visible to your character."
    ),
    (
        "You cannot mutate ECS directly, inspect hidden state, bypass consent/policy, "
        "or do anything a human controller could not do through the same verbs."
    ),
    (
        "Prefer concrete, small actions. If a reference is ambiguous or missing, use "
        "look, say, remember, or another in-world action to gather context."
    ),
    "Use !help <verb> for a short summary of a specific action surface.",
]
AGENT_HELP_TEXT = "\n".join(AGENT_HELP_LINES)


def _available_verbs(actor: WorldActor | None) -> tuple[str, ...]:
    if actor is None:
        return ()
    return actor.available_command_types()


def _verb_lines(actor: WorldActor | None) -> list[str]:
    verbs = _available_verbs(actor)
    if not verbs:
        return []
    return ["", "World verbs available now:", ", ".join(verbs)]


def _command_help(topic: str, actor: WorldActor | None = None) -> str:
    key = topic.strip().lower().replace("-", "_")
    available = set(_available_verbs(actor))
    for schema in tool_schemas():
        function = schema.get("function", {})
        name = function.get("name", "")
        if key not in {name, name.replace("_", "-")}:
            continue
        parameters = function.get("parameters", {}).get("properties", {})
        args = ", ".join(parameters) or "no arguments"
        return "\n".join(
            [
                f"Help for `{name}`:",
                function.get("description") or f"Character action: {name}",
                f"Arguments: {args}.",
                "Detailed command help is not written yet.",
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
            (
                "Try `!help humans`, `!help agents`, or `!help <verb>` for an "
                "available action verb."
            ),
        ]
    )


def render_help(topic: str | None = None, actor: WorldActor | None = None) -> str:
    """Render Discord help by topic."""

    normalized = (topic or "humans").strip().lower()
    if normalized in {"", "human", "humans"}:
        return "\n".join([HUMAN_HELP_TEXT, *_verb_lines(actor)])
    if normalized in {"agent", "agents", "llm", "llms"}:
        return "\n".join([AGENT_HELP_TEXT, *_verb_lines(actor)])
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
    return f"Done: {label}."


__all__ = [
    "AGENT_HELP_TEXT",
    "HELP_TEXT",
    "HUMAN_HELP_TEXT",
    "explain_rejection",
    "render_action_result",
    "render_help",
    "render_look",
    "render_move_result",
]
