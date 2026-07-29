"""Action metadata owned by bunnyland.toonsim."""

from ...core.actions import (
    FREE_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "move-sprite",
        ("x", "y"),
        tool_name="move_sprite",
        description=(
            "Reposition your character's sprite to an X/Y spot within the current "
            "room without leaving it. Coordinates run 0-100 across the room and must "
            "stay inside its bounds and clear of solid furniture, doors, and other "
            "characters."
        ),
        cost=FREE_COST,
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
