"""Action metadata owned by bunnyland.social."""

from ...core.actions import (
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "resolve-obligation",
        ("obligation_id", "status", "note"),
        tool_name="resolve_obligation",
        description=(
            "Settle an obligation you owe or are owed by marking it "
            "fulfilled, failed, or cancelled, and optionally leave a note about the outcome."
        ),
        patterns=(
            "fulfill {obligation_id}",
            "fail {obligation_id}",
            "cancel {obligation_id}",
            "resolve {obligation_id}",
        ),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
