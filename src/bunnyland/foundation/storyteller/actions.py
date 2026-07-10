"""Action metadata owned by bunnyland.storyteller."""

from ...core.actions import (
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action("resolve-incident", ("incident_id",), tool_name="resolve_incident"),
)

__all__ = ["ACTION_DEFINITIONS"]
