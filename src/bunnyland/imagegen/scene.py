"""Request an image of a character's current scene (spec 27).

Shared by every client that offers the camera affordance (Discord, TUI, REPL, the web
endpoint): it records the character's current room as a ``scene`` world-history event and
asks the service to illustrate it. Recording the moment durably means the image persists with
that event and repeated requests in the same tick reuse it.
"""

from __future__ import annotations

from relics import Entity, EntityId

from bunnyland.foundation.history.mechanics import (
    history_record_for_event,
    record_world_history,
)

from ..core.components import RoomComponent
from ..core.ecs import container_of, entity_name, parse_entity_id
from ..core.world_actor import WorldActor
from .components import MediaSceneSnapshotComponent
from .scene_projection import MediaSceneProjection
from .service import ImageGenJob, ImageGenService
from .spec import ImagePurpose
from .video_service import VideoGenJob, VideoGenService


def _scene_record(
    actor: WorldActor,
    *,
    service: ImageGenService | VideoGenService,
    character: Entity,
    room: Entity,
    event_id: str,
) -> Entity:
    """Resolve the foreground event and persist its immutable public media snapshot."""

    configured_projection = getattr(service, "scene_projection", None)
    projection = (
        configured_projection
        if isinstance(configured_projection, MediaSceneProjection)
        else MediaSceneProjection(actor)
    )
    primary = projection.select_event(room.id, event_id)
    snapshot = projection.capture(viewer=character, room=room, primary=primary)
    source_event_id = (
        primary.event.event_id
        if primary is not None
        else f"scene:{character.id}:{actor.epoch}"
    )
    primary_snapshot = next(
        (event for event in snapshot.events if event.id == snapshot.primary_event_id),
        None,
    )
    summary = (
        primary_snapshot.summary
        if primary_snapshot is not None
        else f"{entity_name(character)} in {room.get_component(RoomComponent).title}"
    )
    record = record_world_history(
        actor.world,
        summary=summary,
        source_event_id=source_event_id,
        event_type=(type(primary.event).__name__ if primary is not None else "scene"),
        created_at_epoch=(primary.event.world_epoch if primary is not None else actor.epoch),
        location_id=str(room.id),
        actor_ids=(
            (primary.event.actor_id,)
            if primary is not None and primary.event.actor_id
            else ()
        ),
        target_ids=primary.event.target_ids if primary is not None else (),
    )
    if record is None:
        record = history_record_for_event(actor.world, source_event_id)
    if record is None:
        raise RuntimeError("media history record could not be resolved")
    if not record.has_component(MediaSceneSnapshotComponent):
        record.add_component(MediaSceneSnapshotComponent(snapshot=snapshot))
    return record


async def request_scene_image(
    actor: WorldActor,
    service: ImageGenService,
    *,
    character_id: str | EntityId,
    requested_by: str = "",
    event_id: str = "",
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
        record = _scene_record(
            actor,
            service=service,
            character=character,
            room=room,
            event_id=event_id,
        )
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
    event_id: str = "",
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
        record = _scene_record(
            actor,
            service=service,
            character=character,
            room=room,
            event_id=event_id,
        )
        record_id = str(record.id)
    return await service.start(
        record_id,
        requested_by=requested_by,
        target_id=str(parsed),
    )


__all__ = ["request_scene_image", "request_scene_video"]
