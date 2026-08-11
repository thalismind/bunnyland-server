"""Event-focused public scene projection for durable media generation."""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from dataclasses import dataclass
from typing import Final

from pydantic import JsonValue, TypeAdapter
from relics import Edge, Entity, EntityId

from ..core.components import (
    CharacterComponent,
    DeadComponent,
    DescriptionComponent,
    DoorComponent,
    DownedComponent,
    GenerationIntentComponent,
    IdentityComponent,
    LightComponent,
    LockableComponent,
    RestingComponent,
    RoomComponent,
    SleepingComponent,
    StealthComponent,
    SuspendedComponent,
    TemperatureComponent,
)
from ..core.ecs import container_of, entity_name, parse_entity_id
from ..core.edges import Contains, Holding, Wearing
from ..core.events import ActorMovedEvent, DomainEvent, EventVisibility
from ..core.world_actor import WorldActor
from ..foundation.environment.mechanics import TimeOfDayComponent, WeatherComponent
from ..projections.room_summary import light_band, temperature_band
from ..simpacks.toonsim.mechanics import SpriteLayerComponent, SpritePositionComponent
from .scene_models import (
    MediaEntitySnapshot,
    MediaEventSnapshot,
    MediaFact,
    MediaFactProvider,
    MediaFactRequest,
    MediaPosition,
    MediaRoomSnapshot,
    MediaSceneSnapshot,
)

LOG = logging.getLogger("bunnyland.imagegen.scene")
EVENT_LIMIT: Final = 200
SCENE_EVENT_LIMIT: Final = 8
SCENE_ENTITY_LIMIT: Final = 64
_EVENT_JSON = TypeAdapter(dict[str, JsonValue])
_CAMEL_WORD = re.compile(r"(?<!^)(?=[A-Z])")
_BASE_EVENT_FIELDS = frozenset(
    {
        "event_id",
        "world_epoch",
        "created_at",
        "visibility",
        "actor_id",
        "room_id",
        "target_ids",
        "causation_id",
        "correlation_id",
    }
)
_NON_VISUAL_FIELDS = frozenset(
    {
        "author_intent",
        "inferred_intent",
        "final_interpretation",
        "approach",
        "command_id",
        "command_type",
    }
)


@dataclass(frozen=True)
class MediaEventEnvelope:
    """One occurrence-time event and the rooms it affected."""

    event: DomainEvent
    room_ids: tuple[str, ...]


def _is_hidden(entity: Entity) -> bool:
    if not entity.has_component(StealthComponent):
        return False
    stealth = entity.get_component(StealthComponent)
    return stealth.hiding and stealth.visibility_level <= stealth.hidden_threshold


def _description(entity: Entity) -> tuple[str, str]:
    if not entity.has_component(DescriptionComponent):
        return "", ""
    value = entity.get_component(DescriptionComponent)
    return value.long or value.short, value.appearance


def _identity(entity: Entity) -> tuple[str, tuple[str, ...]]:
    if not entity.has_component(IdentityComponent):
        return "", ()
    value = entity.get_component(IdentityComponent)
    return value.kind, value.tags


def _states(entity: Entity) -> tuple[str, ...]:
    states: list[str] = []
    for component, label in (
        (DeadComponent, "dead"),
        (DownedComponent, "collapsed"),
        (SleepingComponent, "sleeping"),
        (RestingComponent, "resting"),
        (SuspendedComponent, "inactive"),
    ):
        if entity.has_component(component):
            states.append(label)
    if entity.has_component(DoorComponent):
        states.append("open" if entity.get_component(DoorComponent).open else "closed")
    if entity.has_component(LockableComponent) and entity.get_component(
        LockableComponent
    ).locked:
        states.append("locked")
    return tuple(states)


def _role_key(entity: MediaEntitySnapshot) -> tuple[int, str]:
    priorities = {"primary_actor": 0, "primary_target": 1, "participant": 2}
    return priorities.get(entity.role, 3), entity.name


