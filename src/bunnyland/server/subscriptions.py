"""Event fanout for realtime clients."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any

from ..core.events import DomainEvent
from ..core.world_actor import WorldActor
from .serialization import event_message

STREAM_PROTOCOL_VERSION = 1
PROJECTION_VERSION = 1


@dataclass(eq=False)
class EventSubscription:
    """A bounded queue registered with an ``EventStream``."""

    stream: EventStream
    queue: asyncio.Queue[dict[str, Any]]
    dropped: bool = False
    stream_sequence: int = 0

    def close(self) -> None:
        self.stream.unsubscribe(self)

    def consume_dropped(self) -> bool:
        dropped = self.dropped
        self.dropped = False
        if dropped:
            self.stream.resyncs += 1
        return dropped

    def frame(self, actor: WorldActor, message: dict[str, Any]) -> dict[str, Any]:
        """Version one externally delivered frame and assign its connection sequence."""

        self.stream_sequence += 1
        data = message.get("data")
        event = data.get("event") if isinstance(data, dict) else None
        event = event if isinstance(event, dict) else {}
        return {
            **message,
            "world_id": str(getattr(actor, "world_id", "")),
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "projection_version": PROJECTION_VERSION,
            "world_epoch": int(event.get("world_epoch") or actor.epoch),
            "stream_sequence": self.stream_sequence,
            "event_id": event.get("event_id"),
            "causal_command_id": event.get("causation_id") or event.get("command_id"),
        }


class EventStream:
    """Records recent domain events and fans out new ones to websocket clients."""

    def __init__(self, actor: WorldActor, *, recent_limit: int = 200) -> None:
        self._recent: deque[dict[str, Any]] = deque(maxlen=recent_limit)
        self._subscribers: set[EventSubscription] = set()
        self._registry = actor.plugins
        self.connections_total = 0
        self.connections_closed = 0
        self.dropped_frames = 0
        self.resyncs = 0
        self.max_queue_depth = 0
        self.projection_count = 0
        self.projection_latency_seconds = 0.0
        self.projection_latency_max_seconds = 0.0
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
                subscription.dropped = True
                self.dropped_frames += 1
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(message)
            self.max_queue_depth = max(self.max_queue_depth, queue.qsize())

    def recent_messages(self) -> list[dict[str, Any]]:
        return list(self._recent)

    def subscribe(self, *, max_queue_size: int = 100) -> EventSubscription:
        subscription = EventSubscription(self, asyncio.Queue(maxsize=max_queue_size))
        self._subscribers.add(subscription)
        self.connections_total += 1
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        if subscription in self._subscribers:
            self._subscribers.discard(subscription)
            self.connections_closed += 1

    def record_projection_latency(self, seconds: float) -> None:
        self.projection_count += 1
        self.projection_latency_seconds += seconds
        self.projection_latency_max_seconds = max(self.projection_latency_max_seconds, seconds)

    def stats(self) -> dict[str, int | float]:
        return {
            "connections": len(self._subscribers),
            "connections_total": self.connections_total,
            "reconnects": self.connections_closed,
            "dropped_frames": self.dropped_frames,
            "resyncs": self.resyncs,
            "queue_depth": sum(item.queue.qsize() for item in self._subscribers),
            "max_queue_depth": self.max_queue_depth,
            "projection_count": self.projection_count,
            "projection_latency_seconds": (
                self.projection_latency_seconds / self.projection_count
                if self.projection_count
                else 0.0
            ),
            "projection_latency_max_seconds": self.projection_latency_max_seconds,
        }


__all__ = [
    "EventStream",
    "EventSubscription",
    "PROJECTION_VERSION",
    "STREAM_PROTOCOL_VERSION",
]
