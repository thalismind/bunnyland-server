"""Action metadata owned by bunnyland.toonsim."""

from ...core.actions import (
    FREE_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action("move-sprite", ("x", "y"), tool_name="move_sprite", cost=FREE_COST),
)

__all__ = ["ACTION_DEFINITIONS"]
