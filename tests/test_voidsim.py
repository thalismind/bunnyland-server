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
    AnswerDistressSignalHandler,
    AstrogationComponent,
    BulkheadComponent,
    CoursePlottedEvent,
    CycleAirlockHandler,
    DistressSignalComponent,
    DockedTo,
    DockHandler,
    DockingCompletedEvent,
    EnterOrbitHandler,
    EvacuateModuleHandler,
    FuelChangedEvent,
    FuelComponent,
    HabitatModuleComponent,
    InspectShipSystemHandler,
    JumpCompletedEvent,
    JumpDriveComponent,
    JumpHandler,
    JumpRoute,
    JumpStartedEvent,
    JumpTravelConsequence,
    LandHandler,
    LandingCompletedEvent,
    LaunchHandler,
    LeaveOrbitHandler,
    LifeSupportComponent,
    LifeSupportConsequence,
    LifeSupportFailedEvent,
    ModuleEvacuatedEvent,
    NavigationHazardEncounteredEvent,
    NavigationRouteComponent,
    OpenAirlockHandler,
    OrbitalBodyComponent,
    OrbitComponent,
    OrbitEnteredEvent,
    OxygenComponent,
    PlotCourseHandler,
    PowerGridComponent,
    PowerReroutedEvent,
    PressureChangedEvent,
    PressurizedComponent,
    RefuelHandler,
    RepairSystemHandler,
    ReroutePowerHandler,
    ScanHandler,
    SealBulkheadHandler,
    SensorComponent,
    ShipComponent,
    ShipSystemComponent,
    ShipSystemRepairedEvent,
    SignalDetectedEvent,
    StarSystemComponent,
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
    actor.register_handler(PlotCourseHandler())
    actor.register_handler(JumpHandler())
    actor.register_handler(ScanHandler())
    actor.register_handler(AnswerDistressSignalHandler())
    actor.register_handler(RefuelHandler())
    actor.register_handler(EnterOrbitHandler())
    actor.register_handler(LeaveOrbitHandler())
    actor.register_handler(LandHandler())
    actor.register_handler(LaunchHandler())
    actor.register_consequence(LifeSupportConsequence())
    actor.register_consequence(JumpTravelConsequence())


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


# --- 8.2 Space travel, orbits, and navigation -----------------------------------------


def _system(scenario, room_id, name):
    scenario.actor.world.get_entity(room_id).add_component(StarSystemComponent(name=name))


def _ship_in(scenario, room_id, **fields):
    ship = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=fields.get("name", "Burrow Runner"), kind="ship"),
            ShipComponent(name=fields.get("name", "Burrow Runner")),
            FuelComponent(level=fields.get("fuel", 100.0), maximum=100.0),
            JumpDriveComponent(),
            SensorComponent(),
        ],
    )
    scenario.actor.world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), ship.id
    )
    return ship.id


def _jump_route(scenario, *, fuel_cost=10.0, hazard="none", jump_seconds=1):
    origin = scenario.actor.world.get_entity(scenario.room_a)
    origin.add_relationship(
        JumpRoute(
            fuel_cost=fuel_cost, hazard=hazard, jump_seconds=jump_seconds, label="moss lane"
        ),
        scenario.room_b,
    )


async def test_plot_course_then_jump_completes_travel():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    _system(scenario, scenario.room_b, "Proxima")
    _jump_route(scenario, fuel_cost=10.0, jump_seconds=1)
    ship_id = _ship_in(scenario, scenario.room_a, fuel=100.0)
    plotted: list[CoursePlottedEvent] = []
    started: list[JumpStartedEvent] = []
    completed: list[JumpCompletedEvent] = []
    fuel: list[FuelChangedEvent] = []
    scenario.actor.bus.subscribe(CoursePlottedEvent, plotted.append)
    scenario.actor.bus.subscribe(JumpStartedEvent, started.append)
    scenario.actor.bus.subscribe(JumpCompletedEvent, completed.append)
    scenario.actor.bus.subscribe(FuelChangedEvent, fuel.append)

    await scenario.actor.submit(
        _cmd(scenario, "plot-course", ship_id=str(ship_id), destination_id=str(scenario.room_b))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "jump", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(HOUR)

    ship = scenario.actor.world.get_entity(ship_id)
    assert container_of(ship) == scenario.room_b
    assert not ship.has_component(NavigationRouteComponent)
    assert ship.get_component(FuelComponent).level == 90.0
    assert plotted[0].destination_id == str(scenario.room_b)
    assert started[0].destination_id == str(scenario.room_b)
    assert completed[0].destination_id == str(scenario.room_b)
    assert fuel[0].level == 90.0


async def test_jump_rejected_without_plotted_course():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    ship_id = _ship_in(scenario, scenario.room_a)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "jump", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)
    assert any(event.reason == "no course plotted" for event in rejects)


