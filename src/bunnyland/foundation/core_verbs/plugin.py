"""Canonical Core Verbs plugin entrypoint."""

from ...core.components import (
    AdminComponent,
    ConversationComponent,
    HoldableComponent,
    RestingComponent,
    RoomGateComponent,
    WearableComponent,
)
from ...core.consequences import ConversationConsequence
from ...core.edges import AllowsMembersOf, ConversationParticipant, KnowsRoom, StudiedBy
from ...core.events import (
    CharacterWokeEvent,
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
    RestEndedEvent,
    RestStartedEvent,
    RoomLookedEvent,
    SleepStartedEvent,
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
    RestHandler,
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
from ...core.perspective import V1_PERSPECTIVE_QUERIES
from ...core.recovery import install_recovery, recovery_fragments
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


def _install_conversation_lifecycle(actor, _context=None) -> None:
    actor.register_consequence(ConversationConsequence())


def _definition() -> Plugin:
    return Plugin(
        id=CORE_VERBS,
        name="Core Verbs",
        ecs=EcsContribution(
            components=(
                AdminComponent,
                ConversationComponent,
                HoldableComponent,
                RestingComponent,
                RoomGateComponent,
                WearableComponent,
            ),
            edges=(AllowsMembersOf, ConversationParticipant, KnowsRoom, StudiedBy),
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
                RestHandler,
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
                RestStartedEvent,
                RestEndedEvent,
                SleepStartedEvent,
                CharacterWokeEvent,
            ),
        ),
        runtime=RuntimeContribution(
            integration_factories=(_install_conversation_lifecycle, install_recovery),
            perspective_queries=V1_PERSPECTIVE_QUERIES,
        ),
        content=ContentContribution(prompt_fragments=(recovery_fragments,)),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.CORE})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
