"""Action metadata owned by bunnyland.storyteller."""

from ...core.actions import (
    EPIC_ACTION_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "resolve-incident",
        ("incident_id",),
        tool_name="resolve_incident",
        description=(
            "Resolve an active world incident, bringing a major unfolding "
            "event to its conclusion. This is an epic effort that dominates your turn."
        ),
        cost=EPIC_ACTION_COST,
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
