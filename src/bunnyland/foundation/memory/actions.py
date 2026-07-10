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
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("take note {text}", "note {text}"),
    ),
    define_action(
        "remember",
        ("query", "mode", "limit", "scope", "collection"),
        tool_name="remember",
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("remember {query}",),
    ),
    define_action(
        "forget",
        ("note_id", "scope", "collection"),
        tool_name="forget",
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("forget {note_id}",),
    ),
    define_action(
        "reflect",
        ("text", "query", "mode", "limit"),
        tool_name="reflect",
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("reflect {text}",),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
