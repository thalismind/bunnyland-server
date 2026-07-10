"""Event fanout for realtime clients."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any

from ..core.events import DomainEvent
from ..core.world_actor import WorldActor
from .serialization import event_message


@dataclass(frozen=True)
class EventSubscription:
    """A bounded queue registered with an ``EventStream``."""

    stream: EventStream
    queue: asyncio.Queue[dict[str, Any]]

    def close(self) -> None:
        self.stream.unsubscribe(self)


class EventStream:
    """Records recent domain events and fans out new ones to websocket clients."""

    def __init__(self, actor: WorldActor, *, recent_limit: int = 200) -> None:
        self._recent: deque[dict[str, Any]] = deque(maxlen=recent_limit)
        self._subscribers: set[EventSubscription] = set()
        self._registry = actor.plugins
        actor.bus.subscribe(DomainEvent, self.record)

    def record(self, event: DomainEvent) -> None:
        message = event_message(event, self._registry)
        self._recent.append(message)
        self.broadcast(message)

    def broadcast(self, message: dict[str, Any]) -> None:
        """Fan out a websocket message without adding it to recent domain history."""
        for subscription in tuple(self._subscribers):
            queue = subscription.queue
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(message)

    def recent_messages(self) -> list[dict[str, Any]]:
        return list(self._recent)

    def subscribe(self, *, max_queue_size: int = 100) -> EventSubscription:
        subscription = EventSubscription(self, asyncio.Queue(maxsize=max_queue_size))
        self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        self._subscribers.discard(subscription)


__all__ = ["EventStream", "EventSubscription"]
