"""Storyteller incident budgeting and in-world encounters."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from pydantic.dataclasses import dataclass
from relics import Component, World

from ..core.commands import SubmittedCommand
from ..core.components import (
    CharacterComponent,
    DeadComponent,
    IdentityComponent,
    PortableComponent,
    RoomComponent,
    SuspendedComponent,
)
from ..core.ecs import container_of, parse_entity_id, reachable_ids, replace_component, spawn_entity
from ..core.edges import ContainmentMode, Contains
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected

SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class StorytellerComponent(Component):
    enabled: bool = True
    interval_seconds: int = SECONDS_PER_DAY
    next_incident_epoch: int = SECONDS_PER_DAY


@dataclass(frozen=True)
class IncidentBudgetComponent(Component):
    points: float = 0.0
    points_per_day: float = 6.0
    max_points: float = 100.0
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class ThreatPointsComponent(Component):
    points: float = 0.0


@dataclass(frozen=True)
class IncidentHistoryComponent(Component):
    incident_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class IncidentComponent(Component):
    kind: str
    budget_spent: float
    started_at_epoch: int
    room_id: str | None = None
    resolved_at_epoch: int | None = None


class IncidentProposedEvent(DomainEvent):
    incident_id: str
    kind: str
    budget_spent: float


class IncidentStartedEvent(DomainEvent):
    incident_id: str
    kind: str
    room_id_started: str | None = None


class IncidentResolvedEvent(DomainEvent):
    incident_id: str
    kind: str


def _event_base(epoch: int, **kwargs) -> dict:
    base = {
        "event_id": uuid4().hex,
        "world_epoch": epoch,
        "created_at": datetime.now(UTC),
        "visibility": EventVisibility.SYSTEM,
    }
    base.update(kwargs)
    return base


def _target_room(world: World):
    for character in world.query().with_all([CharacterComponent]).execute_entities():
        if character.has_component(DeadComponent) or character.has_component(SuspendedComponent):
            continue
        room_id = container_of(character)
        if room_id is not None and world.has_entity(room_id):
            return world.get_entity(room_id)
    rooms = list(world.query().with_all([RoomComponent]).execute_entities())
    return rooms[0] if rooms else None


def _choose_incident(points: float) -> tuple[str, float]:
    if points >= 10:
        return "hostile_encounter", 10.0
    if points >= 5:
        return "trader_arrival", 5.0
    return "resource_drop", min(points, 2.0)


def _spawn_incident(world: World, epoch: int, room, kind: str, spent: float):
    incident = spawn_entity(
        world,
        [
            IdentityComponent(name=kind.replace("_", " "), kind="incident"),
            IncidentComponent(
                kind=kind,
                budget_spent=spent,
                started_at_epoch=epoch,
                room_id=str(room.id) if room is not None else None,
            ),
        ],
    )
    if room is not None:
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), incident.id)
        if kind == "resource_drop":
            supply = spawn_entity(
                world,
                [
                    IdentityComponent(name="supply bundle", kind="item"),
                    PortableComponent(can_pick_up=True),
                ],
            )
            room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), supply.id)
    return incident


class StorytellerConsequence:
    """Accrue incident budget and start a deterministic incident when due."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = world.query().with_all([StorytellerComponent, IncidentBudgetComponent])
        for entity in query.execute_entities():
            storyteller = entity.get_component(StorytellerComponent)
            budget = entity.get_component(IncidentBudgetComponent)
            elapsed = max(0, epoch - budget.last_updated_epoch)
            points = min(
                budget.max_points,
                budget.points + budget.points_per_day * (elapsed / SECONDS_PER_DAY),
            )
            if not storyteller.enabled or epoch < storyteller.next_incident_epoch:
                replace_component(entity, replace(budget, points=points, last_updated_epoch=epoch))
                continue

            threat = (
                entity.get_component(ThreatPointsComponent).points
                if entity.has_component(ThreatPointsComponent)
                else 0.0
            )
            kind, spent = _choose_incident(points + threat)
            room = _target_room(world)
            incident = _spawn_incident(world, epoch, room, kind, spent)
            history = (
                entity.get_component(IncidentHistoryComponent)
                if entity.has_component(IncidentHistoryComponent)
                else IncidentHistoryComponent()
            )
            replace_component(
                entity,
                replace(
                    budget,
                    points=max(0.0, points - spent),
                    last_updated_epoch=epoch,
                ),
            )
            replace_component(
                entity,
                replace(storyteller, next_incident_epoch=epoch + storyteller.interval_seconds),
            )
            replace_component(
                entity,
                IncidentHistoryComponent(
                    incident_ids=(*history.incident_ids, str(incident.id))[-10:]
                ),
            )
            room_id = str(room.id) if room is not None else None
            events.append(
                IncidentProposedEvent(
                    **_event_base(
                        epoch,
                        actor_id=str(entity.id),
                        room_id=room_id,
                        target_ids=(str(incident.id),),
                        incident_id=str(incident.id),
                        kind=kind,
                        budget_spent=spent,
                    )
                )
            )
            events.append(
                IncidentStartedEvent(
                    **_event_base(
                        epoch,
                        visibility=EventVisibility.ROOM if room_id else EventVisibility.SYSTEM,
                        actor_id=str(entity.id),
                        room_id=room_id,
                        target_ids=(str(incident.id),),
                        incident_id=str(incident.id),
                        kind=kind,
                        room_id_started=room_id,
                    )
                )
            )
        return events


class ResolveIncidentHandler:
    command_type = "resolve-incident"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        incident_id = parse_entity_id(command.payload.get("incident_id"))
        if actor_id is None or incident_id is None:
            return rejected("invalid character or incident id")
        if not ctx.world.has_entity(incident_id):
            return rejected("incident does not exist")
        actor = ctx.entity(actor_id)
        if incident_id not in reachable_ids(ctx.world, actor):
            return rejected("incident is not reachable")
        incident_entity = ctx.entity(incident_id)
        if not incident_entity.has_component(IncidentComponent):
            return rejected("target is not an incident")
        incident = incident_entity.get_component(IncidentComponent)
        if incident.resolved_at_epoch is not None:
            return rejected("incident is already resolved")
        replace_component(incident_entity, replace(incident, resolved_at_epoch=ctx.epoch))
        return ok(
            IncidentResolvedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(actor)) if container_of(actor) else None,
                    target_ids=(str(incident_id),),
                    incident_id=str(incident_id),
                    kind=incident.kind,
                )
            )
        )


def storyteller_fragments(world: World, character) -> list[str]:
    room_id = container_of(character)
    if room_id is None or not world.has_entity(room_id):
        return []
    lines = []
    for _edge, entity_id in world.get_entity(room_id).get_relationships(Contains):
        if not world.has_entity(entity_id):
            continue
        entity = world.get_entity(entity_id)
        if entity.has_component(IncidentComponent):
            incident = entity.get_component(IncidentComponent)
            if incident.resolved_at_epoch is None:
                lines.append(f"Active incident: {incident.kind.replace('_', ' ')}.")
    return sorted(lines)


def install_storyteller(actor) -> None:
    actor.register_consequence(StorytellerConsequence())


__all__ = [
    "IncidentBudgetComponent",
    "IncidentComponent",
    "IncidentHistoryComponent",
    "IncidentProposedEvent",
    "IncidentResolvedEvent",
    "IncidentStartedEvent",
    "ResolveIncidentHandler",
    "StorytellerComponent",
    "StorytellerConsequence",
    "ThreatPointsComponent",
    "install_storyteller",
    "storyteller_fragments",
]