class MediaSceneProjection:
    """Captures public room state and public/room events for media prompts."""

    def __init__(
        self,
        actor: WorldActor,
        *,
        fact_providers: tuple[MediaFactProvider, ...] = (),
        event_limit: int = EVENT_LIMIT,
    ) -> None:
        self.actor = actor
        self.fact_providers = fact_providers
        self._events: deque[MediaEventEnvelope] = deque(maxlen=event_limit)
        actor.bus.subscribe(DomainEvent, self._record)

    def _record(self, event: DomainEvent) -> None:
        if event.visibility not in {EventVisibility.PUBLIC, EventVisibility.ROOM}:
            return
        if type(event).__name__.startswith(("ImageGeneration", "VideoGeneration")):
            return
        self._events.append(MediaEventEnvelope(event=event, room_ids=self._event_rooms(event)))

    def _event_rooms(self, event: DomainEvent) -> tuple[str, ...]:
        rooms: list[str] = []
        if isinstance(event, ActorMovedEvent):
            rooms.extend((event.from_room_id, event.to_room_id))
        elif event.room_id:
            rooms.append(event.room_id)
        event_data = _EVENT_JSON.validate_python(event.model_dump(mode="json"))
        for field in ("from_room_id", "to_room_id"):
            value = event_data.get(field)
            if isinstance(value, str) and value:
                rooms.append(value)
        for raw_id in (event.actor_id, *event.target_ids):
            entity_id = parse_entity_id(raw_id) if raw_id else None
            if entity_id is None or not self.actor.world.has_entity(entity_id):
                continue
            room_id = container_of(self.actor.world.get_entity(entity_id))
            if room_id is not None:
                rooms.append(str(room_id))
        return tuple(dict.fromkeys(rooms))

    def select_event(self, room_id: EntityId, event_id: str = "") -> MediaEventEnvelope | None:
        """Resolve an exact eligible event or the latest event in ``room_id``."""

        room = str(room_id)
        if event_id:
            envelope = next(
                (entry for entry in reversed(self._events) if entry.event.event_id == event_id),
                None,
            )
            if envelope is None:
                raise ValueError("media event is unknown or expired")
            if room not in envelope.room_ids:
                raise ValueError("media event is not visible in the character's room")
            return envelope
        return next(
            (entry for entry in reversed(self._events) if room in entry.room_ids),
            None,
        )

    def capture(
        self,
        *,
        viewer: Entity,
        room: Entity,
        primary: MediaEventEnvelope | None,
    ) -> MediaSceneSnapshot:
        """Capture a stable, public scene around ``primary`` in ``room``."""

        primary_id = primary.event.event_id if primary is not None else ""
        relevant = self._relevant_events(str(room.id), primary)
        participant_ids = {
            raw_id
            for event in relevant
            for raw_id in (event.event.actor_id, *event.event.target_ids)
            if raw_id
        }
        characters: list[MediaEntitySnapshot] = []
        objects: list[MediaEntitySnapshot] = []
        for edge, child_id in room.get_relationships(Contains):
            if not edge.visible or not self.actor.world.has_entity(child_id):
                continue
            child = self.actor.world.get_entity(child_id)
            if _is_hidden(child):
                continue
            role = "participant" if str(child_id) in participant_ids else "background"
            if primary is not None and primary.event.actor_id == str(child_id):
                role = "primary_actor"
            elif primary is not None and str(child_id) in primary.event.target_ids:
                role = "primary_target"
            snapshot = self._entity_snapshot(
                child,
                role=role,
                viewer_id=str(viewer.id),
                primary_event_id=primary_id,
            )
            if child.has_component(CharacterComponent):
                characters.append(snapshot)
            else:
                objects.append(snapshot)
        room_component = room.get_component(RoomComponent)
        description, appearance = _description(room)
        region = ""
        parent_id = container_of(room)
        if parent_id is not None and self.actor.world.has_entity(parent_id):
            region = entity_name(self.actor.world.get_entity(parent_id), fallback="")
        clock = next(
            iter(
                self.actor.world.query()
                .with_all([TimeOfDayComponent])
                .execute_entities()
            ),
            None,
        )
        time_of_day = (
            clock.get_component(TimeOfDayComponent).phase if clock is not None else ""
        )
        weather = (
            clock.get_component(WeatherComponent).condition
            if clock is not None and clock.has_component(WeatherComponent)
            else ""
        )
        room_snapshot = MediaRoomSnapshot(
            id=str(room.id),
            title=room_component.title,
            description=description,
            appearance=appearance,
            biome=room_component.biome,
            region=region,
            indoor=room_component.indoor,
            light=(
                light_band(room.get_component(LightComponent).level)
                if room.has_component(LightComponent)
                else ""
            ),
            temperature=(
                temperature_band(room.get_component(TemperatureComponent).celsius)
                if room.has_component(TemperatureComponent)
                else ""
            ),
            time_of_day=time_of_day,
            weather=weather,
            facts=self._provider_facts(
                room,
                role="room",
                viewer_id=str(viewer.id),
                primary_event_id=primary_id,
            ),
        )
        return MediaSceneSnapshot(
            captured_at_epoch=self.actor.epoch,
            viewer_id=str(viewer.id),
            primary_event_id=primary_id,
            world_title=self.actor.world_info.title,
            world_description=self.actor.world_info.description,
            room=room_snapshot,
            characters=tuple(sorted(characters, key=_role_key)[:SCENE_ENTITY_LIMIT]),
            objects=tuple(sorted(objects, key=_role_key)[:SCENE_ENTITY_LIMIT]),
            events=tuple(self._event_snapshot(entry) for entry in relevant),
        )

    def _relevant_events(
        self, room_id: str, primary: MediaEventEnvelope | None
    ) -> tuple[MediaEventEnvelope, ...]:
        matching = [entry for entry in self._events if room_id in entry.room_ids]
        if primary is None:
            return tuple(matching[-SCENE_EVENT_LIMIT:])
        primary_index = next(
            index
            for index, entry in enumerate(matching)
            if entry.event.event_id == primary.event.event_id
        )
        start = max(0, primary_index - SCENE_EVENT_LIMIT + 1)
        return tuple(matching[start : primary_index + 1])

    def _entity_snapshot(
        self,
        entity: Entity,
        *,
        role: str,
        viewer_id: str,
        primary_event_id: str,
    ) -> MediaEntitySnapshot:
        description, appearance = _description(entity)
        kind, identity_tags = _identity(entity)
        intent = (
            entity.get_component(GenerationIntentComponent)
            if entity.has_component(GenerationIntentComponent)
            else None
        )
        tags = tuple(
            dict.fromkeys((*identity_tags, *(intent.tags if intent is not None else ())))
        )
        if intent is not None and intent.description:
            description = " ".join(part for part in (description, intent.description) if part)
        character = (
            entity.get_component(CharacterComponent)
            if entity.has_component(CharacterComponent)
            else None
        )
        held = self._related_names(entity, Holding)
        worn = self._related_names(entity, Wearing)
        position = None
        if entity.has_component(SpritePositionComponent):
            sprite_position = entity.get_component(SpritePositionComponent)
            position = MediaPosition(
                x=sprite_position.x,
                y=sprite_position.y,
                layer=(
                    entity.get_component(SpriteLayerComponent).layer
                    if entity.has_component(SpriteLayerComponent)
                    else 0
                ),
            )
        return MediaEntitySnapshot(
            id=str(entity.id),
            name=entity_name(entity),
            kind=kind,
            role=role,
            description=description,
            appearance=appearance,
            species=character.species if character is not None else "",
            biography=character.biography if character is not None else "",
            tags=tags,
            states=_states(entity),
            held=held,
            worn=worn,
            position=position,
            facts=self._provider_facts(
                entity,
                role=role,
                viewer_id=viewer_id,
                primary_event_id=primary_event_id,
            ),
        )

    def _related_names(self, entity: Entity, edge_type: type[Edge]) -> tuple[str, ...]:
        names = [
            entity_name(self.actor.world.get_entity(target_id))
            for _edge, target_id in entity.get_relationships(edge_type)
            if self.actor.world.has_entity(target_id)
        ]
        return tuple(sorted(names))

    def _provider_facts(
        self,
        entity: Entity,
        *,
        role: str,
        viewer_id: str,
        primary_event_id: str,
    ) -> tuple[MediaFact, ...]:
        request = MediaFactRequest(
            role=role,
            viewer_id=viewer_id,
            primary_event_id=primary_event_id,
        )
        facts: list[MediaFact] = []
        for provider in self.fact_providers:
            try:
                facts.extend(provider.facts_for(self.actor.world, entity, request))
            except Exception:  # noqa: BLE001 - one plugin must not erase the core snapshot.
                LOG.warning("media fact provider failed for entity %s", entity.id, exc_info=True)
        return tuple(sorted(facts, key=lambda fact: fact.id))

    def _event_snapshot(self, envelope: MediaEventEnvelope) -> MediaEventSnapshot:
        event = envelope.event
        data = _EVENT_JSON.validate_python(event.model_dump(mode="json"))
        details = tuple(
            f"{key}: {self._render_json(value)}"
            for key, value in sorted(data.items())
            if key not in _BASE_EVENT_FIELDS
            and key not in _NON_VISUAL_FIELDS
            and value not in (None, "", [], {})
        )
        actor_name = self._entity_name(event.actor_id)
        target_names = tuple(self._entity_name(raw_id) for raw_id in event.target_ids)
        title = _CAMEL_WORD.sub(" ", type(event).__name__).removesuffix(" Event")
        participants = ""
        if actor_name:
            participants = f" by {actor_name}"
        if target_names:
            participants += f" involving {', '.join(target_names)}"
        detail_text = f": {details[0]}" if details else ""
        return MediaEventSnapshot(
            id=event.event_id,
            event_type=type(event).__name__,
            summary=f"{title}{participants}{detail_text}",
            epoch=event.world_epoch,
            actor_id=event.actor_id or "",
            target_ids=event.target_ids,
            causation_id=event.causation_id or "",
            correlation_id=event.correlation_id or "",
            details=details,
        )

    def _entity_name(self, raw_id: str | None) -> str:
        entity_id = parse_entity_id(raw_id) if raw_id else None
        if entity_id is None or not self.actor.world.has_entity(entity_id):
            return raw_id or ""
        return entity_name(self.actor.world.get_entity(entity_id))

    @staticmethod
    def _render_json(value: JsonValue) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, sort_keys=True, separators=(",", ":"))


__all__ = [
    "EVENT_LIMIT",
    "SCENE_EVENT_LIMIT",
    "SCENE_ENTITY_LIMIT",
    "MediaEventEnvelope",
    "MediaSceneProjection",
]
