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
from ..core.components import CharacterComponent, IdentityComponent
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
class DockedTo(Edge):
    port: str = "main"


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
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
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
    return sorted(lines)


def install_voidsim(actor) -> None:
    actor.register_consequence(LifeSupportConsequence())


__all__ = [
    "AirlockComponent",
    "AirlockCycledEvent",
    "BulkheadComponent",
    "CycleAirlockHandler",
    "DockHandler",
    "DockedTo",
    "DockingCompletedEvent",
    "EvacuateModuleHandler",
    "HabitatModuleComponent",
    "InspectShipSystemHandler",
    "LifeSupportComponent",
    "LifeSupportConsequence",
    "LifeSupportFailedEvent",
    "ModuleEvacuatedEvent",
    "OpenAirlockHandler",
    "OxygenComponent",
    "PowerGridComponent",
    "PowerReroutedEvent",
    "PressureChangedEvent",
    "PressurizedComponent",
    "RadiationShieldComponent",
    "RepairSystemHandler",
    "ReroutePowerHandler",
    "SealBulkheadHandler",
    "ShipComponent",
    "ShipSystemComponent",
    "ShipSystemDamagedEvent",
    "ShipSystemRepairedEvent",
    "StationComponent",
    "UndockHandler",
    "install_voidsim",
    "voidsim_fragments",
]
