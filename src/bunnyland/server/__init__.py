"""Optional server API helpers for web clients.

The dependency-free pieces in this package expose world snapshots and event streams. The
FastAPI app factory is imported lazily by callers that install web-server dependencies.
"""

from .models import CommandRequest, CommandResponse
from .serialization import event_message, serialize_event, serialize_world
from .subscriptions import EventStream, EventSubscription

__all__ = [
    "CommandRequest",
    "CommandResponse",
    "EventStream",
    "EventSubscription",
    "event_message",
    "serialize_event",
    "serialize_world",
]
