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
        description=(
            "Record important information in your notes so you can recall it "
            "later. Take a note whenever you learn something worth keeping."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("take note {text}", "note {text}"),
        examples=("take note the north tunnel is flooded",),
        chat_safe=True,
    ),
    define_action(
        "remember",
        ("query", "mode", "limit", "scope", "collection"),
        tool_name="remember",
        description=(
            "Search your own memories and notes for information relevant to "
            "a query. Remember before acting when you might already know something useful."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("remember {query}",),
        examples=("remember the north tunnel",),
        chat_safe=True,
    ),
    define_action(
        "forget",
        ("note_id", "scope", "collection"),
        tool_name="forget",
        description=(
            "Remove a specific note by its note id when it is outdated, "
            "wrong, or no longer useful."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("forget {note_id}",),
        examples=("forget note-123",),
        chat_safe=True,
    ),
    define_action(
        "reflect",
        ("text", "query", "mode", "limit"),
        tool_name="reflect",
        description=(
            "Reflect on recent notes or a topic and record a synthesized "
            "memory, turning scattered details into a lasting insight."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("reflect {text}",),
        examples=("reflect on the north tunnel",),
        chat_safe=True,
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
