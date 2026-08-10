"""Player-visible action metadata for the sandbox plugin."""

from ..core.actions import (
    ACTION_COST,
    FREE_COST,
    ActionArgument,
    ActionDefinition,
    ActionPattern,
    ActionRequirement,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    ActionDefinition(
        command_type="accept-after-dark-warning",
        tool_name="accept_after_dark_warning",
        title="Accept After Dark Warning",
        description=(
            "Acknowledge that After Dark is an optional adults-only district. This records "
            "the character's explicit consent to enter; it does not enable any separate "
            "adult interaction boundary."
        ),
        icon="✅",
        cost=FREE_COST,
        arguments={
            "acknowledged": ActionArgument(
                title="Acknowledged",
                description="Must be true to record explicit acknowledgement.",
                kind="boolean",
                required=True,
            )
        },
        natural_patterns=(
            ActionPattern(
                "accept after dark warning",
                fixed_arguments={"acknowledged": True},
            ),
        ),
    ),
    ActionDefinition(
        command_type="enter-after-dark",
        tool_name="enter_after_dark",
        title="Enter After Dark",
        description=(
            "Enter the optional After Dark district through a nearby marked entrance. "
            "The character must have accepted the warning and remain allowed by world policy."
        ),
        icon="🚪",
        cost=ACTION_COST,
        arguments={
            "entrance_id": ActionArgument(
                title="Entrance",
                description="A reachable After Dark entrance marker.",
                kind="entity",
                required=True,
            )
        },
        natural_patterns=(ActionPattern("enter after dark through {entrance_id}"),),
        requirement=ActionRequirement(
            reachable_components=("AfterDarkEntranceComponent",),
        ),
    ),
    ActionDefinition(
        command_type="leave-after-dark",
        tool_name="leave_after_dark",
        title="Leave After Dark",
        description=(
            "Leave After Dark through a nearby marked exit. Consent is never required "
            "to leave."
        ),
        icon="🚪",
        cost=ACTION_COST,
        arguments={
            "exit_id": ActionArgument(
                title="Exit",
                description="A reachable After Dark exit marker.",
                kind="entity",
                required=True,
            )
        },
        natural_patterns=(ActionPattern("leave after dark through {exit_id}"),),
        requirement=ActionRequirement(
            reachable_components=("AfterDarkExitComponent",),
        ),
    ),
    ActionDefinition(
        command_type="withdraw-after-dark-consent",
        tool_name="withdraw_after_dark_consent",
        title="Withdraw After Dark Consent",
        description=(
            "Withdraw this character's After Dark entry consent. This prevents future entry "
            "but never prevents leaving the district."
        ),
        icon="✋",
        cost=FREE_COST,
        natural_patterns=(ActionPattern("withdraw after dark consent"),),
    ),
)


__all__ = ["ACTION_DEFINITIONS"]
