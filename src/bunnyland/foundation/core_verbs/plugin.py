"""Canonical Core Verbs plugin entrypoint."""

from ...core.components import (
    AdminComponent,
    ConversationComponent,
    HoldableComponent,
    WearableComponent,
)
from ...core.edges import ConversationParticipant
from ...core.events import (
    ContainerClosedEvent,
    ContainerOpenedEvent,
    ConversationEndedEvent,
    ConversationLineEvent,
    ConversationStartedEvent,
    DoorClosedEvent,
    DoorOpenedEvent,
    EntityInspectedEvent,
    EntityLockedEvent,
    EntityUnlockedEvent,
    ItemHeldEvent,
    ItemRemovedEvent,
    ItemUnheldEvent,
    ItemWornEvent,
    RoomLookedEvent,
)
from ...core.handlers import (
    CloseHandler,
    ConversationLineHandler,
    DropHandler,
    EndConversationHandler,
    HoldHandler,
    InspectHandler,
    LockHandler,
    LookHandler,
    MoveHandler,
    OpenHandler,
    PutHandler,
    RemoveHandler,
    SayHandler,
    SleepHandler,
    StartConversationHandler,
    TakeHandler,
    TellHandler,
    UnholdHandler,
    UnlockHandler,
    UseHandler,
    WaitHandler,
    WakeHandler,
    WearHandler,
    WriteHandler,
)
from ...plugins.ids import CORE_VERBS
from ...plugins.model import (
    CommandContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
)
from .actions import ACTION_DEFINITIONS


def _definition() -> Plugin:
    return Plugin(
        id=CORE_VERBS,
        name="Core Verbs",
        ecs=EcsContribution(
            components=(
                AdminComponent,
                ConversationComponent,
                HoldableComponent,
                WearableComponent,
            ),
            edges=(ConversationParticipant,),
        ),
        commands=CommandContribution(
            action_definitions=ACTION_DEFINITIONS,
            action_handlers=(
                LookHandler,
                InspectHandler,
                MoveHandler,
                TakeHandler,
                DropHandler,
                PutHandler,
                OpenHandler,
                CloseHandler,
                LockHandler,
                UnlockHandler,
                HoldHandler,
                UnholdHandler,
                WearHandler,
                RemoveHandler,
                UseHandler,
                WriteHandler,
                SleepHandler,
                WakeHandler,
                WaitHandler,
                SayHandler,
                TellHandler,
                StartConversationHandler,
                ConversationLineHandler,
                EndConversationHandler,
            ),
            typed_events=(
                ConversationStartedEvent,
                ConversationLineEvent,
                ConversationEndedEvent,
                RoomLookedEvent,
                EntityInspectedEvent,
                ContainerOpenedEvent,
                ContainerClosedEvent,
                DoorOpenedEvent,
                DoorClosedEvent,
                EntityLockedEvent,
                EntityUnlockedEvent,
                ItemHeldEvent,
                ItemUnheldEvent,
                ItemWornEvent,
                ItemRemovedEvent,
            ),
        ),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.CORE})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
