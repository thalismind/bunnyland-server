"""Tests for void-sim ships, stations, and habitats (catalogue 8.1)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    build_submitted_command,
    container_of,
    spawn_entity,
)
from bunnyland.core.components import CharacterComponent
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.voidsim import (
    AirlockComponent,
    AirlockCycledEvent,
    BulkheadComponent,
    CycleAirlockHandler,
    DockedTo,
    DockHandler,
    DockingCompletedEvent,
    EvacuateModuleHandler,
    HabitatModuleComponent,
    InspectShipSystemHandler,
    LifeSupportComponent,
    LifeSupportConsequence,
    LifeSupportFailedEvent,
    ModuleEvacuatedEvent,
    OpenAirlockHandler,
    OxygenComponent,
    PowerGridComponent,
    PowerReroutedEvent,
    PressureChangedEvent,
    PressurizedComponent,
    RepairSystemHandler,
    ReroutePowerHandler,
    SealBulkheadHandler,
    ShipComponent,
    ShipSystemComponent,
    ShipSystemRepairedEvent,
    StationComponent,
    UndockHandler,
    voidsim_fragments,
)

HOUR = 60 * 60


def _install(actor):
    actor.register_handler(OpenAirlockHandler())
    actor.register_handler(CycleAirlockHandler())
    actor.register_handler(SealBulkheadHandler())
    actor.register_handler(RepairSystemHandler())
    actor.register_handler(ReroutePowerHandler())
    actor.register_handler(InspectShipSystemHandler())
    actor.register_handler(DockHandler())
    actor.register_handler(UndockHandler())
    actor.register_handler(EvacuateModuleHandler())
    actor.register_consequence(LifeSupportConsequence())


def _cmd(scenario, command_type, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def _spawn_in_room_a(scenario, components):
    entity = spawn_entity(scenario.actor.world, components)
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


def _make_module(scenario, **overrides):
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(HabitatModuleComponent(module_type=overrides.get("module_type", "bridge")))
    room.add_component(PressurizedComponent(pressure=overrides.get("pressure", 1.0)))
    return scenario.room_a


async def test_open_airlock_to_vacuum_decompresses_module():
    scenario = build_scenario()
    _install(scenario.actor)
    _make_module(scenario)
    airlock_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="port airlock", kind="airlock"),
            AirlockComponent(module_id=str(scenario.room_a), exposes_vacuum=True),
        ],
    )
    cycled: list[AirlockCycledEvent] = []
    pressure: list[PressureChangedEvent] = []
    scenario.actor.bus.subscribe(AirlockCycledEvent, cycled.append)
    scenario.actor.bus.subscribe(PressureChangedEvent, pressure.append)

    await scenario.actor.submit(_cmd(scenario, "open-airlock", airlock_id=str(airlock_id)))
    await scenario.actor.tick(HOUR)

    airlock = scenario.actor.world.get_entity(airlock_id).get_component(AirlockComponent)
    module = scenario.actor.world.get_entity(scenario.room_a).get_component(PressurizedComponent)
    assert airlock.state == "open"
    assert module.pressure == 0.0
    assert cycled[0].state == "open"
    assert pressure[0].pressure == 0.0


async def test_cycle_airlock_preserves_pressure():
    scenario = build_scenario()
    _install(scenario.actor)
    _make_module(scenario)
    airlock_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="port airlock", kind="airlock"),
            AirlockComponent(module_id=str(scenario.room_a), exposes_vacuum=True),
        ],
    )
    cycled: list[AirlockCycledEvent] = []
    scenario.actor.bus.subscribe(AirlockCycledEvent, cycled.append)

    await scenario.actor.submit(_cmd(scenario, "cycle-airlock", airlock_id=str(airlock_id)))
    await scenario.actor.tick(HOUR)

    module = scenario.actor.world.get_entity(scenario.room_a).get_component(PressurizedComponent)
    assert module.pressure == 1.0
    assert cycled[0].state == "cycled"


async def test_seal_bulkhead_sets_sealed_and_rejects_resealing():
    scenario = build_scenario()
    _install(scenario.actor)
    bulkhead_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="aft bulkhead", kind="bulkhead"), BulkheadComponent()],
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "seal-bulkhead", bulkhead_id=str(bulkhead_id)))
    await scenario.actor.tick(HOUR)
    assert scenario.actor.world.get_entity(bulkhead_id).get_component(BulkheadComponent).sealed

    await scenario.actor.submit(_cmd(scenario, "seal-bulkhead", bulkhead_id=str(bulkhead_id)))
    await scenario.actor.tick(HOUR)
    assert any(event.reason == "bulkhead is already sealed" for event in rejects)


async def test_repair_system_restores_integrity():
    scenario = build_scenario()
    _install(scenario.actor)
    system_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="life support unit", kind="ship-system"),
            ShipSystemComponent(system_type="life-support", integrity=40.0, online=False),
        ],
    )
    repaired: list[ShipSystemRepairedEvent] = []
    scenario.actor.bus.subscribe(ShipSystemRepairedEvent, repaired.append)

    await scenario.actor.submit(_cmd(scenario, "repair-system", system_id=str(system_id)))
    await scenario.actor.tick(HOUR)

    system = scenario.actor.world.get_entity(system_id).get_component(ShipSystemComponent)
    assert system.integrity == 100.0
    assert system.online is True
    assert repaired[0].system_type == "life-support"


async def test_repair_system_rejects_healthy_system():
    scenario = build_scenario()
    _install(scenario.actor)
    system_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="reactor", kind="ship-system"),
            ShipSystemComponent(system_type="reactor"),
        ],
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "repair-system", system_id=str(system_id)))
    await scenario.actor.tick(HOUR)
    assert any(event.reason == "system is not damaged" for event in rejects)


async def test_reroute_power_brings_system_online():
    scenario = build_scenario()
    _install(scenario.actor)
    grid_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="main bus", kind="power-grid"),
            PowerGridComponent(available=100.0),
        ],
    )
    system_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="shields", kind="ship-system"),
            ShipSystemComponent(system_type="shields", online=False),
        ],
    )
    rerouted: list[PowerReroutedEvent] = []
    scenario.actor.bus.subscribe(PowerReroutedEvent, rerouted.append)

    await scenario.actor.submit(
        _cmd(scenario, "reroute-power", grid_id=str(grid_id), system_id=str(system_id), amount=30)
    )
    await scenario.actor.tick(HOUR)

    grid = scenario.actor.world.get_entity(grid_id).get_component(PowerGridComponent)
    system = scenario.actor.world.get_entity(system_id).get_component(ShipSystemComponent)
    assert grid.available == 70.0
    assert system.online is True
    assert rerouted[0].amount == 30.0


async def test_reroute_power_rejects_insufficient_power():
    scenario = build_scenario()
    _install(scenario.actor)
    grid_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="main bus", kind="power-grid"),
            PowerGridComponent(available=10.0),
        ],
    )
    system_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="shields", kind="ship-system"),
            ShipSystemComponent(system_type="shields"),
        ],
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "reroute-power", grid_id=str(grid_id), system_id=str(system_id), amount=50)
    )
    await scenario.actor.tick(HOUR)
    assert any(event.reason == "not enough power available" for event in rejects)


async def test_dock_then_undock():
    scenario = build_scenario()
    _install(scenario.actor)
    ship_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="Burrow Runner", kind="ship"),
            ShipComponent(name="Burrow Runner"),
        ],
    )
    station_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="Moss Station", kind="station"),
            StationComponent(name="Moss Station"),
        ],
    )
    docking: list[DockingCompletedEvent] = []
    scenario.actor.bus.subscribe(DockingCompletedEvent, docking.append)

    await scenario.actor.submit(
        _cmd(scenario, "dock", ship_id=str(ship_id), station_id=str(station_id))
    )
    await scenario.actor.tick(HOUR)
    ship = scenario.actor.world.get_entity(ship_id)
    assert any(target == station_id for _edge, target in ship.get_relationships(DockedTo))
    assert docking[0].docked is True

    await scenario.actor.submit(
        _cmd(scenario, "undock", ship_id=str(ship_id), station_id=str(station_id))
    )
    await scenario.actor.tick(HOUR)
    ship = scenario.actor.world.get_entity(ship_id)
    assert not list(ship.get_relationships(DockedTo))
    assert docking[1].docked is False


async def test_inspect_ship_system_is_accepted():
    scenario = build_scenario()
    _install(scenario.actor)
    system_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="engines", kind="ship-system"),
            ShipSystemComponent(system_type="engines"),
        ],
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "inspect-ship-system", system_id=str(system_id)))
    await scenario.actor.tick(HOUR)
    assert rejects == []


async def test_evacuate_module_moves_characters_to_destination():
    scenario = build_scenario()
    _install(scenario.actor)
    _make_module(scenario)
    other = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Ensign Clover", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), other.id
    )
    evacuated: list[ModuleEvacuatedEvent] = []
    scenario.actor.bus.subscribe(ModuleEvacuatedEvent, evacuated.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "evacuate-module",
            module_id=str(scenario.room_a),
            destination_id=str(scenario.room_b),
        )
    )
    await scenario.actor.tick(HOUR)

    assert container_of(scenario.actor.world.get_entity(other.id)) == scenario.room_b
    assert str(other.id) in evacuated[0].evacuee_ids


async def test_life_support_offline_drains_oxygen_and_fails():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(OxygenComponent(level=10.0, maximum=100.0))
    room.add_component(LifeSupportComponent(online=False, oxygen_per_hour=100.0))
    failures: list[LifeSupportFailedEvent] = []
    scenario.actor.bus.subscribe(LifeSupportFailedEvent, failures.append)

    await scenario.actor.tick(HOUR)

    oxygen = scenario.actor.world.get_entity(scenario.room_a).get_component(OxygenComponent)
    assert oxygen.level == 0.0
    assert oxygen.failed is True
    assert failures and failures[0].module_id == str(scenario.room_a)


async def test_life_support_online_replenishes_oxygen():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(OxygenComponent(level=50.0, maximum=100.0))
    room.add_component(LifeSupportComponent(online=True, oxygen_per_hour=100.0))

    await scenario.actor.tick(HOUR)

    oxygen = scenario.actor.world.get_entity(scenario.room_a).get_component(OxygenComponent)
    assert oxygen.level > 50.0
    assert oxygen.failed is False


def test_voidsim_fragments_describe_module_and_systems():
    scenario = build_scenario()
    _make_module(scenario, module_type="engineering")
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(OxygenComponent(level=80.0, maximum=100.0))
    room.add_component(LifeSupportComponent(online=True))
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="reactor", kind="ship-system"),
            ShipSystemComponent(system_type="reactor"),
        ],
    )

    character = scenario.actor.world.get_entity(scenario.character)
    fragments = voidsim_fragments(scenario.actor.world, character)

    assert any("engineering module" in line for line in fragments)
    assert any("Module oxygen: 80/100" in line for line in fragments)
    assert any("Ship system reactor" in line for line in fragments)
