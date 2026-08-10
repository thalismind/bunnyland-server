"""Request an image of a character's current scene (spec 27).

Shared by every client that offers the camera affordance (Discord, TUI, REPL, the web
endpoint): it records the character's current room as a ``scene`` world-history event and
asks the service to illustrate it. Recording the moment durably means the image persists with
that event and repeated requests in the same tick reuse it.
"""

from __future__ import annotations

from hashlib import sha256

from relics import EntityId

from bunnyland.foundation.history.mechanics import (
    HistoryLocation,
    history_record_for_event,
    record_world_history,
    world_history_records,
)

from ..core.components import RoomComponent
from ..core.ecs import container_of, entity_name, parse_entity_id
from ..core.world_actor import WorldActor
from .service import ImageGenJob, ImageGenService
from .spec import ImagePurpose
from .video_service import VideoGenJob, VideoGenService

RECENT_VIDEO_EVENT_LIMIT = 3


async def request_scene_image(
    actor: WorldActor,
    service: ImageGenService,
    *,
    character_id: str | EntityId,
    requested_by: str = "",
) -> ImageGenJob | None:
    """Record the character's current room as an event and request its image.

    Returns the queued (or reused) job, or ``None`` when the character is unknown or not in a
    room — there is nothing to illustrate.
    """
    parsed = character_id if isinstance(character_id, EntityId) else parse_entity_id(character_id)
    async with actor._lock:
        if parsed is None or not actor.world.has_entity(parsed):
            return None
        character = actor.world.get_entity(parsed)
        room_id = container_of(character)
        if room_id is None or not actor.world.has_entity(room_id):
            return None
        room = actor.world.get_entity(room_id)
        if not room.has_component(RoomComponent):
            return None
        summary = f"{entity_name(character)} in {room.get_component(RoomComponent).title}"
        source_event_id = f"scene:{parsed}:{actor.epoch}"
        record = record_world_history(
            actor.world,
            summary=summary,
            source_event_id=source_event_id,
            event_type="scene",
            created_at_epoch=actor.epoch,
            location_id=str(room_id),
        )
        if record is None:  # this moment already has a record -> reuse it
            record = history_record_for_event(actor.world, source_event_id)
        record_id = str(record.id)
    return await service.start(
        record_id,
        ImagePurpose.EVENT,
        requested_by=requested_by,
        target_id=str(parsed),
    )


async def request_scene_video(
    actor: WorldActor,
    service: VideoGenService,
    *,
    character_id: str | EntityId,
    requested_by: str = "",
) -> VideoGenJob | None:
    """Request a short clip of the latest events in the character's current room."""

    parsed = character_id if isinstance(character_id, EntityId) else parse_entity_id(character_id)
    async with actor._lock:
        if parsed is None or not actor.world.has_entity(parsed):
            return None
        character = actor.world.get_entity(parsed)
        room_id = container_of(character)
        if room_id is None or not actor.world.has_entity(room_id):
            return None
        room = actor.world.get_entity(room_id)
        if not room.has_component(RoomComponent):
            return None
        recent = [
            (entity, record)
            for entity, record in world_history_records(actor.world)
            if record.event_type != "event-video"
            and any(
                target_id == room_id
                for _edge, target_id in entity.get_relationships(HistoryLocation)
            )
        ][:RECENT_VIDEO_EVENT_LIMIT]
        if len(recent) == 1:
            record_id = str(recent[0][0].id)
        else:
            summaries = [record.summary for _entity, record in reversed(recent)]
            if not summaries:
                summaries = [
                    f"{entity_name(character)} in {room.get_component(RoomComponent).title}"
                ]
            source_ids = [record.source_event_id for _entity, record in recent]
            digest_source = "\n".join(source_ids) or f"scene:{parsed}:{actor.epoch}"
            digest = sha256(digest_source.encode()).hexdigest()[:16]
            source_event_id = f"event-video:{parsed}:{digest}"
            record = record_world_history(
                actor.world,
                summary=" Then, ".join(summaries),
                source_event_id=source_event_id,
                event_type="event-video",
                created_at_epoch=actor.epoch,
                location_id=str(room_id),
            )
            if record is None:
                record = history_record_for_event(actor.world, source_event_id)
            record_id = str(record.id)
    return await service.start(
        record_id,
        requested_by=requested_by,
        target_id=str(parsed),
    )


__all__ = ["RECENT_VIDEO_EVENT_LIMIT", "request_scene_image", "request_scene_video"]
