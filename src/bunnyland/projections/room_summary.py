"""Room-summary projection (spec 11.4, 17).

Structured ``RoomFacts`` are computed deterministically from the world and drive actions;
a prose ``visible_summary`` is rendered from them for readability and cached in the
room's ``RoomSummaryComponent``. The cache is marked dirty by world events and rebuilt
lazily on read. Semantic bands (dark/dim/lit/bright, cold/cool/mild/warm/hot) are used
instead of raw numbers so tiny changes don't churn the summary (spec 17.3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from relics import (
    EntityId,
    OnComponentAdded,
    OnComponentRemoved,
    OnRelationshipAdded,
    OnRelationshipRemoved,
    World,
)

from ..core.components import (
    CharacterComponent,
    ContainerComponent,
    DoorComponent,
    IdentityComponent,
    LightComponent,
    LockableComponent,
    RoomComponent,
    RoomSummaryComponent,
    TemperatureComponent,
)
from ..core.ecs import container_of, contents, replace_component
from ..core.edges import Contains, ExitTo

# Components/edges whose add or remove can change a room's visible state (spec 17.3).
# Our frozen components are replaced (remove+add), so add/remove observers catch edits too.
_ROOM_COMPONENTS = (RoomComponent, LightComponent, TemperatureComponent)
_ROOM_EDGES = (Contains, ExitTo)


# --------------------------------------------------------------------------------------
# Structured facts
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RoomObject:
    id: str
    name: str
    states: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoomExit:
    direction: str
    to_room_id: str
    locked: bool = False


@dataclass(frozen=True)
class RoomFacts:
    room_id: str
    title: str
    biome: str
    occupants: tuple[tuple[str, str], ...] = ()  # (entity_id, name)
    objects: tuple[RoomObject, ...] = ()
    exits: tuple[RoomExit, ...] = ()
    bands: Mapping[str, str] = field(default_factory=dict)


def light_band(level: float) -> str:
    if level < 0.2:
        return "dark"
    if level < 0.5:
        return "dim"
    if level < 0.85:
        return "lit"
    return "bright"


def temperature_band(celsius: float) -> str:
    if celsius < 5:
        return "cold"
    if celsius < 15:
        return "cool"
    if celsius < 24:
        return "mild"
    if celsius < 32:
        return "warm"
    return "hot"


def _object_states(entity) -> tuple[str, ...]:
    states: list[str] = []
    if entity.has_component(DoorComponent):
        states.append("open" if entity.get_component(DoorComponent).open else "closed")
    elif entity.has_component(ContainerComponent):
        states.append("open" if entity.get_component(ContainerComponent).open else "closed")
    if entity.has_component(LockableComponent) and entity.get_component(LockableComponent).locked:
        states.append("locked")
    return tuple(states)


def _name(entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return "something"


def build_room_facts(world: World, room_id: EntityId) -> RoomFacts:
    """Compute the objective, deterministic facts of a room from current ECS state."""
    room = world.get_entity(room_id)
    room_component = (
        room.get_component(RoomComponent) if room.has_component(RoomComponent) else None
    )

    occupants: list[tuple[str, str]] = []
    objects: list[RoomObject] = []
    for child_id in contents(room):
        child = world.get_entity(child_id)
        if child.has_component(CharacterComponent):
            occupants.append((str(child_id), _name(child)))
        else:
            objects.append(
                RoomObject(id=str(child_id), name=_name(child), states=_object_states(child))
            )

    exits = tuple(
        RoomExit(direction=edge.direction, to_room_id=str(target), locked=edge.locked)
        for edge, target in room.get_relationships(ExitTo)
    )

    bands: dict[str, str] = {}
    if room.has_component(LightComponent):
        bands["light"] = light_band(room.get_component(LightComponent).level)
    if room.has_component(TemperatureComponent):
        bands["temperature"] = temperature_band(room.get_component(TemperatureComponent).celsius)

    return RoomFacts(
        room_id=str(room_id),
        title=room_component.title if room_component else "an unknown place",
        biome=room_component.biome if room_component else "unknown",
        occupants=tuple(sorted(occupants)),
        objects=tuple(sorted(objects, key=lambda o: o.name)),
        exits=tuple(sorted(exits, key=lambda e: e.direction)),
        bands=bands,
    )


def render_summary(facts: RoomFacts) -> str:
    """Deterministic template prose (LLM prose summaries are a later, optional feature)."""
    lines = [facts.title]
    if facts.bands:
        descriptors = ", ".join(facts.bands[k] for k in sorted(facts.bands))
        lines.append(f"It is {descriptors}.")
    if facts.occupants:
        lines.append("Here: " + ", ".join(name for _id, name in facts.occupants) + ".")
    if facts.objects:
        rendered = []
        for obj in facts.objects:
            rendered.append(f"{obj.name} ({', '.join(obj.states)})" if obj.states else obj.name)
        lines.append("You see: " + ", ".join(rendered) + ".")
    if facts.exits:
        lines.append("Exits: " + ", ".join(e.direction for e in facts.exits) + ".")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Observers (spec 17.3): keep the cache honest by reacting to ECS changes directly
# --------------------------------------------------------------------------------------


def _component_observer(component_type, dirty, *, removed: bool):
    """A Relics observer that dirties the room of an entity when ``component_type`` changes."""
    if removed:

        class _Observer(OnComponentRemoved):
            def on_component_removed(self, entity, component) -> None:
                dirty(entity)
    else:

        class _Observer(OnComponentAdded):
            def on_component_added(self, entity, component) -> None:
                dirty(entity)

    _Observer.component_type = component_type
    return _Observer()


def _relationship_observer(edge_type, dirty, *, removed: bool):
    """A Relics observer that dirties a room when an ``edge_type`` edge from it changes."""
    if removed:

        class _Observer(OnRelationshipRemoved):
            def on_relationship_removed(self, source, edge, target) -> None:
                dirty(source)
    else:

        class _Observer(OnRelationshipAdded):
            def on_relationship_added(self, source, edge, target) -> None:
                dirty(source)

    _Observer.edge_type = edge_type
    return _Observer()


# --------------------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------------------


class RoomSummaryProjection:
    """Rebuilds room summaries lazily; Relics observers mark a room dirty when its own
    conditions, contents, or exits change (spec 11.4, 17.3)."""

    def __init__(self, world: World) -> None:
        self.world = world
        self._attached = False

    def attach(self, world: World | None = None) -> RoomSummaryProjection:
        """Register the ECS observers that dirty a room on relevant changes (idempotent)."""
        if world is not None:
            self.world = world
        if self._attached:
            return self
        for component_type in _ROOM_COMPONENTS:
            self.world.observe(_component_observer(component_type, self._dirty, removed=False))
            self.world.observe(_component_observer(component_type, self._dirty, removed=True))
        for edge_type in _ROOM_EDGES:
            self.world.observe(_relationship_observer(edge_type, self._dirty, removed=False))
            self.world.observe(_relationship_observer(edge_type, self._dirty, removed=True))
        self._attached = True
        return self

    # -- dirtying ----------------------------------------------------------------------

    def _dirty(self, entity) -> None:
        """Dirty the room an observed entity belongs to: itself if a room, else its room."""
        if entity.has_component(RoomComponent):
            self.mark_dirty(entity.id)
            return
        parent = container_of(entity)
        if parent is not None and self.world.has_entity(parent):
            if self.world.get_entity(parent).has_component(RoomComponent):
                self.mark_dirty(parent)

    def mark_dirty(self, room_id: EntityId) -> None:
        if not self.world.has_entity(room_id):
            return
        room = self.world.get_entity(room_id)
        if not room.has_component(RoomComponent):
            return
        existing = (
            room.get_component(RoomSummaryComponent)
            if room.has_component(RoomSummaryComponent)
            else RoomSummaryComponent()
        )
        if not existing.dirty:
            replace_component(room, replace(existing, dirty=True))

    # -- reads -------------------------------------------------------------------------

    def facts(self, room_id: EntityId) -> RoomFacts:
        return build_room_facts(self.world, room_id)

    def summary(self, room_id: EntityId, epoch: int) -> RoomSummaryComponent:
        """Return the cached summary, rebuilding it first if dirty or missing."""
        room = self.world.get_entity(room_id)
        if (
            not room.has_component(RoomSummaryComponent)
            or room.get_component(RoomSummaryComponent).dirty
        ):
            self._rebuild(room_id, epoch)
        return room.get_component(RoomSummaryComponent)

    def _rebuild(self, room_id: EntityId, epoch: int) -> None:
        room = self.world.get_entity(room_id)
        facts = build_room_facts(self.world, room_id)
        previous_version = (
            room.get_component(RoomSummaryComponent).version
            if room.has_component(RoomSummaryComponent)
            else 0
        )
        replace_component(
            room,
            RoomSummaryComponent(
                visible_summary=render_summary(facts),
                last_updated_epoch=epoch,
                version=previous_version + 1,
                dirty=False,
            ),
        )


__all__ = [
    "RoomExit",
    "RoomFacts",
    "RoomObject",
    "RoomSummaryProjection",
    "build_room_facts",
    "light_band",
    "render_summary",
    "temperature_band",
]
