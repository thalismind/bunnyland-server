"""Action metadata owned by bunnyland.factions."""

from ...core.actions import EXTENDED_FOCUS_COST, FOCUS_COST, ActionDefinition, define_action
from ...core.commands import Lane

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "join-faction",
        ("faction_id", "rank"),
        tool_name="join_faction",
        description=(
            "Join a public faction at a chosen rank. The target must be a public faction "
            "you do not already belong to; secret affiliations cannot be joined publicly."
        ),
        lane=Lane.FOCUS,
        cost=EXTENDED_FOCUS_COST,
        patterns=("join faction {faction_id}",),
    ),
    define_action(
        "leave-faction",
        ("faction_id",),
        tool_name="leave_faction",
        description=(
            "Resign membership in a public faction you currently belong to. Secret "
            "affiliations cannot be exposed or changed through this public action."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("leave faction {faction_id}",),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