async def test_jump_rejected_without_enough_fuel():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    _system(scenario, scenario.room_b, "Proxima")
    _jump_route(scenario, fuel_cost=50.0)
    ship_id = _ship_in(scenario, scenario.room_a, fuel=10.0)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "plot-course", ship_id=str(ship_id), destination_id=str(scenario.room_b))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "jump", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)
    assert any(event.reason == "not enough fuel to jump" for event in rejects)


async def test_hazardous_jump_warns_unskilled_pilot_only():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    _system(scenario, scenario.room_b, "Proxima")
    _jump_route(scenario, hazard="ion storm")
    ship_id = _ship_in(scenario, scenario.room_a)
    hazards: list[NavigationHazardEncounteredEvent] = []
    scenario.actor.bus.subscribe(NavigationHazardEncounteredEvent, hazards.append)

    await scenario.actor.submit(
        _cmd(scenario, "plot-course", ship_id=str(ship_id), destination_id=str(scenario.room_b))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "jump", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)
    assert hazards and hazards[0].hazard == "ion storm"


async def test_skilled_pilot_avoids_hazard_warning():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    _system(scenario, scenario.room_b, "Proxima")
    _jump_route(scenario, hazard="ion storm")
    ship_id = _ship_in(scenario, scenario.room_a)
    scenario.actor.world.get_entity(scenario.character).add_component(AstrogationComponent(skill=5))
    hazards: list[NavigationHazardEncounteredEvent] = []
    scenario.actor.bus.subscribe(NavigationHazardEncounteredEvent, hazards.append)

    await scenario.actor.submit(
        _cmd(scenario, "plot-course", ship_id=str(ship_id), destination_id=str(scenario.room_b))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "jump", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)
    assert hazards == []


async def test_scan_detects_then_answer_distress_signal():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    ship_id = _ship_in(scenario, scenario.room_a)
    signal = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="mayday beacon", kind="signal"),
            DistressSignalComponent(text="Hull breach, send aid."),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), signal.id
    )
    detected: list[SignalDetectedEvent] = []
    scenario.actor.bus.subscribe(SignalDetectedEvent, detected.append)

    await scenario.actor.submit(_cmd(scenario, "scan", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)
    assert detected and detected[0].signal_id == str(signal.id)
    scanned = scenario.actor.world.get_entity(signal.id).get_component(DistressSignalComponent)
    assert scanned.detected

    await scenario.actor.submit(
        _cmd(scenario, "answer-distress-signal", signal_id=str(signal.id))
    )
    await scenario.actor.tick(HOUR)
    answered = scenario.actor.world.get_entity(signal.id).get_component(DistressSignalComponent)
    assert answered.answered is True


async def test_refuel_fills_tank():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    ship_id = _ship_in(scenario, scenario.room_a, fuel=20.0)
    fuel: list[FuelChangedEvent] = []
    scenario.actor.bus.subscribe(FuelChangedEvent, fuel.append)

    await scenario.actor.submit(_cmd(scenario, "refuel", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)
    assert scenario.actor.world.get_entity(ship_id).get_component(FuelComponent).level == 100.0
    assert fuel[0].level == 100.0


async def test_enter_orbit_land_launch_and_leave():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    ship_id = _ship_in(scenario, scenario.room_a)
    body = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Verdant III", kind="planet"),
            OrbitalBodyComponent(body_type="planet", landable=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), body.id
    )
    orbited: list[OrbitEnteredEvent] = []
    landed: list[LandingCompletedEvent] = []
    scenario.actor.bus.subscribe(OrbitEnteredEvent, orbited.append)
    scenario.actor.bus.subscribe(LandingCompletedEvent, landed.append)

    await scenario.actor.submit(
        _cmd(scenario, "enter-orbit", ship_id=str(ship_id), body_id=str(body.id))
    )
    await scenario.actor.tick(HOUR)
    ship = scenario.actor.world.get_entity(ship_id)
    assert ship.get_component(OrbitComponent).altitude == "orbit"
    assert orbited[0].body_id == str(body.id)

    await scenario.actor.submit(_cmd(scenario, "land", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)
    orbit = scenario.actor.world.get_entity(ship_id).get_component(OrbitComponent)
    assert orbit.altitude == "surface"
    assert landed[0].body_id == str(body.id)

    await scenario.actor.submit(_cmd(scenario, "launch", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)
    orbit = scenario.actor.world.get_entity(ship_id).get_component(OrbitComponent)
    assert orbit.altitude == "orbit"

    await scenario.actor.submit(_cmd(scenario, "leave-orbit", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)
    assert not scenario.actor.world.get_entity(ship_id).has_component(OrbitComponent)


async def test_land_rejected_when_not_in_orbit():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    ship_id = _ship_in(scenario, scenario.room_a)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "land", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)
    assert any(event.reason == "ship must be in orbit to land" for event in rejects)
