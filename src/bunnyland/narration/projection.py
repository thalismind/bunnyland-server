"""Presentation-only narration over visible state and recent domain events.

Narration is a projection: it reads domain events plus current ECS projections and writes
only to its own volatile transcript. It does not mutate the Relics world.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
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

LOW_SALIENCE_CUTOFF = 30


@dataclass(frozen=True)
class NarrationVoice:
    """Scenario narration style metadata kept separate from scene facts."""

    name: str
    style_tags: tuple[str, ...] = ()
    lead_in: str = ""


DEFAULT_VOICE = NarrationVoice(name="plain")
DEFAULT_VOICES = (
    DEFAULT_VOICE,
    NarrationVoice(name="cozy", style_tags=("warm", "gentle"), lead_in="Gently,"),
    NarrationVoice(name="noir", style_tags=("terse", "shadowed"), lead_in="In clipped shadows,"),
)


class NarrationVoiceRegistry:
    """Resolve scenario voice names or tags to deterministic narration style metadata."""

    def __init__(self, voices: tuple[NarrationVoice, ...] = DEFAULT_VOICES) -> None:
        self._voices = {voice.name: voice for voice in voices}

    def get(self, name: str) -> NarrationVoice:
        return self._voices.get(name, DEFAULT_VOICE)

    def for_tags(self, tags: tuple[str, ...]) -> NarrationVoice:
        wanted = set(tags)
        for voice in self._voices.values():
            if wanted.intersection(voice.style_tags):
                return voice
        return DEFAULT_VOICE


DEFAULT_VOICE_REGISTRY = NarrationVoiceRegistry()


@dataclass(frozen=True)
class SceneEvent:
    """One visible event phrase retained for audit and rendering."""

    event_id: str
    event_type: str
    summary: str
    salience: int
    actor_id: str | None = None
    room_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneCluster:
    """A coherent group of visible events for one viewer."""

    cluster_id: str
    event_ids: tuple[str, ...]
    summaries: tuple[str, ...]
    salience: int
    actor_id: str | None = None
    room_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneFact:
    """One programmatic fact visible to a narration viewer."""

    category: str
    text: str
    entity_id: str | None = None
    event_id: str | None = None


@dataclass(frozen=True)
class SceneInput:
    """Programmatic, viewer-scoped facts consumed by narration renderers."""

    viewer_id: str
    room_id: str | None
    location_title: str
    room_summary: str
    voice: NarrationVoice = DEFAULT_VOICE
    visible_characters: tuple[str, ...] = ()
    visible_objects: tuple[str, ...] = ()
    exits: tuple[str, ...] = ()
    events: tuple[SceneEvent, ...] = ()
    clusters: tuple[SceneCluster, ...] = ()
    omitted_event_ids: tuple[str, ...] = ()
    compressed_event_ids: tuple[str, ...] = ()
    compression_notes: tuple[str, ...] = ()
    invisible_names: tuple[str, ...] = ()
    facts: tuple[SceneFact, ...] = ()


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
    lead_in = f"{scene.voice.lead_in} " if scene.voice.lead_in else ""
    if scene.clusters:
        cluster_text = " ".join(
            " ".join(cluster.summaries) for cluster in scene.clusters
        )
        lines.append(f"{title}: {lead_in}{cluster_text}")
    elif scene.events:
        lines.append(f"{title}: {lead_in}" + " ".join(event.summary for event in scene.events))
    else:
        lines.append(f"{title}: {lead_in}{scene.room_summary or 'Nothing notable changes.'}")
    visible = scene.visible_characters + scene.visible_objects
    if visible:
        lines.append("Visible now: " + ", ".join(visible) + ".")
    if scene.exits:
        lines.append("Exits: " + ", ".join(scene.exits) + ".")
    return "\n".join(lines)


def _render_perceived_room_summary(
    *,
    title: str,
    bands: dict[str, str],
    visible_characters: tuple[str, ...],
    visible_objects: tuple[str, ...],
    exits: tuple[str, ...],
) -> str:
    lines = [title]
    if bands:
        descriptors = ", ".join(bands[key] for key in sorted(bands))
        lines.append(f"It is {descriptors}.")
    if visible_characters:
        lines.append("Here: " + ", ".join(visible_characters) + ".")
    if visible_objects:
        lines.append("You see: " + ", ".join(visible_objects) + ".")
    if exits:
        lines.append("Exits: " + ", ".join(exits) + ".")
    return "\n".join(lines)


def _scene_facts(
    *,
    room_id: str | None,
    location_title: str,
    room_summary: str,
    visible_characters: tuple[tuple[str, str], ...],
    visible_objects: tuple[tuple[str, str], ...],
    exits: tuple[str, ...],
    events: tuple[SceneEvent, ...],
    compression_notes: tuple[str, ...],
) -> tuple[SceneFact, ...]:
    facts: list[SceneFact] = [
        SceneFact(
            category="location",
            text=f"Location: {location_title}.",
            entity_id=room_id,
        )
    ]
    if room_summary:
        facts.append(
            SceneFact(
                category="room-summary",
                text=room_summary,
                entity_id=room_id,
            )
        )
    for entity_id, name in visible_characters:
        facts.append(
            SceneFact(
                category="visible-character",
                text=f"Visible character: {name}.",
                entity_id=entity_id,
            )
        )
    for entity_id, name in visible_objects:
        facts.append(
            SceneFact(
                category="visible-object",
                text=f"Visible object: {name}.",
                entity_id=entity_id,
            )
        )
    for direction in exits:
        facts.append(SceneFact(category="exit", text=f"Exit: {direction}.", entity_id=room_id))
    for event in events:
        facts.append(
            SceneFact(
                category="event",
                text=event.summary,
                event_id=event.event_id,
            )
        )
    for note in compression_notes:
        facts.append(SceneFact(category="compression", text=note))
    return tuple(facts)


def _compress_visible_events(
    events: tuple[SceneEvent, ...], *, max_events: int
) -> tuple[tuple[SceneEvent, ...], tuple[str, ...], tuple[str, ...]]:
    if max_events <= 0 or len(events) <= max_events:
        return events, (), ()

    high_salience = tuple(event for event in events if event.salience > LOW_SALIENCE_CUTOFF)
    routine = tuple(event for event in events if event.salience <= LOW_SALIENCE_CUTOFF)
    routine_budget = max(0, max_events - len(high_salience))
    kept_routine = routine[:routine_budget]
    compressed = routine[routine_budget:]
    if not compressed:
        return events, (), ()

    kept = tuple(
        sorted(
            (*high_salience, *kept_routine),
            key=lambda event: (-event.salience, event.event_id),
        )
    )
    compressed_ids = tuple(event.event_id for event in compressed)
    count = len(compressed_ids)
    noun = "event" if count == 1 else "events"
    return kept, compressed_ids, (f"{count} routine {noun} compressed.",)


def _scene_clusters(events: tuple[SceneEvent, ...]) -> tuple[SceneCluster, ...]:
    grouped: dict[tuple[str | None, tuple[str, ...]], list[SceneEvent]] = {}
    for event in events:
        key = (event.actor_id, event.room_ids)
        grouped.setdefault(key, []).append(event)

    clusters: list[SceneCluster] = []
    for (actor_id, room_ids), grouped_events in grouped.items():
        event_ids = tuple(event.event_id for event in grouped_events)
        clusters.append(
            SceneCluster(
                cluster_id=f"cluster-{event_ids[0]}",
                event_ids=event_ids,
                summaries=tuple(event.summary for event in grouped_events),
                salience=max(event.salience for event in grouped_events),
                actor_id=actor_id,
                room_ids=room_ids,
            )
        )
    return tuple(sorted(clusters, key=lambda cluster: (-cluster.salience, cluster.cluster_id)))


@dataclass
class NarrationProjection:
    """Collects tick events and emits per-viewer presentation messages."""

    world: World
    room_summary: RoomSummaryProjection | None = None
    capacity: int = 20
    max_scene_events: int = 8
    voice: NarrationVoice = DEFAULT_VOICE
    renderer: Callable[[SceneInput], str | Awaitable[str]] = render_scene
    fallback_renderer: Callable[[SceneInput], str] = render_scene
    non_blocking: bool = False
    render_timeout_seconds: float = 0.25
    _pending: list[DomainEvent] = field(default_factory=list, init=False)
    _transcript: dict[str, deque[SceneNarration]] = field(
        default_factory=lambda: defaultdict(deque), init=False
    )
    _delivery_tasks: set[asyncio.Task[None]] = field(default_factory=set, init=False)
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

    def pending_deliveries(self) -> int:
        return sum(1 for task in self._delivery_tasks if not task.done())

    def assemble(self, viewer: Entity, events: tuple[DomainEvent, ...]) -> SceneInput:
        room_id = container_of(viewer)
        location_title = "nowhere"
        room_summary = ""
        exits: tuple[str, ...] = ()
        bands: dict[str, str] = {}
        if room_id is not None:
            projection = self.room_summary or RoomSummaryProjection(self.world).attach()
            facts = projection.facts(room_id)
            location_title = facts.title
            bands = dict(facts.bands)
            exits = tuple(exit_.direction for exit_ in facts.exits)

        perception = perceive(self.world, viewer)
        visible_character_facts = tuple(
            (entity.id, entity.name) for entity in perception.entities if entity.is_character
        )
        visible_object_facts = tuple(
            (entity.id, entity.name) for entity in perception.entities if not entity.is_character
        )
        visible_characters = tuple(name for _entity_id, name in visible_character_facts)
        visible_objects = tuple(name for _entity_id, name in visible_object_facts)
        if room_id is not None:
            room_summary = _render_perceived_room_summary(
                title=location_title,
                bands=bands,
                visible_characters=visible_characters,
                visible_objects=visible_objects,
                exits=exits,
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
                    actor_id=event.actor_id,
                    room_ids=_event_rooms(self.world, event),
                )
            )
        visible_events.sort(key=lambda event: (-event.salience, event.event_id))
        visible_event_tuple, compressed_event_ids, compression_notes = _compress_visible_events(
            tuple(visible_events),
            max_events=self.max_scene_events,
        )
        clusters = _scene_clusters(visible_event_tuple)
        return SceneInput(
            viewer_id=str(viewer.id),
            room_id=str(room_id) if room_id is not None else None,
            location_title=location_title,
            room_summary=room_summary,
            voice=self.voice,
            visible_characters=visible_characters,
            visible_objects=visible_objects,
            exits=exits,
            events=visible_event_tuple,
            clusters=clusters,
            omitted_event_ids=tuple(omitted),
            compressed_event_ids=compressed_event_ids,
            compression_notes=compression_notes,
            invisible_names=self._invisible_names(viewer),
            facts=_scene_facts(
                room_id=str(room_id) if room_id is not None else None,
                location_title=location_title,
                room_summary=room_summary,
                visible_characters=visible_character_facts,
                visible_objects=visible_object_facts,
                exits=exits,
                events=visible_event_tuple,
                compression_notes=compression_notes,
            ),
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
                epoch = max(event.world_epoch for event in events)
                if self.non_blocking:
                    self._queue_delivery(str(viewer.id), epoch, scene)
                else:
                    self._record_narration(
                        str(viewer.id),
                        epoch,
                        scene,
                        self._render_text_sync(scene),
                    )
        except Exception as exc:  # pragma: no cover - exact exception is stored for operators.
            self.errors.append(str(exc))

    def _on_event(self, event: DomainEvent) -> None:
        self._pending.append(event)

    def _render_text_sync(self, scene: SceneInput) -> str:
        text = self.renderer(scene)
        if inspect.isawaitable(text):
            raise RuntimeError("async narration renderer requires non_blocking=True")
        return text

    def _queue_delivery(self, viewer_id: str, epoch: int, scene: SceneInput) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._record_narration(viewer_id, epoch, scene, self.fallback_renderer(scene))
            return
        task = loop.create_task(self._deliver(viewer_id, epoch, scene))
        self._delivery_tasks.add(task)
        task.add_done_callback(self._delivery_tasks.discard)

    async def _deliver(self, viewer_id: str, epoch: int, scene: SceneInput) -> None:
        try:
            rendered = self.renderer(scene)
            if inspect.isawaitable(rendered):
                text = await asyncio.wait_for(rendered, timeout=self.render_timeout_seconds)
            else:
                text = rendered
        except TimeoutError:
            self.errors.append("narration render timed out")
            text = self.fallback_renderer(scene)
        except Exception as exc:  # noqa: BLE001 - delivery must fall back, not fail the tick.
            self.errors.append(str(exc))
            text = self.fallback_renderer(scene)
        self._record_narration(viewer_id, epoch, scene, text)

    def _record_narration(
        self, viewer_id: str, epoch: int, scene: SceneInput, text: str
    ) -> None:
        narration = SceneNarration(
            viewer_id=viewer_id,
            epoch=epoch,
            scene=scene,
            text=text,
            source_event_ids=tuple(event.event_id for event in scene.events),
        )
        entries = self._transcript[viewer_id]
        entries.append(narration)
        while len(entries) > self.capacity:
            entries.popleft()

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
    "DEFAULT_VOICE",
    "DEFAULT_VOICE_REGISTRY",
    "NarrationVoice",
    "NarrationVoiceRegistry",
    "NarrationIssue",
    "NarrationProjection",
    "SceneCluster",
    "SceneEvent",
    "SceneFact",
    "SceneInput",
    "SceneNarration",
    "check_grounding",
    "render_scene",
]
