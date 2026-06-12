"""Void-sim sci-fi frontier mechanics (catalogue section 8).

FTL-inspired: ships and stations made of habitat modules, life support and pressure that
can fail, power that must be rerouted, ship systems that take damage and get repaired,
and docking between craft. This module owns section 8.1 (ships, stations, and habitats);
later subsections (travel, crew, hazards, contracts) build on the same components.

Following the rest of bunnyland, systems read broadly but write narrowly: the life
support consequence only touches oxygen and emits a failure event; it never reaches into
mood, health, or other packages.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic.dataclasses import dataclass
from relics import Component, Edge, Entity, EntityId, World

from ..core.commands import SubmittedCommand
from ..core.components import (
    CharacterComponent,
    DeadComponent,
    IdentityComponent,
    SuspendedComponent,
)
from ..core.ecs import (
    container_of,
    contents,
    parse_entity_id,
    reachable_ids,
    replace_component,
)
from ..core.edges import ContainmentMode, Contains
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from .barbariansim import CorruptionComponent, CorruptionGainedEvent

SECONDS_PER_HOUR = 60 * 60
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR


@dataclass(frozen=True)
class ShipComponent(Component):
    name: str
    hull_integrity: float = 100.0


@dataclass(frozen=True)
class StationComponent(Component):
    name: str


@dataclass(frozen=True)
class HabitatModuleComponent(Component):
    module_type: str
    ship_id: str | None = None


@dataclass(frozen=True)
class AirlockComponent(Component):
    state: str = "sealed"  # sealed | open | cycled
    module_id: str | None = None
    exposes_vacuum: bool = False


@dataclass(frozen=True)
class BulkheadComponent(Component):
    sealed: bool = False


@dataclass(frozen=True)
class PressurizedComponent(Component):
    pressure: float = 1.0  # atmospheres; 0.0 == vacuum


@dataclass(frozen=True)
class LifeSupportComponent(Component):
    online: bool = True
    oxygen_per_hour: float = 5.0


@dataclass(frozen=True)
class ShipSystemComponent(Component):
    system_type: str
    integrity: float = 100.0
    online: bool = True


@dataclass(frozen=True)
class PowerGridComponent(Component):
    capacity: float = 100.0
    available: float = 100.0


@dataclass(frozen=True)
class OxygenComponent(Component):
    level: float = 100.0
    maximum: float = 100.0
    failed: bool = False
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class RadiationShieldComponent(Component):
    strength: float = 100.0


@dataclass(frozen=True)
class ChaosInfluenceComponent(Component):
    """Warp/chaos pressure source.

    Void-sim treats barbarian-sim corruption as the character's chaos state. This component
    is only the environmental source that applies it.
    """

    source_type: str = "warp breach"
    corruption_per_hour: float = 1.0
    system_damage_per_hour: float = 0.0
    mutation_pressure_per_corruption: float = 1.0
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class ChaosWardComponent(Component):
    """Protection against nearby chaos influence."""

    protection_per_hour: float = 1.0


@dataclass(frozen=True)
class ChaosMutationPressureComponent(Component):
    """Chaos-specific mutation pressure from warp/corruption exposure."""

    amount: float = 0.0
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class RadiationMutationPressureComponent(Component):
    """Radiation-specific mutation pressure reserved for nuke-sim.

    TODO(nuke-sim): accumulate ionizing radiation here and resolve radiation-specific
    mutation outcomes without mixing it into chaos pressure.
    """

    amount: float = 0.0
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class CyberneticMutationPressureComponent(Component):
    """Cybernetic/body-mod pressure reserved for future augmentation systems.

    TODO(nuke-sim): decide whether cybernetics compete with, suppress, or amplify organic
    mutation outcomes while still tracking their pressure independently.
    """

    amount: float = 0.0
    last_updated_epoch: int = 0


# --- 8.2 Space travel, orbits, and navigation -----------------------------------------


@dataclass(frozen=True)
class StarSystemComponent(Component):
    name: str


@dataclass(frozen=True)
class OrbitalBodyComponent(Component):
    body_type: str  # planet | moon | asteroid-belt | station
    landable: bool = True


@dataclass(frozen=True)
class OrbitComponent(Component):
    body_id: str
    altitude: str = "orbit"  # orbit | surface


@dataclass(frozen=True)
class NavigationRouteComponent(Component):
    destination_id: str
    fuel_cost: float = 0.0
    hazard: str = "none"
    jump_seconds: float = 0.0
    status: str = "plotted"  # plotted | jumping
    arrive_at_epoch: int = 0


@dataclass(frozen=True)
class JumpDriveComponent(Component):
    charged: bool = True
    jump_seconds: float = 3600.0


@dataclass(frozen=True)
class FuelComponent(Component):
    level: float = 100.0
    maximum: float = 100.0


@dataclass(frozen=True)
class SensorComponent(Component):
    scan_range: float = 1.0


@dataclass(frozen=True)
class DistressSignalComponent(Component):
    text: str
    source_site_id: str | None = None
    detected: bool = False
    answered: bool = False


@dataclass(frozen=True)
class AstrogationComponent(Component):
    skill: int = 0


@dataclass(frozen=True)
class DockedTo(Edge):
    port: str = "main"


@dataclass(frozen=True)
class JumpRoute(Edge):
    fuel_cost: float = 10.0
    hazard: str = "none"
    jump_seconds: float = 3600.0
    label: str = ""


class AirlockCycledEvent(DomainEvent):
    airlock_id: str
    state: str


class PressureChangedEvent(DomainEvent):
    module_id: str
    pressure: float


class LifeSupportFailedEvent(DomainEvent):
    module_id: str


class PowerReroutedEvent(DomainEvent):
    system_id: str
    amount: float


class ShipSystemDamagedEvent(DomainEvent):
    system_id: str
    system_type: str
    integrity: float


class ShipSystemRepairedEvent(DomainEvent):
    system_id: str
    system_type: str


class DockingCompletedEvent(DomainEvent):
    ship_id: str
    station_id: str
    docked: bool


class ModuleEvacuatedEvent(DomainEvent):
    module_id: str
    evacuee_ids: tuple[str, ...] = ()


class CoursePlottedEvent(DomainEvent):
    ship_id: str
    destination_id: str
    fuel_cost: float


class JumpStartedEvent(DomainEvent):
    ship_id: str
    destination_id: str
    arrive_at_epoch: int


class JumpCompletedEvent(DomainEvent):
    ship_id: str
    destination_id: str


class FuelChangedEvent(DomainEvent):
    ship_id: str
    level: float
    maximum: float


class SignalDetectedEvent(DomainEvent):
    signal_id: str
    text: str


class NavigationHazardEncounteredEvent(DomainEvent):
    ship_id: str
    hazard: str


class OrbitEnteredEvent(DomainEvent):
    ship_id: str
    body_id: str


class LandingCompletedEvent(DomainEvent):
    ship_id: str
    body_id: str


class ChaosInfluenceAppliedEvent(DomainEvent):
    character_id: str
    source_id: str
    source_type: str
    amount: float
    corruption: float
    mutation_pressure: float


def _room_id(world: World, character_id: EntityId) -> str | None:
    raw = container_of(world.get_entity(character_id))
    return str(raw) if raw is not None else None


def _name(entity: Entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return str(entity.id)


def _void_event(epoch: int, **kwargs) -> dict:
    from datetime import UTC, datetime
    from uuid import uuid4

    base = {"event_id": uuid4().hex, "world_epoch": epoch, "created_at": datetime.now(UTC)}
    base.update(kwargs)
    return base


def _reachable_component(ctx: HandlerContext, character_id: EntityId, target_id, component):
    """Resolve a reachable entity that carries ``component``; return (entity, error)."""
    parsed = parse_entity_id(target_id)
    if parsed is None or not ctx.world.has_entity(parsed):
        return None, "target does not exist"
    character = ctx.entity(character_id)
    if parsed not in reachable_ids(ctx.world, character):
        return None, "target is not reachable"
    entity = ctx.entity(parsed)
    if not entity.has_component(component):
        return None, "target is the wrong kind"
    return entity, None


class OpenAirlockHandler:
    command_type = "open-airlock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        airlock, error = _reachable_component(
            ctx, character_id, command.payload.get("airlock_id"), AirlockComponent
        )
        if airlock is None:
            return rejected(error if error else "target is not an airlock")

        state = airlock.get_component(AirlockComponent)
        if state.state == "open":
            return rejected("airlock is already open")
        replace_component(airlock, replace(state, state="open"))

        events: list[DomainEvent] = [
            AirlockCycledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(airlock.id),),
                    airlock_id=str(airlock.id),
                    state="open",
                )
            )
        ]
        module_id = parse_entity_id(state.module_id)
        if state.exposes_vacuum and module_id is not None and ctx.world.has_entity(module_id):
            module = ctx.entity(module_id)
            if module.has_component(PressurizedComponent):
                pressurized = module.get_component(PressurizedComponent)
                if pressurized.pressure > 0.0:
                    replace_component(module, replace(pressurized, pressure=0.0))
                    events.append(
                        PressureChangedEvent(
                            **ctx.event_base(
                                visibility=EventVisibility.ROOM,
                                actor_id=str(character_id),
                                room_id=str(module_id),
                                target_ids=(str(module_id),),
                                module_id=str(module_id),
                                pressure=0.0,
                            )
                        )
                    )
        return ok(*events)


class CycleAirlockHandler:
    command_type = "cycle-airlock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        airlock, error = _reachable_component(
            ctx, character_id, command.payload.get("airlock_id"), AirlockComponent
        )
        if airlock is None:
            return rejected(error if error else "target is not an airlock")

        state = airlock.get_component(AirlockComponent)
        replace_component(airlock, replace(state, state="sealed"))
        return ok(
            AirlockCycledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(airlock.id),),
                    airlock_id=str(airlock.id),
                    state="cycled",
                )
            )
        )


class SealBulkheadHandler:
    command_type = "seal-bulkhead"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        bulkhead, error = _reachable_component(
            ctx, character_id, command.payload.get("bulkhead_id"), BulkheadComponent
        )
        if bulkhead is None:
            return rejected(error if error else "target is not a bulkhead")

        state = bulkhead.get_component(BulkheadComponent)
        if state.sealed:
            return rejected("bulkhead is already sealed")
        replace_component(bulkhead, replace(state, sealed=True))
        return ok()


class RepairSystemHandler:
    command_type = "repair-system"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        system, error = _reachable_component(
            ctx, character_id, command.payload.get("system_id"), ShipSystemComponent
        )
        if system is None:
            return rejected(error if error else "target is not a ship system")

        state = system.get_component(ShipSystemComponent)
        if state.integrity >= 100.0 and state.online:
            return rejected("system is not damaged")
        replace_component(system, replace(state, integrity=100.0, online=True))
        return ok(
            ShipSystemRepairedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(system.id),),
                    system_id=str(system.id),
                    system_type=state.system_type,
                )
            )
        )


class ReroutePowerHandler:
    command_type = "reroute-power"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        grid, error = _reachable_component(
            ctx, character_id, command.payload.get("grid_id"), PowerGridComponent
        )
        if grid is None:
            return rejected(error if error else "target is not a power grid")
        system, error = _reachable_component(
            ctx, character_id, command.payload.get("system_id"), ShipSystemComponent
        )
        if system is None:
            return rejected(error if error else "target is not a ship system")

        try:
            amount = float(command.payload.get("amount", 0))
        except (TypeError, ValueError):
            return rejected("invalid power amount")
        if amount <= 0.0:
            return rejected("power amount must be positive")
        grid_state = grid.get_component(PowerGridComponent)
        if amount > grid_state.available:
            return rejected("not enough power available")

        replace_component(grid, replace(grid_state, available=grid_state.available - amount))
        system_state = system.get_component(ShipSystemComponent)
        replace_component(system, replace(system_state, online=True))
        return ok(
            PowerReroutedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(system.id),),
                    system_id=str(system.id),
                    amount=amount,
                )
            )
        )


class InspectShipSystemHandler:
    command_type = "inspect-ship-system"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        system, error = _reachable_component(
            ctx, character_id, command.payload.get("system_id"), ShipSystemComponent
        )
        if system is None:
            return rejected(error if error else "target is not a ship system")
        return ok()


class DockHandler:
    command_type = "dock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        station, error = _reachable_component(
            ctx, character_id, command.payload.get("station_id"), StationComponent
        )
        if station is None:
            return rejected(error if error else "target is not a station")
        if _docked(ship, station.id):
            return rejected("ship is already docked here")

        port = str(command.payload.get("port", "main"))
        ship.add_relationship(DockedTo(port=port), station.id)
        return ok(
            DockingCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id), str(station.id)),
                    ship_id=str(ship.id),
                    station_id=str(station.id),
                    docked=True,
                )
            )
        )


class UndockHandler:
    command_type = "undock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        station, error = _reachable_component(
            ctx, character_id, command.payload.get("station_id"), StationComponent
        )
        if station is None:
            return rejected(error if error else "target is not a station")
        if not _docked(ship, station.id):
            return rejected("ship is not docked here")

        ship.remove_relationship(DockedTo, station.id)
        return ok(
            DockingCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id), str(station.id)),
                    ship_id=str(ship.id),
                    station_id=str(station.id),
                    docked=False,
                )
            )
        )


class EvacuateModuleHandler:
    command_type = "evacuate-module"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        module, error = _reachable_component(
            ctx, character_id, command.payload.get("module_id"), HabitatModuleComponent
        )
        if module is None:
            return rejected(error if error else "target is not a habitat module")
        destination_id = parse_entity_id(command.payload.get("destination_id"))
        if destination_id is None or not ctx.world.has_entity(destination_id):
            return rejected("destination does not exist")
        if destination_id == module.id:
            return rejected("destination is the module being evacuated")

        destination = ctx.entity(destination_id)
        evacuees: list[str] = []
        for occupant_id in list(contents(module)):
            occupant = ctx.entity(occupant_id)
            if not occupant.has_component(CharacterComponent):
                continue
            module.remove_relationship(Contains, occupant_id)
            destination.add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), occupant_id
            )
            evacuees.append(str(occupant_id))
        if not evacuees:
            return rejected("no one to evacuate")
        return ok(
            ModuleEvacuatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(destination_id),
                    target_ids=(str(module.id),),
                    module_id=str(module.id),
                    evacuee_ids=tuple(evacuees),
                )
            )
        )


def _docked(ship: Entity, station_id: EntityId) -> bool:
    return any(target_id == station_id for _edge, target_id in ship.get_relationships(DockedTo))


#: Astrogation skill at or above which a pilot avoids a hazardous jump's complications.
_HAZARD_SKILL_THRESHOLD = 3


def _jump_route(origin: Entity, destination_id: EntityId) -> JumpRoute | None:
    for edge, target_id in origin.get_relationships(JumpRoute):
        if target_id == destination_id:
            return edge
    return None


class PlotCourseHandler:
    command_type = "plot-course"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        destination_id = parse_entity_id(command.payload.get("destination_id"))
        if destination_id is None or not ctx.world.has_entity(destination_id):
            return rejected("destination does not exist")
        if not ctx.entity(destination_id).has_component(StarSystemComponent):
            return rejected("destination is not a star system")
        origin_id = container_of(ship)
        if origin_id is None or not ctx.world.has_entity(origin_id):
            return rejected("ship is not in a star system")
        route = _jump_route(ctx.entity(origin_id), destination_id)
        if route is None:
            return rejected("no jump route to destination")

        replace_component(
            ship,
            NavigationRouteComponent(
                destination_id=str(destination_id),
                fuel_cost=route.fuel_cost,
                hazard=route.hazard,
                jump_seconds=route.jump_seconds,
                status="plotted",
            ),
        )
        return ok(
            CoursePlottedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id), str(destination_id)),
                    ship_id=str(ship.id),
                    destination_id=str(destination_id),
                    fuel_cost=route.fuel_cost,
                )
            )
        )


class JumpHandler:
    command_type = "jump"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        if not ship.has_component(NavigationRouteComponent):
            return rejected("no course plotted")
        route = ship.get_component(NavigationRouteComponent)
        if route.status == "jumping":
            return rejected("ship is already jumping")
        if not ship.has_component(JumpDriveComponent) or not ship.get_component(
            JumpDriveComponent
        ).charged:
            return rejected("jump drive is not charged")
        if not ship.has_component(FuelComponent):
            return rejected("ship has no fuel tank")
        fuel = ship.get_component(FuelComponent)
        if fuel.level < route.fuel_cost:
            return rejected("not enough fuel to jump")

        new_fuel = replace(fuel, level=fuel.level - route.fuel_cost)
        replace_component(ship, new_fuel)
        arrive_at = ctx.epoch + int(route.jump_seconds)
        replace_component(ship, replace(route, status="jumping", arrive_at_epoch=arrive_at))

        events: list[DomainEvent] = [
            FuelChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id),),
                    ship_id=str(ship.id),
                    level=new_fuel.level,
                    maximum=new_fuel.maximum,
                )
            ),
            JumpStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id),),
                    ship_id=str(ship.id),
                    destination_id=route.destination_id,
                    arrive_at_epoch=arrive_at,
                )
            ),
        ]
        if route.hazard and route.hazard != "none":
            character = ctx.entity(character_id)
            skill = (
                character.get_component(AstrogationComponent).skill
                if character.has_component(AstrogationComponent)
                else 0
            )
            if skill < _HAZARD_SKILL_THRESHOLD:
                events.append(
                    NavigationHazardEncounteredEvent(
                        **ctx.event_base(
                            visibility=EventVisibility.ROOM,
                            actor_id=str(character_id),
                            room_id=_room_id(ctx.world, character_id),
                            target_ids=(str(ship.id),),
                            ship_id=str(ship.id),
                            hazard=route.hazard,
                        )
                    )
                )
        return ok(*events)


class ScanHandler:
    command_type = "scan"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx, character_id, command.payload.get("ship_id"), SensorComponent
        )
        if ship is None:
            return rejected(error if error else "no sensor to scan with")
        origin_id = container_of(ship)
        if origin_id is None or not ctx.world.has_entity(origin_id):
            return rejected("ship is not in a star system")

        events: list[DomainEvent] = []
        for content_id in contents(ctx.entity(origin_id)):
            signal_entity = ctx.entity(content_id)
            if not signal_entity.has_component(DistressSignalComponent):
                continue
            signal = signal_entity.get_component(DistressSignalComponent)
            if signal.detected:
                continue
            replace_component(signal_entity, replace(signal, detected=True))
            events.append(
                SignalDetectedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(content_id),),
                        signal_id=str(content_id),
                        text=signal.text,
                    )
                )
            )
        if not events:
            return rejected("scan finds nothing")
        return ok(*events)


class AnswerDistressSignalHandler:
    command_type = "answer-distress-signal"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        signal_entity, error = _reachable_component(
            ctx, character_id, command.payload.get("signal_id"), DistressSignalComponent
        )
        if signal_entity is None:
            return rejected(error if error else "target is not a distress signal")
        signal = signal_entity.get_component(DistressSignalComponent)
        if not signal.detected:
            return rejected("signal has not been detected")
        if signal.answered:
            return rejected("signal already answered")
        replace_component(signal_entity, replace(signal, answered=True))
        return ok()


class RefuelHandler:
    command_type = "refuel"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx, character_id, command.payload.get("ship_id"), FuelComponent
        )
        if ship is None:
            return rejected(error if error else "ship has no fuel tank")
        fuel = ship.get_component(FuelComponent)
        if fuel.level >= fuel.maximum:
            return rejected("fuel tank is already full")

        raw_amount = command.payload.get("amount")
        if raw_amount is None:
            new_level = fuel.maximum
        else:
            try:
                new_level = min(fuel.maximum, fuel.level + float(raw_amount))
            except (TypeError, ValueError):
                return rejected("invalid fuel amount")
        replace_component(ship, replace(fuel, level=new_level))
        return ok(
            FuelChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id),),
                    ship_id=str(ship.id),
                    level=new_level,
                    maximum=fuel.maximum,
                )
            )
        )


class EnterOrbitHandler:
    command_type = "enter-orbit"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        body, error = _reachable_component(
            ctx, character_id, command.payload.get("body_id"), OrbitalBodyComponent
        )
        if body is None:
            return rejected(error if error else "target is not an orbital body")

        replace_component(ship, OrbitComponent(body_id=str(body.id), altitude="orbit"))
        return ok(
            OrbitEnteredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id), str(body.id)),
                    ship_id=str(ship.id),
                    body_id=str(body.id),
                )
            )
        )


class LeaveOrbitHandler:
    command_type = "leave-orbit"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        if not ship.has_component(OrbitComponent):
            return rejected("ship is not in orbit")
        ship.remove_component(OrbitComponent)
        return ok()


class LandHandler:
    command_type = "land"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        if not ship.has_component(OrbitComponent):
            return rejected("ship must be in orbit to land")
        orbit = ship.get_component(OrbitComponent)
        if orbit.altitude == "surface":
            return rejected("ship is already landed")
        body_id = parse_entity_id(orbit.body_id)
        if body_id is None or not ctx.world.has_entity(body_id):
            return rejected("orbital body no longer exists")
        body = ctx.entity(body_id)
        if body.has_component(OrbitalBodyComponent) and not body.get_component(
            OrbitalBodyComponent
        ).landable:
            return rejected("body cannot be landed on")

        replace_component(ship, replace(orbit, altitude="surface"))
        return ok(
            LandingCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id), str(body_id)),
                    ship_id=str(ship.id),
                    body_id=str(body_id),
                )
            )
        )


class LaunchHandler:
    command_type = "launch"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        if not ship.has_component(OrbitComponent):
            return rejected("ship is not landed")
        orbit = ship.get_component(OrbitComponent)
        if orbit.altitude != "surface":
            return rejected("ship is not on a surface")
        replace_component(ship, replace(orbit, altitude="orbit"))
        return ok()


class JumpTravelConsequence:
    """Complete in-progress jumps: move the ship to its destination system."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = world.query().with_all([ShipComponent, NavigationRouteComponent])
        for ship in query.execute_entities():
            route = ship.get_component(NavigationRouteComponent)
            if route.status != "jumping" or epoch < route.arrive_at_epoch:
                continue
            destination_id = parse_entity_id(route.destination_id)
            if destination_id is None or not world.has_entity(destination_id):
                continue
            origin_id = container_of(ship)
            if origin_id is not None and world.has_entity(origin_id):
                world.get_entity(origin_id).remove_relationship(Contains, ship.id)
            world.get_entity(destination_id).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), ship.id
            )
            ship.remove_component(NavigationRouteComponent)
            events.append(
                JumpCompletedEvent(
                    **_void_event(
                        epoch,
                        visibility=EventVisibility.ROOM,
                        room_id=str(destination_id),
                        target_ids=(str(ship.id), str(destination_id)),
                        ship_id=str(ship.id),
                        destination_id=str(destination_id),
                    )
                )
            )
        return events


