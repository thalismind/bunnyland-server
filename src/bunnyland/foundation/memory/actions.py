"""Action metadata owned by bunnyland.memory."""

from ...core.actions import (
    FOCUS_COST,
    ActionDefinition,
    define_action,
)
from ...core.commands import Lane

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "take-note",
        ("text", "tags", "scope", "collection"),
        tool_name="take_note",
        description="Record important information in the character's private or shared notes.",
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("take note {text}", "note {text}"),
        examples=("take note the north tunnel is flooded",),
    ),
    define_action(
        "remember",
        ("query", "mode", "limit", "scope", "collection"),
        tool_name="remember",
        description="Search the character's memories and notes for relevant information.",
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("remember {query}",),
        examples=("remember the north tunnel",),
    ),
    define_action(
        "forget",
        ("note_id", "scope", "collection"),
        tool_name="forget",
        description="Remove a specific note by its note id.",
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("forget {note_id}",),
        examples=("forget note-123",),
    ),
    define_action(
        "reflect",
        ("text", "query", "mode", "limit"),
        tool_name="reflect",
        description="Reflect on recent notes or a topic and record a synthesized memory.",
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("reflect {text}",),
        examples=("reflect on the north tunnel",),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
