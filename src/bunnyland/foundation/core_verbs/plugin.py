"""Canonical Core Verbs plugin entrypoint."""

from ...core.components import (
    AdminComponent,
    ConversationComponent,
    HoldableComponent,
    WearableComponent,
)
from ...core.edges import ConversationParticipant, DetectedStealth, KnowsRoom
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
    StealthChangedEvent,
    StealthDetectedEvent,
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
    SneakHandler,
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
from ...core.perspective import V1_PERSPECTIVE_QUERIES
from ...plugins.ids import CORE_VERBS
from ...plugins.model import (
    CommandContribution,
    ContentContribution,
    EcsContribution,
    Plugin,
    PluginPlacement,
    RuntimeContribution,
)
from .actions import ACTION_DEFINITIONS
from .stealth import stealth_fragments


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
            edges=(ConversationParticipant, DetectedStealth, KnowsRoom),
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
                SneakHandler,
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
                StealthChangedEvent,
                StealthDetectedEvent,
            ),
        ),
        runtime=RuntimeContribution(perspective_queries=V1_PERSPECTIVE_QUERIES),
        content=ContentContribution(prompt_fragments=(stealth_fragments,)),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.CORE})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
