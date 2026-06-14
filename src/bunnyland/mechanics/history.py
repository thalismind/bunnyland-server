"""Durable world history records.

World history is shared, persisted ECS state. It is distinct from private memory:
characters may forget, but notable deeds can remain in the world as records that prompts,
reputation, artifacts, and later consequence systems can query.
"""

from __future__ import annotations

from pydantic.dataclasses import dataclass
from relics import Component, Edge, Entity, EntityId, World

from ..core.components import IdentityComponent
from ..core.ecs import container_of, entity_name, parse_entity_id, reachable_ids, spawn_entity
from ..core.events import (
    CharacterDiedEvent,
    DomainEvent,
    ItemCraftedEvent,
    PhysicalWriteEvent,
)

_HISTORY_PROMPT_LIMIT = 5
_SUMMARY_LIMIT = 180
_QUOTE_LIMIT = 90


@dataclass(frozen=True)
class WorldHistoryRecordComponent(Component):
    """A notable, queryable world-history record."""

    summary: str
    source_event_id: str
    event_type: str
    created_at_epoch: int
    location_id: str = ""
    tags: tuple[str, ...] = ()
    salience: float = 1.0


@dataclass(frozen=True)
class HistoryActor(Edge):
    """history record -> actor involved in the deed."""

    role: str = "actor"


@dataclass(frozen=True)
class HistoryTarget(Edge):
    """history record -> target or artifact involved in the deed."""

    role: str = "target"


def install_history(actor) -> None:
    """Subscribe the durable history projector to the actor bus."""

    WorldHistoryReactor(actor.world).subscribe(actor.bus)


def world_history_records(
    world: World, *, tags: set[str] | None = None
) -> list[tuple[Entity, WorldHistoryRecordComponent]]:
    """Return history records, newest/highest salience first."""

    records: list[tuple[Entity, WorldHistoryRecordComponent]] = []
    for entity in world.query().with_all([WorldHistoryRecordComponent]).execute_entities():
        record = entity.get_component(WorldHistoryRecordComponent)
        if tags is not None and not tags.intersection(record.tags):
            continue
        records.append((entity, record))
    return sorted(
        records,
        key=lambda item: (
            item[1].created_at_epoch,
            item[1].salience,
            item[1].source_event_id,
        ),
        reverse=True,
    )


def history_record_for_event(world: World, source_event_id: str) -> Entity | None:
    """Return the record created from ``source_event_id``, if any."""

    for entity, record in world_history_records(world):
        if record.source_event_id == source_event_id:
            return entity
    return None


def record_world_history(
    world: World,
    *,
    summary: str,
    source_event_id: str,
    event_type: str,
    created_at_epoch: int,
    location_id: str = "",
    actor_ids: tuple[str, ...] = (),
    target_ids: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    salience: float = 1.0,
) -> Entity | None:
    """Create one durable ECS record for a notable event.

    Duplicate source event ids are ignored so replaying or re-emitting an event cannot
    create repeated history entries.
    """

    text = _clean(summary)
    if not text or not source_event_id:
        return None
    if history_record_for_event(world, source_event_id) is not None:
        return None

    record = spawn_entity(
        world,
        [
            IdentityComponent(name=f"History: {_truncate(text, 48)}", kind="history"),
            WorldHistoryRecordComponent(
                summary=_truncate(text, _SUMMARY_LIMIT),
                source_event_id=source_event_id,
                event_type=event_type,
                created_at_epoch=created_at_epoch,
                location_id=location_id,
                tags=tuple(dict.fromkeys(tag for tag in tags if tag)),
                salience=max(0.0, salience),
            ),
        ],
    )
    for actor_id in dict.fromkeys(actor_ids):
        parsed = parse_entity_id(actor_id)
        if parsed is not None and world.has_entity(parsed):
            record.add_relationship(HistoryActor(), parsed)
    for target_id in dict.fromkeys(target_ids):
        parsed = parse_entity_id(target_id)
        if parsed is not None and world.has_entity(parsed):
            record.add_relationship(HistoryTarget(), parsed)
    return record


def history_fragments(world: World, character: Entity) -> list[str]:
    """Prompt lines for relevant world history near a character."""

    room_id = container_of(character)
    visible = reachable_ids(world, character)
    fragments: list[str] = []
    for record_entity, record in world_history_records(world):
        if not _record_relevant(record_entity, record, character.id, room_id, visible):
            continue
        fragments.append(
            f"World history: {record.summary} "
            f"[history:{record_entity.id} source:{record.source_event_id}]"
        )
        if len(fragments) >= _HISTORY_PROMPT_LIMIT:
            break
    return fragments


