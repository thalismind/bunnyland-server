"""Presentation-only narration over visible state and recent domain events.

Narration is a projection: it reads domain events plus current ECS projections and writes
only to its own volatile transcript. It does not mutate the Relics world.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field

from relics import Entity, World

from ..core.components import CharacterComponent, IdentityComponent, RoomComponent
from ..core.ecs import container_of, parse_entity_id
from ..core.events import (
    ActorMovedEvent,
    CharacterDiedEvent,
    CharacterDownedEvent,
    DomainEvent,
    EntityInspectedEvent,
    EventVisibility,
    ItemDroppedEvent,
    ItemPutEvent,
    ItemTakenEvent,
    RoomLookedEvent,
    SpeechSaidEvent,
    SpeechToldEvent,
)
from ..core.world_actor import WorldActor
from ..projections import RoomSummaryProjection, perceive


@dataclass(frozen=True)
class SceneEvent:
    """One visible event phrase retained for audit and rendering."""

    event_id: str
    event_type: str
    summary: str
    salience: int
    room_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneInput:
    """Programmatic, viewer-scoped facts consumed by narration renderers."""

    viewer_id: str
    room_id: str | None
    location_title: str
    room_summary: str
    visible_characters: tuple[str, ...] = ()
    visible_objects: tuple[str, ...] = ()
    exits: tuple[str, ...] = ()
    events: tuple[SceneEvent, ...] = ()
    omitted_event_ids: tuple[str, ...] = ()
    invisible_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneNarration:
    """Rendered presentation message for one viewer."""

    viewer_id: str
    epoch: int
    scene: SceneInput
    text: str
    source_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class NarrationIssue:
    """Grounding issue reported by the deterministic narration harness."""

    kind: str
    detail: str


def _name(world: World, raw_id: str | None) -> str:
    entity_id = parse_entity_id(raw_id) if raw_id else None
    if entity_id is not None and world.has_entity(entity_id):
        entity = world.get_entity(entity_id)
        if entity.has_component(IdentityComponent):
            return entity.get_component(IdentityComponent).name
    return "someone"


def _room_title(world: World, raw_id: str | None) -> str:
    entity_id = parse_entity_id(raw_id) if raw_id else None
    if entity_id is not None and world.has_entity(entity_id):
        entity = world.get_entity(entity_id)
        if entity.has_component(RoomComponent):
            return entity.get_component(RoomComponent).title
    return "somewhere"


def _event_rooms(world: World, event: DomainEvent) -> tuple[str, ...]:
    rooms: list[str] = []
    if isinstance(event, ActorMovedEvent):
        rooms.extend([event.from_room_id, event.to_room_id])
    elif event.room_id:
        rooms.append(event.room_id)
    elif event.actor_id:
        actor_id = parse_entity_id(event.actor_id)
        if actor_id is not None and world.has_entity(actor_id):
            room_id = container_of(world.get_entity(actor_id))
            if room_id is not None:
                rooms.append(str(room_id))
    return tuple(dict.fromkeys(room for room in rooms if room))


def _event_salience(event: DomainEvent) -> int:
    if isinstance(event, (CharacterDiedEvent, CharacterDownedEvent)):
        return 100
    if isinstance(event, (SpeechSaidEvent, SpeechToldEvent)):
        return 80
    if isinstance(event, ActorMovedEvent):
        return 70
    if isinstance(event, (ItemTakenEvent, ItemDroppedEvent, ItemPutEvent)):
        return 60
    if isinstance(event, (RoomLookedEvent, EntityInspectedEvent)):
        return 30
    return 0


def _event_visible_to(world: World, viewer: Entity, event: DomainEvent) -> bool:
    viewer_id = str(viewer.id)
    viewer_room_id = container_of(viewer)
    viewer_room = str(viewer_room_id) if viewer_room_id is not None else None
    if event.visibility is EventVisibility.PRIVATE:
        return event.actor_id == viewer_id or viewer_id in event.target_ids
    if event.visibility is EventVisibility.DIRECTED:
        return (
            event.actor_id == viewer_id
            or viewer_id in event.target_ids
            or (
                isinstance(event, SpeechToldEvent)
                and viewer_id in event.overhearer_ids
            )
        )
    rooms = _event_rooms(world, event)
    if rooms and viewer_room in rooms:
        return True
    if event.actor_id == viewer_id or viewer_id in event.target_ids:
        return True
    return event.visibility is EventVisibility.PUBLIC


def _event_summary(world: World, viewer: Entity, event: DomainEvent) -> str:
    viewer_id = str(viewer.id)
    actor = "You" if event.actor_id == viewer_id else _name(world, event.actor_id)
    if isinstance(event, ActorMovedEvent):
        if event.actor_id == viewer_id:
            direction = f" {event.direction}" if event.direction else ""
            return f"You moved{direction} to {_room_title(world, event.to_room_id)}."
        viewer_room = container_of(viewer)
        if viewer_room is not None and str(viewer_room) == event.from_room_id:
            direction = f" {event.direction}" if event.direction else ""
            return f"{actor} left{direction}."
        return f"{actor} arrived."
    if isinstance(event, SpeechSaidEvent):
        return f'{actor} said, "{event.text}"'
    if isinstance(event, SpeechToldEvent):
        target = _name(world, event.target_ids[0]) if event.target_ids else "someone"
        if event.actor_id == viewer_id:
            return f'You told {target}, "{event.text}"'
        if viewer_id in event.target_ids:
            return f'{actor} told you, "{event.text}"'
        return f'{actor} told {target}, "{event.text}"'
    if isinstance(event, ItemTakenEvent):
        return f"{actor} picked up {_name(world, event.item_id)}."
    if isinstance(event, ItemDroppedEvent):
        return f"{actor} dropped {_name(world, event.item_id)}."
    if isinstance(event, ItemPutEvent):
        return f"{actor} put {_name(world, event.item_id)} away."
    if isinstance(event, CharacterDownedEvent):
        return f"{actor} collapsed."
    if isinstance(event, CharacterDiedEvent):
        return f"{actor} died."
    if isinstance(event, RoomLookedEvent):
        return f"{actor} looked around."
    if isinstance(event, EntityInspectedEvent):
        return f"{actor} inspected {event.name}."
    return ""


def _visible_entity_names(scene: SceneInput) -> set[str]:
    return {
        scene.location_title,
        *scene.visible_characters,
        *scene.visible_objects,
        *(exit_.split(" ", 1)[0] for exit_ in scene.exits),
    }


def check_grounding(scene: SceneInput, text: str) -> tuple[NarrationIssue, ...]:
    """Flag obvious deterministic grounding failures in rendered narration."""

    issues: list[NarrationIssue] = []
    lowered = text.lower()
    for hidden in scene.invisible_names:
        if hidden and hidden.lower() in lowered:
            issues.append(
                NarrationIssue(
                    kind="hidden-state-leak",
                    detail=f"narration mentioned hidden or remote entity {hidden!r}",
                )
            )
    if scene.events:
        event_text = " ".join(event.summary for event in scene.events)
        visible = _visible_entity_names(scene)
        if not any(name and name in text for name in visible) and event_text not in text:
            issues.append(
                NarrationIssue(
                    kind="ungrounded",
                    detail="narration did not mention visible scene facts or event summaries",
                )
            )
    return tuple(issues)


def render_scene(scene: SceneInput) -> str:
    """Render deterministic fallback narration from scene facts."""

    lines: list[str] = []
    title = scene.location_title or "Somewhere"
    if scene.events:
        lines.append(f"{title}: " + " ".join(event.summary for event in scene.events))
    else:
        lines.append(f"{title}: {scene.room_summary or 'Nothing notable changes.'}")
    visible = scene.visible_characters + scene.visible_objects
    if visible:
        lines.append("Visible now: " + ", ".join(visible) + ".")
    if scene.exits:
        lines.append("Exits: " + ", ".join(scene.exits) + ".")
    return "\n".join(lines)


@dataclass
class NarrationProjection:
    """Collects tick events and emits per-viewer presentation messages."""

    world: World
    room_summary: RoomSummaryProjection | None = None
    capacity: int = 20
    renderer: Callable[[SceneInput], str] = render_scene
    _pending: list[DomainEvent] = field(default_factory=list, init=False)
    _transcript: dict[str, deque[SceneNarration]] = field(
        default_factory=lambda: defaultdict(deque), init=False
    )
    errors: list[str] = field(default_factory=list, init=False)

    def attach(self, actor: WorldActor) -> NarrationProjection:
        self.world = actor.world
        self.room_summary = (self.room_summary or RoomSummaryProjection(self.world)).attach()
        actor.bus.subscribe(DomainEvent, self._on_event)
        actor.register_after_tick(self.after_tick)
        return self

    def latest(self, viewer_id: str) -> SceneNarration | None:
        entries = self._transcript.get(viewer_id)
        return entries[-1] if entries else None

    def narrations(self, viewer_id: str) -> tuple[SceneNarration, ...]:
        return tuple(self._transcript.get(viewer_id, ()))

    def assemble(self, viewer: Entity, events: tuple[DomainEvent, ...]) -> SceneInput:
        room_id = container_of(viewer)
        location_title = "nowhere"
        room_summary = ""
        exits: tuple[str, ...] = ()
        if room_id is not None:
            projection = self.room_summary or RoomSummaryProjection(self.world).attach()
            facts = projection.facts(room_id)
            location_title = facts.title
            room_summary = projection.summary(room_id, 0).visible_summary
            exits = tuple(exit_.direction for exit_ in facts.exits)

        perception = perceive(self.world, viewer)
        visible_characters = tuple(
            entity.name for entity in perception.entities if entity.is_character
        )
        visible_objects = tuple(
            entity.name for entity in perception.entities if not entity.is_character
        )
        visible_events: list[SceneEvent] = []
        omitted: list[str] = []
        for event in events:
            if not _event_visible_to(self.world, viewer, event):
                omitted.append(event.event_id)
                continue
            summary = _event_summary(self.world, viewer, event)
            if not summary:
                omitted.append(event.event_id)
                continue
            visible_events.append(
                SceneEvent(
                    event_id=event.event_id,
                    event_type=event.__class__.__name__,
                    summary=summary,
                    salience=_event_salience(event),
                    room_ids=_event_rooms(self.world, event),
                )
            )
        visible_events.sort(key=lambda event: (-event.salience, event.event_id))
        return SceneInput(
            viewer_id=str(viewer.id),
            room_id=str(room_id) if room_id is not None else None,
            location_title=location_title,
            room_summary=room_summary,
            visible_characters=visible_characters,
            visible_objects=visible_objects,
            exits=exits,
            events=tuple(visible_events),
            omitted_event_ids=tuple(omitted),
            invisible_names=self._invisible_names(viewer),
        )

    def after_tick(self, actor: WorldActor) -> None:
        del actor
        if not self._pending:
            return
        events = tuple(self._pending)
        self._pending.clear()
        try:
            for viewer in self.world.query().with_all([CharacterComponent]).execute_entities():
                scene = self.assemble(viewer, events)
                if not scene.events:
                    continue
                text = self.renderer(scene)
                narration = SceneNarration(
                    viewer_id=str(viewer.id),
                    epoch=max(event.world_epoch for event in events),
                    scene=scene,
                    text=text,
                    source_event_ids=tuple(event.event_id for event in scene.events),
                )
                entries = self._transcript[str(viewer.id)]
                entries.append(narration)
                while len(entries) > self.capacity:
                    entries.popleft()
        except Exception as exc:  # pragma: no cover - exact exception is stored for operators.
            self.errors.append(str(exc))

    def _on_event(self, event: DomainEvent) -> None:
        self._pending.append(event)

    def _invisible_names(self, viewer: Entity) -> tuple[str, ...]:
        visible = set(perceived.id for perceived in perceive(self.world, viewer).entities)
        names: list[str] = []
        for entity in self.world.query().with_all([IdentityComponent]).execute_entities():
            if entity.id == viewer.id or str(entity.id) in visible:
                continue
            name = entity.get_component(IdentityComponent).name
            if name:
                names.append(name)
        return tuple(sorted(names))


__all__ = [
    "NarrationIssue",
    "NarrationProjection",
    "SceneEvent",
    "SceneInput",
    "SceneNarration",
    "check_grounding",
    "render_scene",
]