class LifeSupportConsequence:
    """Drain or replenish module oxygen based on life support, and flag failures."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for module in world.query().with_all([OxygenComponent]).execute_entities():
            oxygen = module.get_component(OxygenComponent)
            elapsed = max(0, epoch - oxygen.last_updated_epoch)
            if elapsed <= 0:
                continue
            hours = elapsed / 3600.0
            online = True
            rate = 5.0
            if module.has_component(LifeSupportComponent):
                support = module.get_component(LifeSupportComponent)
                online = support.online
                rate = support.oxygen_per_hour
            if online:
                level = min(oxygen.maximum, oxygen.level + rate * hours)
            else:
                level = max(0.0, oxygen.level - rate * hours)
            failed = level <= 0.0
            replace_component(
                module,
                replace(oxygen, level=level, failed=failed, last_updated_epoch=epoch),
            )
            if failed and not oxygen.failed:
                events.append(
                    LifeSupportFailedEvent(
                        **_void_event(
                            epoch,
                            visibility=EventVisibility.ROOM,
                            room_id=str(module.id),
                            target_ids=(str(module.id),),
                            module_id=str(module.id),
                        )
                    )
                )
        return events


def _reachable_chaos_warding(world: World, character: Entity) -> float:
    protection = 0.0
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(ChaosWardComponent):
            protection += max(0.0, entity.get_component(ChaosWardComponent).protection_per_hour)
        if entity.has_component(RadiationShieldComponent):
            protection += max(0.0, entity.get_component(RadiationShieldComponent).strength) / 100.0
    return protection


def _chaos_targets_for_source(world: World, source_id: EntityId) -> list[Entity]:
    targets: list[Entity] = []
    for character in (
        world.query()
        .with_all([CharacterComponent])
        .with_none([DeadComponent, SuspendedComponent])
        .execute_entities()
    ):
        if source_id in reachable_ids(world, character):
            targets.append(character)
    return targets


def _ship_systems_near_source(world: World, source: Entity) -> list[Entity]:
    parent_id = container_of(source)
    if parent_id is None or not world.has_entity(parent_id):
        return []
    nearby_ids = {parent_id, *contents(world.get_entity(parent_id))}
    return [
        world.get_entity(entity_id)
        for entity_id in nearby_ids
        if world.has_entity(entity_id)
        and world.get_entity(entity_id).has_component(ShipSystemComponent)
    ]


class ChaosInfluenceConsequence:
    """Apply void-sim warp/chaos pressure as barbarian-sim corruption."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for source in world.query().with_all([ChaosInfluenceComponent]).execute_entities():
            influence = source.get_component(ChaosInfluenceComponent)
            elapsed = max(0, epoch - influence.last_updated_epoch)
            replace_component(source, replace(influence, last_updated_epoch=epoch))
            if elapsed <= 0:
                continue
            hours = elapsed / 3600.0

            for character in _chaos_targets_for_source(world, source.id):
                warding = _reachable_chaos_warding(world, character)
                rate = max(0.0, influence.corruption_per_hour - warding)
                amount = rate * hours
                if amount <= 0.0:
                    continue

                current = (
                    character.get_component(CorruptionComponent)
                    if character.has_component(CorruptionComponent)
                    else CorruptionComponent()
                )
                updated_corruption = replace(
                    current,
                    amount=current.amount + amount,
                    last_updated_epoch=epoch,
                )
                replace_component(character, updated_corruption)

                pressure = (
                    character.get_component(ChaosMutationPressureComponent)
                    if character.has_component(ChaosMutationPressureComponent)
                    else ChaosMutationPressureComponent()
                )
                mutation_delta = amount * max(0.0, influence.mutation_pressure_per_corruption)
                replace_component(
                    character,
                    replace(
                        pressure,
                        amount=pressure.amount + mutation_delta,
                        last_updated_epoch=epoch,
                    ),
                )
                events.append(
                    CorruptionGainedEvent(
                        **_void_event(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(character.id),
                            room_id=_room_id(world, character.id),
                            character_id=str(character.id),
                            amount=updated_corruption.amount,
                        )
                    )
                )
                events.append(
                    ChaosInfluenceAppliedEvent(
                        **_void_event(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(character.id),
                            room_id=_room_id(world, character.id),
                            target_ids=(str(character.id), str(source.id)),
                            character_id=str(character.id),
                            source_id=str(source.id),
                            source_type=influence.source_type,
                            amount=amount,
                            corruption=updated_corruption.amount,
                            mutation_pressure=pressure.amount + mutation_delta,
                        )
                    )
                )

            system_damage = max(0.0, influence.system_damage_per_hour) * hours
            if system_damage <= 0.0:
                continue
            for system_entity in _ship_systems_near_source(world, source):
                system = system_entity.get_component(ShipSystemComponent)
                integrity = max(0.0, system.integrity - system_damage)
                online = system.online and integrity > 0.0
                if integrity == system.integrity and online == system.online:
                    continue
                replace_component(
                    system_entity,
                    replace(system, integrity=integrity, online=online),
                )
                events.append(
                    ShipSystemDamagedEvent(
                        **_void_event(
                            epoch,
                            visibility=EventVisibility.ROOM,
                            room_id=str(container_of(system_entity) or source.id),
                            target_ids=(str(system_entity.id), str(source.id)),
                            system_id=str(system_entity.id),
                            system_type=system.system_type,
                            integrity=integrity,
                        )
                    )
                )
        return events


