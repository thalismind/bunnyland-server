"""Request an image of a character's current scene (spec 27).

Shared by every client that offers the camera affordance (Discord, TUI, REPL, the web
endpoint): it records the character's current room as a ``scene`` world-history event and
asks the service to illustrate it. Recording the moment durably means the image persists with
that event and repeated requests in the same tick reuse it.
"""

from __future__ import annotations

from relics import EntityId

from ..core.components import RoomComponent
from ..core.ecs import container_of, entity_name, parse_entity_id
from ..core.world_actor import WorldActor
from ..mechanics.history import history_record_for_event, record_world_history
from .service import ImageGenJob, ImageGenService
from .spec import ImagePurpose


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
    return await service.start(record_id, ImagePurpose.EVENT, requested_by=requested_by)


__all__ = ["request_scene_image"]
