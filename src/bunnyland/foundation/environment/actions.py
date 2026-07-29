"""Action metadata owned by bunnyland.environment."""

from ...core.actions import (
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "ignite",
        ("target_id", "intensity"),
        tool_name="ignite",
        description=(
            "Set a flammable target alight, optionally choosing how intense "
            "the flame is. Watch what might catch fire nearby."
        ),
    ),
    define_action(
        "extinguish",
        ("target_id",),
        tool_name="extinguish",
        description=(
            "Put out a fire on a burning target before it spreads or causes "
            "more harm."
        ),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
