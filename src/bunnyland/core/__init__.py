"""bunnyland core: ECS primitives, components, edges, events, commands, world actor.

This package wraps the synchronous Relics ECS with the async, event-driven,
command-queue architecture described in the bunnyland specification.
"""

from .commands import (
    Command,
    CommandCost,
    Lane,
    MoveCommand,
    OnInsufficientPoints,
    SubmittedCommand,
    WaitCommand,
    build_submitted_command,
)
from .components import (
    ActionPointsComponent,
    CharacterComponent,
    DeadComponent,
    DescriptionComponent,
    DownedComponent,
    FocusPointsComponent,
    IdentityComponent,
    InitiativeComponent,
    LifecycleComponent,
    RoomComponent,
    SuspendedComponent,
    WorldClockComponent,
)
from .controllers import (
    DiscordControllerComponent,
    LLMControllerComponent,
    SuspendedControllerComponent,
)
from .ecs import (
    container_of,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from .edges import ContainmentMode, Contains, ControlledBy, ExitTo, Holding, Wearing
from .events import DomainEvent, EventBus, EventVisibility
from .handlers import HandlerContext, HandlerResult, MoveHandler
from .queue import CommandQueues
from .world_actor import WorldActor

__all__ = [
    "ActionPointsComponent",
    "CharacterComponent",
    "Command",
    "CommandCost",
    "CommandQueues",
    "Contains",
    "ContainmentMode",
    "ControlledBy",
    "DeadComponent",
    "DescriptionComponent",
    "DiscordControllerComponent",
    "DomainEvent",
    "DownedComponent",
    "EventBus",
    "EventVisibility",
    "ExitTo",
    "FocusPointsComponent",
    "HandlerContext",
    "HandlerResult",
    "Holding",
    "IdentityComponent",
    "InitiativeComponent",
    "LLMControllerComponent",
    "Lane",
    "LifecycleComponent",
    "MoveCommand",
    "MoveHandler",
    "OnInsufficientPoints",
    "RoomComponent",
    "SubmittedCommand",
    "SuspendedComponent",
    "SuspendedControllerComponent",
    "WaitCommand",
    "Wearing",
    "WorldActor",
    "WorldClockComponent",
    "build_submitted_command",
    "container_of",
    "parse_entity_id",
    "replace_component",
    "spawn_entity",
]