# --- Crew duty shifts (catalogue 8.3) -------------------------------------------------


@dataclass(frozen=True)
class DutyShiftComponent(Component):
    """A watch rotation: a time slot plus the role and tasks it covers."""

    name: str
    start_hour: int = 0
    end_hour: int = 8
    role: str = ""
    tasks: tuple[str, ...] = ()


@dataclass(frozen=True)
class CrewDutyStatusComponent(Component):
    """Cached on/off-duty flag so prompt fragments can read it without the clock."""

    on_duty: bool = False
    last_changed_epoch: int = 0


@dataclass(frozen=True)
class WorksShift(Edge):
    """crew -> duty-shift entity; ``station`` is the post this crew covers."""

    station: str = ""


class CrewShiftAssignedEvent(DomainEvent):
    character_id: str
    shift_id: str
    shift_name: str
    station: str = ""


class CrewShiftRelievedEvent(DomainEvent):
    character_id: str
    shift_id: str
    shift_name: str


class CrewDutyChangedEvent(DomainEvent):
    character_id: str
    shift_id: str
    shift_name: str
    on_duty: bool


def _hour_of_day(epoch: int) -> int:
    return (epoch % SECONDS_PER_DAY) // SECONDS_PER_HOUR


def _shift_covers_hour(shift: DutyShiftComponent, hour: int) -> bool:
    if shift.start_hour == shift.end_hour:
        return True  # a round-the-clock watch
    if shift.start_hour < shift.end_hour:
        return shift.start_hour <= hour < shift.end_hour
    # the watch wraps past midnight, e.g. 22:00 -> 06:00
    return hour >= shift.start_hour or hour < shift.end_hour


