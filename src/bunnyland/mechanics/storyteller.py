"""Storyteller incident budgeting and in-world encounters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial

from pydantic.dataclasses import dataclass
from relics import Component, Edge, Entity, EntityId, World

from ..core.commands import SubmittedCommand
from ..core.components import (
    AdminComponent,
    CharacterComponent,
    DeadComponent,
    GenerationIntentComponent,
    HealthComponent,
    IdentityComponent,
    PortableComponent,
    RoomComponent,
    SuspendedComponent,
)
from ..core.ecs import container_of, parse_entity_id, replace_component, spawn_entity
from ..core.edges import ContainmentMode, Contains
from ..core.events import DomainEvent, EventVisibility, event_base
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from ..prompts import ComponentPromptContext

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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.resolved_at_epoch is not None:
            return ()
        return (f"Active incident: {self.kind.replace('_', ' ')}.",)


@dataclass(frozen=True)
class IncidentSpawned(Edge):
    kind: str = "spawn"


@dataclass(frozen=True)
class IncidentDefinition:
    """Plugin-contributed incident selection and generation contract."""

    id: str
    cost: float
    priority: int = 0
    eligible: Callable[[World], bool] = lambda world: True
    generation: Callable[[float], GenerationIntentComponent] | None = None


@dataclass(frozen=True)
class IncidentResolutionRule:
    """Plugin-owned predicate for one spawned incident requirement kind."""

    id: str
    kind: str
    resolved: Callable[[World, IncidentComponent, Entity], bool]


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


class IncidentGeneratedEvent(DomainEvent):
    seed: str
    incident_id: str
    incident_key: str
    kind: str
    budget_spent: float
    generation: GenerationIntentComponent

    @property
    def intent(self) -> str:
        return self.generation.description

    @property
    def tags(self) -> tuple[str, ...]:
        return self.generation.tags

    @property
    def wants(self) -> tuple[str, ...]:
        return self.generation.wants

    @property
    def needs(self) -> tuple[str, ...]:
        return self.generation.needs


_event_base = partial(event_base, default_visibility=EventVisibility.SYSTEM)


def _target_room(world: World):
    for character in world.query().with_all([CharacterComponent]).execute_entities():
        if character.has_component(DeadComponent) or character.has_component(SuspendedComponent):
            continue
        room_id = container_of(character)
        if room_id is not None and world.has_entity(room_id):
            return world.get_entity(room_id)
    rooms = list(world.query().with_all([RoomComponent]).execute_entities())
    return rooms[0] if rooms else None


def _choose_incident(world: World, points: float) -> tuple[str, float]:
    definition, spent = _choose_incident_definition(world, points, default_incident_definitions())
    return definition.id, spent


def default_incident_definitions() -> tuple[IncidentDefinition, ...]:
    return (
        IncidentDefinition(
            id="resource_drop",
            cost=2.0,
            generation=partial(_incident_generation, "resource_drop"),
        ),
        IncidentDefinition(
            id="trader_arrival",
            cost=5.0,
            priority=10,
            generation=partial(_incident_generation, "trader_arrival"),
        ),
        IncidentDefinition(
            id="hostile_encounter",
            cost=10.0,
            priority=20,
            generation=partial(_incident_generation, "hostile_encounter"),
        ),
    )


def _choose_incident_definition(
    world: World,
    points: float,
    definitions: tuple[IncidentDefinition, ...],
) -> tuple[IncidentDefinition, float]:
    eligible = [
        definition
        for definition in definitions
        if definition.cost <= points and definition.eligible(world)
    ]
    if eligible:
        definition = max(eligible, key=lambda item: (item.priority, item.cost, item.id))
        return definition, definition.cost
    fallback = next(
        (definition for definition in definitions if definition.id == "resource_drop"),
        IncidentDefinition(id="resource_drop", cost=2.0),
    )
    return fallback, min(points, fallback.cost)


def _incident_generation(kind: str, spent: float) -> GenerationIntentComponent:
    if kind == "resource_drop":
        return GenerationIntentComponent(
            description="a resource drop incident that should create claimable supplies",
            tags=("incident", "supply", "loot"),
            wants=("loot", "claimable-reward"),
            source_key=kind,
            entity_kind="incident",
        )
    if kind == "hostile_encounter":
        return GenerationIntentComponent(
            description="a hostile encounter incident that should create an enemy threat",
            tags=("incident", "combat", "hostile"),
            wants=("monster", "enemy-threat"),
            source_key=kind,
            entity_kind="incident",
        )
    return GenerationIntentComponent(
        description=f"a {kind.replace('_', ' ')} incident",
        tags=("incident", kind),
        source_key=kind,
        entity_kind="incident",
    )


def _spawn_incident(
    world: World,
    epoch: int,
    room,
    kind: str,
    spent: float,
    generation: GenerationIntentComponent | None = None,
):
    generation = generation or _incident_generation(kind, spent)
    incident = spawn_entity(
        world,
        [
            IdentityComponent(name=kind.replace("_", " "), kind="incident"),
            generation,
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
    return incident


class StorytellerIncidentEnrichment:
    """Builtin incident enrichment for core storyteller incidents."""

    def __init__(self, world: World):
        self.world = world

    def subscribe(self, bus) -> None:
        bus.subscribe(IncidentGeneratedEvent, self._on_incident)

    def _on_incident(self, event: IncidentGeneratedEvent) -> None:
        incident_id = parse_entity_id(event.incident_id)
        room_id = parse_entity_id(event.room_id)
        if (
            incident_id is None
            or room_id is None
            or not self.world.has_entity(incident_id)
            or not self.world.has_entity(room_id)
        ):
            return
        incident = self.world.get_entity(incident_id)
        room = self.world.get_entity(room_id)
        if event.kind == "resource_drop":
            supply = spawn_entity(
                self.world,
                [
                    IdentityComponent(name="supply bundle", kind="item"),
                    PortableComponent(can_pick_up=True),
                ],
            )
            room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), supply.id)
            incident.add_relationship(IncidentSpawned(kind="loot"), supply.id)
        elif event.kind == "hostile_encounter":
            hostile = spawn_entity(
                self.world,
                [
                    IdentityComponent(name="hostile raider", kind="character"),
                    CharacterComponent(species="raider"),
                    HealthComponent(current=10.0, maximum=10.0),
                ],
            )
            room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), hostile.id)
            incident.add_relationship(IncidentSpawned(kind="monster"), hostile.id)


def _is_admin(ctx: HandlerContext, command: SubmittedCommand, actor_id: EntityId) -> bool:
    actor = ctx.entity(actor_id)
    if actor.has_component(AdminComponent):
        return True
    controller_id = parse_entity_id(command.controller_id)
    return (
        controller_id is not None
        and ctx.world.has_entity(controller_id)
        and ctx.entity(controller_id).has_component(AdminComponent)
    )


def _loot_claimed(world: World, incident: IncidentComponent, entity: Entity) -> bool:
    if incident.room_id is None:
        return False
    return container_of(entity) != parse_entity_id(incident.room_id)


def _monster_neutralized(world: World, incident: IncidentComponent, entity: Entity) -> bool:
    del world, incident
    return entity.has_component(DeadComponent) or entity.has_component(SuspendedComponent)


DEFAULT_RESOLUTION_RULES = (
    IncidentResolutionRule(id="loot-claimed", kind="loot", resolved=_loot_claimed),
    IncidentResolutionRule(id="monster-neutralized", kind="monster", resolved=_monster_neutralized),
)


def _spawned_requirement_done(
    world: World,
    incident: IncidentComponent,
    kind: str,
    target_id,
    rules: tuple[IncidentResolutionRule, ...] = DEFAULT_RESOLUTION_RULES,
) -> bool:
    if not world.has_entity(target_id):
        return True
    target = world.get_entity(target_id)
    matching = tuple(rule for rule in rules if rule.kind == kind)
    return not matching or any(rule.resolved(world, incident, target) for rule in matching)


def _incident_ready_to_resolve(
    world: World,
    incident_entity: Entity,
    rules: tuple[IncidentResolutionRule, ...] = DEFAULT_RESOLUTION_RULES,
) -> bool:
    incident = incident_entity.get_component(IncidentComponent)
    spawned = tuple(incident_entity.get_relationships(IncidentSpawned))
    if not spawned:
        return False
    return all(
        _spawned_requirement_done(world, incident, edge.kind, target_id, rules)
        for edge, target_id in spawned
    )


def _resolve_incident(
    incident_entity: Entity, incident: IncidentComponent, epoch: int, *, actor_id: str
) -> IncidentResolvedEvent:
    replace_component(incident_entity, replace(incident, resolved_at_epoch=epoch))
    return IncidentResolvedEvent(
        **_event_base(
            epoch,
            visibility=EventVisibility.ROOM if incident.room_id else EventVisibility.SYSTEM,
            actor_id=actor_id,
            room_id=incident.room_id,
            target_ids=(str(incident_entity.id),),
            incident_id=str(incident_entity.id),
            kind=incident.kind,
        )
    )


class StorytellerConsequence:
    """Accrue incident budget and start a deterministic incident when due."""

    def __init__(self, incidents: tuple[IncidentDefinition, ...] = ()) -> None:
        self.incidents = incidents

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
            if self.incidents:
                definition, spent = _choose_incident_definition(
                    world, points + threat, self.incidents
                )
                kind = definition.id
                generation = (
                    definition.generation(spent)
                    if definition.generation is not None
                    else _incident_generation(kind, spent)
                )
            else:
                kind, spent = _choose_incident(world, points + threat)
                generation = _incident_generation(kind, spent)
            room = _target_room(world)
            incident = _spawn_incident(world, epoch, room, kind, spent, generation)
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
            generation = incident.get_component(GenerationIntentComponent)
            events.append(
                IncidentGeneratedEvent(
                    **_event_base(
                        epoch,
                        actor_id=str(entity.id),
                        room_id=room_id,
                        target_ids=(str(incident.id),),
                        seed=f"{kind}:{epoch}:{spent:g}",
                        incident_id=str(incident.id),
                        incident_key=kind,
                        kind=kind,
                        budget_spent=spent,
                        generation=generation,
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


class IncidentAutoResolutionConsequence:
    """Resolve active incidents once every spawned blocker has been handled."""

    def __init__(
        self, rules: tuple[IncidentResolutionRule, ...] = DEFAULT_RESOLUTION_RULES
    ) -> None:
        self.rules = rules

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for incident_entity in world.query().with_all([IncidentComponent]).execute_entities():
            incident = incident_entity.get_component(IncidentComponent)
            if incident.resolved_at_epoch is not None:
                continue
            if not _incident_ready_to_resolve(world, incident_entity, self.rules):
                continue
            events.append(
                _resolve_incident(
                    incident_entity,
                    incident,
                    epoch,
                    actor_id=str(incident_entity.id),
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
        if not _is_admin(ctx, command, actor_id):
            return rejected("admin privileges required")
        if not ctx.world.has_entity(incident_id):
            return rejected("incident does not exist")
        incident_entity = ctx.entity(incident_id)
        if not incident_entity.has_component(IncidentComponent):
            return rejected("target is not an incident")
        incident = incident_entity.get_component(IncidentComponent)
        if incident.resolved_at_epoch is not None:
            return rejected("incident is already resolved")
        resolved = _resolve_incident(
            incident_entity,
            incident,
            ctx.epoch,
            actor_id=str(actor_id),
        )
        return ok(resolved)


def storyteller_fragments(world: World, character) -> list[str]:
    ctx = ComponentPromptContext.for_entity(world, character)
    if ctx.room is None:
        return []
    lines = []
    for entity in ctx.room_siblings(IncidentComponent):
        incident_ctx = ComponentPromptContext.for_entity(
            world, entity, perspective=ctx.perspective, room=ctx.room
        )
        lines.extend(entity.get_component(IncidentComponent).prompt_fragments(incident_ctx))
    return sorted(lines)


def install_storyteller(
    actor,
    context=None,
    *,
    incidents: tuple[IncidentDefinition, ...] = (),
    resolution_rules: tuple[IncidentResolutionRule, ...] = (),
) -> None:
    registered_incidents = (
        tuple(context.plugins.incidents.values())
        if context is not None and context.plugins is not None
        else incidents
    )
    actor.register_consequence(StorytellerConsequence(registered_incidents))
    contributed_rules = (
        tuple(context.plugins.incident_resolution_rules.values())
        if context is not None and context.plugins is not None
        else resolution_rules
    )
    actor.register_consequence(
        IncidentAutoResolutionConsequence((*DEFAULT_RESOLUTION_RULES, *contributed_rules))
    )
    StorytellerIncidentEnrichment(actor.world).subscribe(actor.bus)


__all__ = [
    "IncidentBudgetComponent",
    "IncidentComponent",
    "IncidentAutoResolutionConsequence",
    "IncidentGeneratedEvent",
    "IncidentHistoryComponent",
    "IncidentDefinition",
    "IncidentResolutionRule",
    "IncidentProposedEvent",
    "IncidentResolvedEvent",
    "IncidentSpawned",
    "IncidentStartedEvent",
    "ResolveIncidentHandler",
    "StorytellerIncidentEnrichment",
    "StorytellerComponent",
    "StorytellerConsequence",
    "default_incident_definitions",
    "ThreatPointsComponent",
    "install_storyteller",
    "storyteller_fragments",
]