class WorldHistoryReactor:
    """Project selected domain events into durable shared history."""

    def __init__(self, world: World) -> None:
        self.world = world

    def subscribe(self, bus) -> None:
        bus.subscribe(DomainEvent, self._on_event)

    def _on_event(self, event: DomainEvent) -> None:
        payload = _history_payload(self.world, event)
        if payload is None:
            return
        record_world_history(self.world, **payload)


def _history_payload(world: World, event: DomainEvent) -> dict | None:
    actor_ids = (event.actor_id,) if event.actor_id else ()
    location_id = event.room_id or _location_for_event_actor(world, event)
    if isinstance(event, PhysicalWriteEvent):
        target_ids = (event.item_id,)
        actor = _name(world, event.actor_id)
        target = _name(world, event.item_id)
        quote = _truncate(_clean(event.text), _QUOTE_LIMIT)
        return {
            "summary": f'{actor} wrote on {target}: "{quote}"',
            "source_event_id": event.event_id,
            "event_type": type(event).__name__,
            "created_at_epoch": event.world_epoch,
            "location_id": location_id,
            "actor_ids": actor_ids,
            "target_ids": target_ids,
            "tags": ("authored", "writing", "artifact"),
            "salience": 0.7,
        }
    if isinstance(event, ItemCraftedEvent):
        output_names = [_name(world, output_id) for output_id in event.output_ids]
        count = len(event.output_ids)
        outputs = ", ".join(output_names[:3]) if output_names else f"{count} item"
        if count > 3:
            outputs = f"{outputs}, and {count - 3} more"
        actor = _name(world, event.actor_id)
        return {
            "summary": f"{actor} crafted {outputs} from recipe {event.recipe_id}.",
            "source_event_id": event.event_id,
            "event_type": type(event).__name__,
            "created_at_epoch": event.world_epoch,
            "location_id": location_id,
            "actor_ids": actor_ids,
            "target_ids": event.output_ids,
            "tags": ("crafted", "artifact"),
            "salience": 0.8,
        }
    if isinstance(event, CharacterDiedEvent):
        actor = _name(world, event.actor_id)
        cause = _clean(event.cause) or "unknown causes"
        return {
            "summary": f"{actor} died from {cause}.",
            "source_event_id": event.event_id,
            "event_type": type(event).__name__,
            "created_at_epoch": event.world_epoch,
            "location_id": location_id,
            "actor_ids": actor_ids,
            "target_ids": actor_ids,
            "tags": ("death", "loss", "consequence"),
            "salience": 1.0,
        }
    return None


def _record_relevant(
    record_entity: Entity,
    record: WorldHistoryRecordComponent,
    character_id: EntityId,
    room_id: EntityId | None,
    visible: set[EntityId],
) -> bool:
    if room_id is not None and record.location_id == str(room_id):
        return True
    for _edge, actor_id in record_entity.get_relationships(HistoryActor):
        if actor_id == character_id:
            return True
    for _edge, target_id in record_entity.get_relationships(HistoryTarget):
        if target_id in visible:
            return True
    return False


def _location_for_event_actor(world: World, event: DomainEvent) -> str:
    actor_id = parse_entity_id(event.actor_id) if event.actor_id else None
    if actor_id is not None and world.has_entity(actor_id):
        room_id = container_of(world.get_entity(actor_id))
        if room_id is not None:
            return str(room_id)
    for raw_target_id in event.target_ids:
        target_id = parse_entity_id(raw_target_id)
        if target_id is not None and world.has_entity(target_id):
            room_id = container_of(world.get_entity(target_id))
            if room_id is not None:
                return str(room_id)
    return ""


def _name(world: World, raw_id: str | None) -> str:
    entity_id = parse_entity_id(raw_id) if raw_id else None
    if entity_id is not None and world.has_entity(entity_id):
        return entity_name(world.get_entity(entity_id), fallback="someone")
    return "someone"


def _clean(text: str) -> str:
    return " ".join(str(text).split())


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


__all__ = [
    "HistoryActor",
    "HistoryTarget",
    "WorldHistoryReactor",
    "WorldHistoryRecordComponent",
    "history_fragments",
    "history_record_for_event",
    "install_history",
    "record_world_history",
    "world_history_records",
]