class AssignCrewShiftHandler:
    command_type = "assign-crew-shift"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        shift_id = parse_entity_id(command.payload.get("shift_id"))
        if character_id is None or shift_id is None:
            return rejected("invalid crew or shift id")
        if not ctx.world.has_entity(shift_id):
            return rejected("shift does not exist")
        shift_entity = ctx.entity(shift_id)
        if not shift_entity.has_component(DutyShiftComponent):
            return rejected("target is not a duty shift")
        character = ctx.entity(character_id)
        if character.has_relationship(WorksShift, shift_id):
            return rejected("already assigned to this shift")

        station = str(command.payload.get("station", "")).strip()
        character.add_relationship(WorksShift(station=station), shift_id)
        shift = shift_entity.get_component(DutyShiftComponent)
        room_id = container_of(character)
        return ok(
            CrewShiftAssignedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room_id) if room_id is not None else None,
                    target_ids=(str(shift_id),),
                    character_id=str(character_id),
                    shift_id=str(shift_id),
                    shift_name=shift.name,
                    station=station,
                )
            )
        )


class RelieveCrewShiftHandler:
    command_type = "relieve-crew-shift"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        shift_id = parse_entity_id(command.payload.get("shift_id"))
        if character_id is None or shift_id is None:
            return rejected("invalid crew or shift id")
        if not ctx.world.has_entity(shift_id):
            return rejected("shift does not exist")
        character = ctx.entity(character_id)
        if not character.has_relationship(WorksShift, shift_id):
            return rejected("not assigned to this shift")

        character.remove_relationship(WorksShift, shift_id)
        shift_entity = ctx.entity(shift_id)
        shift_name = (
            shift_entity.get_component(DutyShiftComponent).name
            if shift_entity.has_component(DutyShiftComponent)
            else _name(shift_entity)
        )
        room_id = container_of(character)
        return ok(
            CrewShiftRelievedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room_id) if room_id is not None else None,
                    target_ids=(str(shift_id),),
                    character_id=str(character_id),
                    shift_id=str(shift_id),
                    shift_name=shift_name,
                )
            )
        )


