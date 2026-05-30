"""Event-driven projections: read-side caches rebuilt from ECS state (spec 17, 23.9).

Projections never own truth. They observe domain events to mark themselves stale, then
rebuild deterministically from the authoritative Relics world on demand. The prompt
builder (a later phase) consumes them.
"""

from .perception import PerceivedEntity, Perception, perceive
from .recent_context import RecentContextProjection
from .room_summary import (
    RoomExit,
    RoomFacts,
    RoomObject,
    RoomSummaryProjection,
    SummaryRenderer,
    build_room_facts,
    render_summary,
)

__all__ = [
    "PerceivedEntity",
    "Perception",
    "RecentContextProjection",
    "RoomExit",
    "RoomFacts",
    "RoomObject",
    "RoomSummaryProjection",
    "SummaryRenderer",
    "build_room_facts",
    "perceive",
    "render_summary",
]
