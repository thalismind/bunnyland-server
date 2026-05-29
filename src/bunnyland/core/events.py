"""Typed domain events and a lightweight event bus (spec section 18).

Events are typed Pydantic models. Handlers subscribe to concrete event classes (or a
base class to receive a whole hierarchy). The bus is owned by the world actor and
dispatched synchronously within a tick; async handlers are awaited.

These are bunnyland's own domain events, distinct from Relics' internal ``CustomEvent``
observer system. The world actor is the single emitter, so ordering is deterministic.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import TypeVar

from pydantic import BaseModel, ConfigDict


class EventVisibility(StrEnum):
    PUBLIC = "public"
    ROOM = "room"
    DIRECTED = "directed"
    PRIVATE = "private"
    SYSTEM = "system"


class DomainEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    world_epoch: int
    created_at: datetime

    visibility: EventVisibility = EventVisibility.SYSTEM
    actor_id: str | None = None
    room_id: str | None = None
    target_ids: tuple[str, ...] = ()

    causation_id: str | None = None
    correlation_id: str | None = None


# --------------------------------------------------------------------------------------
# Command lifecycle events (spec 18.3)
# --------------------------------------------------------------------------------------


class CommandSubmittedEvent(DomainEvent):
    command_id: str
    command_type: str


class CommandAcceptedEvent(DomainEvent):
    command_id: str
    command_type: str


class CommandRejectedEvent(DomainEvent):
    command_id: str
    command_type: str
    reason: str


class CommandQueuedEvent(DomainEvent):
    command_id: str
    command_type: str
    lane: str


class CommandExecutedEvent(DomainEvent):
    command_id: str
    command_type: str


class CommandExpiredEvent(DomainEvent):
    command_id: str
    command_type: str


# --------------------------------------------------------------------------------------
# Points and controller events
# --------------------------------------------------------------------------------------


class ActionPointsChangedEvent(DomainEvent):
    current: float
    maximum: float


class FocusPointsChangedEvent(DomainEvent):
    current: float
    maximum: float


class ControllerChangedEvent(DomainEvent):
    generation: int
    controller_kind: str


# --------------------------------------------------------------------------------------
# Movement / world events
# --------------------------------------------------------------------------------------


class ActorMovedEvent(DomainEvent):
    from_room_id: str
    to_room_id: str
    direction: str | None = None


# --------------------------------------------------------------------------------------
# Inventory / object events (spec 18.3)
# --------------------------------------------------------------------------------------


class ItemTakenEvent(DomainEvent):
    item_id: str
    from_container_id: str


class ItemPutEvent(DomainEvent):
    item_id: str
    to_container_id: str


class ItemDroppedEvent(DomainEvent):
    item_id: str
    room_id_dropped: str


# --------------------------------------------------------------------------------------
# Speech events (spec 14, 18.3). Visibility distinguishes room speech from directed.
# --------------------------------------------------------------------------------------


class SpeechSaidEvent(DomainEvent):
    text: str
    author_intent: str | None = None
    inferred_intent: str | None = None
    final_interpretation: str | None = None


class SpeechToldEvent(DomainEvent):
    text: str
    author_intent: str | None = None
    inferred_intent: str | None = None
    final_interpretation: str | None = None


# --------------------------------------------------------------------------------------
# Event bus
# --------------------------------------------------------------------------------------

E = TypeVar("E", bound=DomainEvent)
Handler = Callable[[DomainEvent], None | Awaitable[None]]


class EventBus:
    """Synchronous-ordered dispatch with support for async handlers.

    Subscriptions are keyed by event class. Subscribing to a base class (e.g.
    ``DomainEvent``) receives every subclass, enabling audit/logging sinks.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        for event_type, handlers in self._handlers.items():
            if isinstance(event, event_type):
                for handler in handlers:
                    result = handler(event)
                    if isinstance(result, Awaitable):
                        await result


__all__ = [
    "ActionPointsChangedEvent",
    "ActorMovedEvent",
    "CommandAcceptedEvent",
    "CommandExecutedEvent",
    "CommandExpiredEvent",
    "CommandQueuedEvent",
    "CommandRejectedEvent",
    "CommandSubmittedEvent",
    "ControllerChangedEvent",
    "DomainEvent",
    "EventBus",
    "EventVisibility",
    "FocusPointsChangedEvent",
    "ItemDroppedEvent",
    "ItemPutEvent",
    "ItemTakenEvent",
    "SpeechSaidEvent",
    "SpeechToldEvent",
]