class CrewDutyConsequence:
    """Flip crew on and off duty as the ship clock enters and leaves their watch."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        hour = _hour_of_day(epoch)
        query = (
            world.query()
            .with_all([CharacterComponent])
            .with_none([DeadComponent, SuspendedComponent])
        )
        for crew in query.execute_entities():
            shifts = [
                shift_id
                for _edge, shift_id in crew.get_relationships(WorksShift)
                if world.has_entity(shift_id)
            ]
            had_status = crew.has_component(CrewDutyStatusComponent)
            if not shifts and not had_status:
                continue

            on_duty = False
            active_id: EntityId | None = None
            active_name = ""
            for shift_id in shifts:
                shift = world.get_entity(shift_id)
                if shift.has_component(DutyShiftComponent) and _shift_covers_hour(
                    shift.get_component(DutyShiftComponent), hour
                ):
                    on_duty = True
                    active_id = shift_id
                    active_name = shift.get_component(DutyShiftComponent).name
                    break

            prev = crew.get_component(CrewDutyStatusComponent).on_duty if had_status else False
            if had_status and on_duty == prev:
                continue
            replace_component(
                crew,
                CrewDutyStatusComponent(on_duty=on_duty, last_changed_epoch=epoch),
            )
            if on_duty != prev:
                events.append(
                    CrewDutyChangedEvent(
                        **_void_event(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(crew.id),
                            target_ids=(str(active_id),) if active_id is not None else (),
                            character_id=str(crew.id),
                            shift_id=str(active_id) if active_id is not None else "",
                            shift_name=active_name,
                            on_duty=on_duty,
                        )
                    )
                )
        return events


def voidsim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    module_id = container_of(character)
    if module_id is not None and world.has_entity(module_id):
        module = world.get_entity(module_id)
        if module.has_component(HabitatModuleComponent):
            module_type = module.get_component(HabitatModuleComponent).module_type
            lines.append(f"You are in the {module_type} module ({_name(module)}).")
        if module.has_component(PressurizedComponent):
            pressure = module.get_component(PressurizedComponent).pressure
            state = "vacuum" if pressure <= 0.0 else f"{pressure:.1f} atm"
            lines.append(f"Module pressure: {state}.")
        if module.has_component(OxygenComponent):
            oxygen = module.get_component(OxygenComponent)
            lines.append(f"Module oxygen: {oxygen.level:.0f}/{oxygen.maximum:.0f}.")
        if module.has_component(LifeSupportComponent):
            online = module.get_component(LifeSupportComponent).online
            lines.append(f"Life support: {'online' if online else 'OFFLINE'}.")
        if module.has_component(ChaosInfluenceComponent):
            influence = module.get_component(ChaosInfluenceComponent)
            lines.append(
                f"Chaos influence: {influence.source_type} "
                f"({influence.corruption_per_hour:g}/hour)."
            )
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(ChaosInfluenceComponent):
            influence = entity.get_component(ChaosInfluenceComponent)
            lines.append(
                f"Chaos source {_name(entity)}: {influence.source_type} "
                f"({influence.corruption_per_hour:g}/hour)."
            )
        if entity.has_component(ChaosWardComponent):
            ward = entity.get_component(ChaosWardComponent)
            lines.append(f"Chaos ward {_name(entity)}: {ward.protection_per_hour:g}/hour.")
        if entity.has_component(ShipSystemComponent):
            system = entity.get_component(ShipSystemComponent)
            status = "online" if system.online else "offline"
            lines.append(
                f"Ship system {system.system_type}: {system.integrity:.0f}% ({status})."
            )
        if entity.has_component(AirlockComponent):
            airlock = entity.get_component(AirlockComponent)
            lines.append(f"Airlock {_name(entity)}: {airlock.state}.")
        if entity.has_component(PowerGridComponent):
            grid = entity.get_component(PowerGridComponent)
            lines.append(
                f"Power grid: {grid.available:.0f}/{grid.capacity:.0f} available."
            )
        if entity.has_component(ShipComponent):
            for _edge, station_id in entity.get_relationships(DockedTo):
                if world.has_entity(station_id):
                    lines.append(
                        f"{_name(entity)} is docked at {_name(world.get_entity(station_id))}."
                    )
        if entity.has_component(FuelComponent):
            fuel = entity.get_component(FuelComponent)
            lines.append(f"{_name(entity)} fuel: {fuel.level:.0f}/{fuel.maximum:.0f}.")
        if entity.has_component(OrbitComponent):
            orbit = entity.get_component(OrbitComponent)
            where = "landed on" if orbit.altitude == "surface" else "in orbit of"
            body_id = parse_entity_id(orbit.body_id)
            if body_id is not None and world.has_entity(body_id):
                body_name = _name(world.get_entity(body_id))
                lines.append(f"{_name(entity)} is {where} {body_name}.")
        if entity.has_component(NavigationRouteComponent):
            route = entity.get_component(NavigationRouteComponent)
            lines.append(f"{_name(entity)} course: {route.status} (hazard: {route.hazard}).")
        if entity.has_component(DistressSignalComponent):
            signal = entity.get_component(DistressSignalComponent)
            if signal.detected and not signal.answered:
                lines.append(f"Distress signal: {signal.text}")
        if entity.has_component(OrbitalBodyComponent):
            body = entity.get_component(OrbitalBodyComponent)
            lines.append(f"Orbital body nearby: {_name(entity)} ({body.body_type}).")
    if module_id is not None and world.has_entity(module_id):
        current = world.get_entity(module_id)
        if current.has_component(StarSystemComponent):
            lines.append(f"Current system: {current.get_component(StarSystemComponent).name}.")
    if character.has_component(CorruptionComponent):
        corruption = character.get_component(CorruptionComponent)
        lines.append(f"Chaos corruption: {corruption.amount:g}.")
    if character.has_component(ChaosMutationPressureComponent):
        pressure = character.get_component(ChaosMutationPressureComponent)
        if pressure.amount > 0.0:
            lines.append(f"Chaos mutation pressure: {pressure.amount:g}.")
    if character.has_component(RadiationMutationPressureComponent):
        pressure = character.get_component(RadiationMutationPressureComponent)
        if pressure.amount > 0.0:
            lines.append(f"Radiation mutation pressure: {pressure.amount:g}.")
    if character.has_component(CyberneticMutationPressureComponent):
        pressure = character.get_component(CyberneticMutationPressureComponent)
        if pressure.amount > 0.0:
            lines.append(f"Cybernetic mutation pressure: {pressure.amount:g}.")
    for edge, shift_id in character.get_relationships(WorksShift):
        if not world.has_entity(shift_id):
            continue
        shift_entity = world.get_entity(shift_id)
        if shift_entity.has_component(DutyShiftComponent):
            shift = shift_entity.get_component(DutyShiftComponent)
            station = f", station {edge.station}" if edge.station else ""
            lines.append(
                f"Duty shift: {shift.name} watch "
                f"({shift.start_hour:02d}:00-{shift.end_hour:02d}:00) "
                f"as {shift.role or 'crew'}{station}."
            )
    if (
        character.has_component(CrewDutyStatusComponent)
        and character.get_component(CrewDutyStatusComponent).on_duty
    ):
        lines.append("You are currently on duty.")
    return sorted(lines)


def install_voidsim(actor) -> None:
    actor.register_consequence(LifeSupportConsequence())
    actor.register_consequence(JumpTravelConsequence())
    actor.register_consequence(ChaosInfluenceConsequence())
    actor.register_consequence(CrewDutyConsequence())


__all__ = [
    "AirlockComponent",
    "AirlockCycledEvent",
    "AnswerDistressSignalHandler",
    "AssignCrewShiftHandler",
    "AstrogationComponent",
    "BulkheadComponent",
    "ChaosInfluenceAppliedEvent",
    "ChaosInfluenceComponent",
    "ChaosInfluenceConsequence",
    "ChaosMutationPressureComponent",
    "ChaosWardComponent",
    "CoursePlottedEvent",
    "CrewDutyChangedEvent",
    "CrewDutyConsequence",
    "CrewDutyStatusComponent",
    "CrewShiftAssignedEvent",
    "CrewShiftRelievedEvent",
    "CycleAirlockHandler",
    "DistressSignalComponent",
    "DutyShiftComponent",
    "DockHandler",
    "DockedTo",
    "DockingCompletedEvent",
    "EnterOrbitHandler",
    "EvacuateModuleHandler",
    "FuelChangedEvent",
    "FuelComponent",
    "HabitatModuleComponent",
    "InspectShipSystemHandler",
    "JumpCompletedEvent",
    "JumpDriveComponent",
    "JumpHandler",
    "JumpRoute",
    "JumpStartedEvent",
    "JumpTravelConsequence",
    "LandHandler",
    "LandingCompletedEvent",
    "LaunchHandler",
    "LeaveOrbitHandler",
    "LifeSupportComponent",
    "LifeSupportConsequence",
    "LifeSupportFailedEvent",
    "ModuleEvacuatedEvent",
    "CyberneticMutationPressureComponent",
    "NavigationHazardEncounteredEvent",
    "NavigationRouteComponent",
    "OpenAirlockHandler",
    "OrbitComponent",
    "OrbitEnteredEvent",
    "OrbitalBodyComponent",
    "OxygenComponent",
    "PlotCourseHandler",
    "PowerGridComponent",
    "PowerReroutedEvent",
    "PressureChangedEvent",
    "PressurizedComponent",
    "RadiationShieldComponent",
    "RadiationMutationPressureComponent",
    "RefuelHandler",
    "RelieveCrewShiftHandler",
    "RepairSystemHandler",
    "ReroutePowerHandler",
    "ScanHandler",
    "SealBulkheadHandler",
    "SensorComponent",
    "ShipComponent",
    "ShipSystemComponent",
    "ShipSystemDamagedEvent",
    "ShipSystemRepairedEvent",
    "SignalDetectedEvent",
    "StarSystemComponent",
    "StationComponent",
    "UndockHandler",
    "WorksShift",
    "install_voidsim",
    "voidsim_fragments",
]
