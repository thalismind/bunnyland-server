"""Event fanout for realtime clients."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any

from ..core.components import CharacterComponent
from ..core.ecs import container_of, parse_entity_id
from ..core.events import DomainEvent, serialized_event_visible_to
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
            while not self.queue.empty():
                self.queue.get_nowait()
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
        self._actor = actor
        self._recent_limit = recent_limit
        self._recent: deque[dict[str, Any]] = deque()
        self._audiences: dict[str, frozenset[str]] = {}
        self._started_at_epoch = actor.epoch
        self._discarded_through_epoch = actor.epoch
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
        event_data = message.get("data", {}).get("event", {})
        audience = frozenset(
            str(character.id)
            for character in self._actor.world.query()
            .with_all([CharacterComponent])
            .execute_entities()
            if serialized_event_visible_to(
                event_data,
                character_id=str(character.id),
                room_of=self._room_of,
            )
        )
        if len(self._recent) >= self._recent_limit:
            discarded = self._recent.popleft()
            discarded_event = discarded.get("data", {}).get("event", {})
            discarded_id = str(discarded_event.get("event_id", ""))
            self._audiences.pop(discarded_id, None)
            self._discarded_through_epoch = max(
                self._discarded_through_epoch,
                int(discarded_event.get("world_epoch", 0)),
            )
        self._recent.append(message)
        self._audiences[event.event_id] = audience
        self.broadcast(message)

    def _room_of(self, character_id: str) -> str | None:
        entity_id = parse_entity_id(character_id)
        if entity_id is None or not self._actor.world.has_entity(entity_id):
            return None
        room_id = container_of(self._actor.world.get_entity(entity_id))
        return str(room_id) if room_id is not None else None

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

    def changes_since(
        self, character_id: str, epoch: int
    ) -> tuple[list[dict[str, Any]], bool, int]:
        """Return occurrence-time-visible history and whether the bounded answer is complete."""

        available_after_epoch = max(self._started_at_epoch, self._discarded_through_epoch)
        complete = epoch >= available_after_epoch
        messages = []
        for message in self._recent:
            event = message.get("data", {}).get("event", {})
            if int(event.get("world_epoch", 0)) <= epoch:
                continue
            event_id = str(event.get("event_id", ""))
            if character_id in self._audiences.get(event_id, frozenset()):
                messages.append(message)
        return messages, complete, available_after_epoch

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
