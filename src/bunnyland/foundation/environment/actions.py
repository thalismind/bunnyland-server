"""Action metadata owned by bunnyland.environment."""

from ...core.actions import (
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action("ignite", ("target_id", "intensity"), tool_name="ignite"),
    define_action("extinguish", ("target_id",), tool_name="extinguish"),
)

__all__ = ["ACTION_DEFINITIONS"]
