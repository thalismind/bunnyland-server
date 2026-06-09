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
    replace_component,
    spawn_entity,
)
from bunnyland.core.components import CharacterComponent
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.core.handlers import HandlerContext
from bunnyland.mechanics.barbariansim import CorruptionComponent, CorruptionGainedEvent
from bunnyland.mechanics.voidsim import (
    AirlockComponent,
    AirlockCycledEvent,
    AnswerDistressSignalHandler,
    AstrogationComponent,
    BulkheadComponent,
    ChaosInfluenceAppliedEvent,
    ChaosInfluenceComponent,
    ChaosInfluenceConsequence,
    ChaosMutationPressureComponent,
    ChaosWardComponent,
    CoursePlottedEvent,
    CyberneticMutationPressureComponent,
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
    RadiationMutationPressureComponent,
    RadiationShieldComponent,
    RefuelHandler,
    RepairSystemHandler,
    ReroutePowerHandler,
    ScanHandler,
    SealBulkheadHandler,
    SensorComponent,
    ShipComponent,
    ShipSystemComponent,
    ShipSystemDamagedEvent,
    ShipSystemRepairedEvent,
    SignalDetectedEvent,
    StarSystemComponent,
    StationComponent,
    UndockHandler,
    install_voidsim,
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
    actor.register_consequence(ChaosInfluenceConsequence())


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


def _handler_cmd(scenario, command_type, *, character_id=None, **payload):
    return build_submitted_command(
        character_id=str(scenario.character) if character_id is None else character_id,
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


async def test_open_airlock_rejects_already_open_airlock():
    scenario = build_scenario()
    _install(scenario.actor)
    airlock_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="port airlock", kind="airlock"),
            AirlockComponent(state="open", exposes_vacuum=True),
        ],
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "open-airlock", airlock_id=str(airlock_id)))
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "airlock is already open" for event in rejects)


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


def test_voidsim_ship_system_handlers_reject_invalid_targets_and_payloads():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    airlock_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="open lock", kind="airlock"),
            AirlockComponent(state="open"),
        ],
    )
    sealed_bulkhead_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="sealed hatch", kind="bulkhead"),
            BulkheadComponent(sealed=True),
        ],
    )
    wrong_kind_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="plain crate", kind="item")],
    )
    distant_airlock = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant lock", kind="airlock"),
            AirlockComponent(state="sealed"),
        ],
    )
    grid_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="main bus", kind="power-grid"),
            PowerGridComponent(available=5.0),
        ],
    )
    system_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="shields", kind="ship-system"),
            ShipSystemComponent(system_type="shields", online=False),
        ],
    )
    ship_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="courier", kind="ship"), ShipComponent(name="courier")],
    )
    station_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="anchor station", kind="station"),
            StationComponent(name="anchor station"),
        ],
    )
    docked_ship_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="docked shuttle", kind="ship"),
            ShipComponent(name="docked shuttle"),
        ],
    )
    docked_ship = scenario.actor.world.get_entity(docked_ship_id)
    docked_ship.add_relationship(DockedTo(port="main"), station_id)
    module_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="crew module", kind="habitat"),
            HabitatModuleComponent(module_type="crew"),
        ],
    )
    cargo_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="cargo pallet", kind="cargo")],
    ).id
    scenario.actor.world.get_entity(module_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), cargo_id
    )

    cases = [
        (
            OpenAirlockHandler(),
            _handler_cmd(
                scenario,
                "open-airlock",
                character_id="not-an-id",
                airlock_id=str(airlock_id),
            ),
            "invalid character id",
        ),
        (
            OpenAirlockHandler(),
            _handler_cmd(scenario, "open-airlock", airlock_id="entity_999"),
            "target does not exist",
        ),
        (
            OpenAirlockHandler(),
            _handler_cmd(scenario, "open-airlock", airlock_id=str(distant_airlock.id)),
            "target is not reachable",
        ),
        (
            OpenAirlockHandler(),
            _handler_cmd(scenario, "open-airlock", airlock_id=str(wrong_kind_id)),
            "target is the wrong kind",
        ),
        (
            OpenAirlockHandler(),
            _handler_cmd(scenario, "open-airlock", airlock_id=str(airlock_id)),
            "airlock is already open",
        ),
        (
            SealBulkheadHandler(),
            _handler_cmd(scenario, "seal-bulkhead", bulkhead_id=str(wrong_kind_id)),
            "target is the wrong kind",
        ),
        (
            SealBulkheadHandler(),
            _handler_cmd(scenario, "seal-bulkhead", bulkhead_id=str(sealed_bulkhead_id)),
            "bulkhead is already sealed",
        ),
        (
            CycleAirlockHandler(),
            _handler_cmd(scenario, "cycle-airlock", airlock_id=str(wrong_kind_id)),
            "target is the wrong kind",
        ),
        (
            RepairSystemHandler(),
            _handler_cmd(scenario, "repair-system", system_id=str(wrong_kind_id)),
            "target is the wrong kind",
        ),
        (
            ReroutePowerHandler(),
            _handler_cmd(
                scenario,
                "reroute-power",
                grid_id=str(wrong_kind_id),
                system_id=str(system_id),
                amount=1,
            ),
            "target is the wrong kind",
        ),
        (
            ReroutePowerHandler(),
            _handler_cmd(
                scenario,
                "reroute-power",
                grid_id=str(grid_id),
                system_id=str(wrong_kind_id),
                amount=1,
            ),
            "target is the wrong kind",
        ),
        (
            ReroutePowerHandler(),
            _handler_cmd(
                scenario,
                "reroute-power",
                grid_id=str(grid_id),
                system_id=str(system_id),
                amount="oops",
            ),
            "invalid power amount",
        ),
        (
            ReroutePowerHandler(),
            _handler_cmd(
                scenario,
                "reroute-power",
                grid_id=str(grid_id),
                system_id=str(system_id),
                amount=0,
            ),
            "power amount must be positive",
        ),
        (
            ReroutePowerHandler(),
            _handler_cmd(
                scenario,
                "reroute-power",
                grid_id=str(grid_id),
                system_id=str(system_id),
                amount=10,
            ),
            "not enough power available",
        ),
        (
            InspectShipSystemHandler(),
            _handler_cmd(scenario, "inspect-ship-system", system_id=str(wrong_kind_id)),
            "target is the wrong kind",
        ),
        (
            DockHandler(),
            _handler_cmd(
                scenario,
                "dock",
                ship_id=str(wrong_kind_id),
                station_id=str(station_id),
            ),
            "target is the wrong kind",
        ),
        (
            DockHandler(),
            _handler_cmd(
                scenario,
                "dock",
                ship_id=str(ship_id),
                station_id=str(wrong_kind_id),
            ),
            "target is the wrong kind",
        ),
        (
            DockHandler(),
            _handler_cmd(
                scenario,
                "dock",
                ship_id=str(docked_ship_id),
                station_id=str(station_id),
            ),
            "ship is already docked here",
        ),
        (
            UndockHandler(),
            _handler_cmd(
                scenario,
                "undock",
                ship_id=str(wrong_kind_id),
                station_id=str(station_id),
            ),
            "target is the wrong kind",
        ),
        (
            UndockHandler(),
            _handler_cmd(
                scenario,
                "undock",
                ship_id=str(ship_id),
                station_id=str(wrong_kind_id),
            ),
            "target is the wrong kind",
        ),
        (
            UndockHandler(),
            _handler_cmd(
                scenario,
                "undock",
                ship_id=str(ship_id),
                station_id=str(station_id),
            ),
            "ship is not docked here",
        ),
        (
            EvacuateModuleHandler(),
            _handler_cmd(scenario, "evacuate-module", module_id=str(wrong_kind_id)),
            "target is the wrong kind",
        ),
        (
            EvacuateModuleHandler(),
            _handler_cmd(
                scenario,
                "evacuate-module",
                module_id=str(module_id),
                destination_id="entity_999",
            ),
            "destination does not exist",
        ),
        (
            EvacuateModuleHandler(),
            _handler_cmd(
                scenario,
                "evacuate-module",
                module_id=str(module_id),
                destination_id=str(module_id),
            ),
            "destination is the module being evacuated",
        ),
        (
            EvacuateModuleHandler(),
            _handler_cmd(
                scenario,
                "evacuate-module",
                module_id=str(module_id),
                destination_id=str(scenario.room_b),
            ),
            "no one to evacuate",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_voidsim_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    cases = [
        (OpenAirlockHandler(), "open-airlock", {"airlock_id": str(scenario.room_a)}),
        (CycleAirlockHandler(), "cycle-airlock", {"airlock_id": str(scenario.room_a)}),
        (SealBulkheadHandler(), "seal-bulkhead", {"bulkhead_id": str(scenario.room_a)}),
        (RepairSystemHandler(), "repair-system", {"system_id": str(scenario.room_a)}),
        (
            ReroutePowerHandler(),
            "reroute-power",
            {
                "grid_id": str(scenario.room_a),
                "system_id": str(scenario.character),
                "amount": 1,
            },
        ),
        (
            InspectShipSystemHandler(),
            "inspect-ship-system",
            {"system_id": str(scenario.room_a)},
        ),
        (
            DockHandler(),
            "dock",
            {"ship_id": str(scenario.room_a), "station_id": str(scenario.room_b)},
        ),
        (UndockHandler(), "undock", {"ship_id": str(scenario.room_a)}),
        (
            EvacuateModuleHandler(),
            "evacuate-module",
            {"module_id": str(scenario.room_a)},
        ),
        (
            PlotCourseHandler(),
            "plot-course",
            {"ship_id": str(scenario.room_a), "destination": "Sol"},
        ),
        (JumpHandler(), "jump", {"ship_id": str(scenario.room_a)}),
        (ScanHandler(), "scan", {"ship_id": str(scenario.room_a)}),
        (
            AnswerDistressSignalHandler(),
            "answer-distress-signal",
            {"signal_id": str(scenario.room_a)},
        ),
        (RefuelHandler(), "refuel", {"ship_id": str(scenario.room_a)}),
        (
            EnterOrbitHandler(),
            "enter-orbit",
            {"ship_id": str(scenario.room_a), "body_id": str(scenario.room_b)},
        ),
        (LeaveOrbitHandler(), "leave-orbit", {"ship_id": str(scenario.room_a)}),
        (
            LandHandler(),
            "land",
            {"ship_id": str(scenario.room_a), "body_id": str(scenario.room_b)},
        ),
        (LaunchHandler(), "launch", {"ship_id": str(scenario.room_a)}),
    ]

    for handler, command_type, payload in cases:
        result = handler.execute(
            ctx,
            _handler_cmd(
                scenario,
                command_type,
                character_id="not-an-id",
                **payload,
            ),
        )
        assert result.ok is False
        assert result.reason == "invalid character id"


def test_voidsim_navigation_orbit_and_signal_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    wrong_kind_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="plain crate", kind="item")],
    )
    ship_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="courier", kind="ship"), ShipComponent(name="courier")],
    )
    inventory_ship_id = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="pocket shuttle", kind="ship"),
            ShipComponent(name="pocket shuttle"),
        ],
    ).id
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), inventory_ship_id
    )
    inventory_sensor_ship_id = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="pocket scanner", kind="ship"),
            ShipComponent(name="pocket scanner"),
            SensorComponent(scan_range=1.0),
        ],
    ).id
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), inventory_sensor_ship_id
    )
    destination_id = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Vega", kind="star-system"),
            StarSystemComponent(name="Vega"),
        ],
    ).id
    body_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="rocky moon", kind="orbital-body"),
            OrbitalBodyComponent(body_type="moon", landable=False),
        ],
    )
    signal_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="weak signal", kind="signal"),
            DistressSignalComponent(text="help", detected=False),
        ],
    )
    answered_signal_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="answered signal", kind="signal"),
            DistressSignalComponent(text="safe", detected=True, answered=True),
        ],
    )
    full_fuel_ship_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="full tanker", kind="ship"),
            ShipComponent(name="full tanker"),
            FuelComponent(level=10.0, maximum=10.0),
        ],
    )
    orbit_ship_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="orbiter", kind="ship"),
            ShipComponent(name="orbiter"),
            OrbitComponent(body_id=str(body_id), altitude="orbit"),
        ],
    )
    landed_ship_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="lander", kind="ship"),
            ShipComponent(name="lander"),
            OrbitComponent(body_id=str(body_id), altitude="surface"),
        ],
    )
    broken_orbit_ship_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="lost orbiter", kind="ship"),
            ShipComponent(name="lost orbiter"),
            OrbitComponent(body_id="entity_999", altitude="orbit"),
        ],
    )

    cases = [
        (
            PlotCourseHandler(),
            _handler_cmd(
                scenario,
                "plot-course",
                ship_id=str(wrong_kind_id),
                destination_id=str(destination_id),
            ),
            "target is the wrong kind",
        ),
        (
            PlotCourseHandler(),
            _handler_cmd(
                scenario,
                "plot-course",
                ship_id=str(ship_id),
                destination_id="entity_999",
            ),
            "destination does not exist",
        ),
        (
            PlotCourseHandler(),
            _handler_cmd(
                scenario,
                "plot-course",
                ship_id=str(ship_id),
                destination_id=str(scenario.room_b),
            ),
            "destination is not a star system",
        ),
        (
            PlotCourseHandler(),
            _handler_cmd(
                scenario,
                "plot-course",
                ship_id=str(inventory_ship_id),
                destination_id=str(destination_id),
            ),
            "no jump route to destination",
        ),
        (
            JumpHandler(),
            _handler_cmd(scenario, "jump", ship_id=str(ship_id)),
            "no course plotted",
        ),
        (
            ScanHandler(),
            _handler_cmd(scenario, "scan", ship_id=str(wrong_kind_id)),
            "target is the wrong kind",
        ),
        (
            ScanHandler(),
            _handler_cmd(scenario, "scan", ship_id=str(inventory_sensor_ship_id)),
            "scan finds nothing",
        ),
        (
            AnswerDistressSignalHandler(),
            _handler_cmd(
                scenario,
                "answer-distress-signal",
                signal_id=str(wrong_kind_id),
            ),
            "target is the wrong kind",
        ),
        (
            AnswerDistressSignalHandler(),
            _handler_cmd(
                scenario,
                "answer-distress-signal",
                signal_id=str(signal_id),
            ),
            "signal has not been detected",
        ),
        (
            AnswerDistressSignalHandler(),
            _handler_cmd(
                scenario,
                "answer-distress-signal",
                signal_id=str(answered_signal_id),
            ),
            "signal already answered",
        ),
        (
            RefuelHandler(),
            _handler_cmd(scenario, "refuel", ship_id=str(wrong_kind_id)),
            "target is the wrong kind",
        ),
        (
            RefuelHandler(),
            _handler_cmd(scenario, "refuel", ship_id=str(full_fuel_ship_id)),
            "fuel tank is already full",
        ),
        (
            RefuelHandler(),
            _handler_cmd(
                scenario,
                "refuel",
                ship_id=str(ship_id),
                amount="oops",
            ),
            "target is the wrong kind",
        ),
        (
            EnterOrbitHandler(),
            _handler_cmd(
                scenario,
                "enter-orbit",
                ship_id=str(wrong_kind_id),
                body_id=str(body_id),
            ),
            "target is the wrong kind",
        ),
        (
            EnterOrbitHandler(),
            _handler_cmd(
                scenario,
                "enter-orbit",
                ship_id=str(ship_id),
                body_id=str(wrong_kind_id),
            ),
            "target is the wrong kind",
        ),
        (
            LeaveOrbitHandler(),
            _handler_cmd(scenario, "leave-orbit", ship_id=str(ship_id)),
            "ship is not in orbit",
        ),
        (
            LandHandler(),
            _handler_cmd(scenario, "land", ship_id=str(ship_id)),
            "ship must be in orbit to land",
        ),
        (
            LandHandler(),
            _handler_cmd(scenario, "land", ship_id=str(landed_ship_id)),
            "ship is already landed",
        ),
        (
            LandHandler(),
            _handler_cmd(scenario, "land", ship_id=str(broken_orbit_ship_id)),
            "orbital body no longer exists",
        ),
        (
            LandHandler(),
            _handler_cmd(scenario, "land", ship_id=str(orbit_ship_id)),
            "body cannot be landed on",
        ),
        (
            LaunchHandler(),
            _handler_cmd(scenario, "launch", ship_id=str(ship_id)),
            "ship is not landed",
        ),
        (
            LaunchHandler(),
            _handler_cmd(scenario, "launch", ship_id=str(orbit_ship_id)),
            "ship is not on a surface",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    result = PlotCourseHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "plot-course",
            ship_id=str(ship_id),
            destination_id=str(destination_id),
        ),
    )
    assert result.ok is False
    assert result.reason == "no jump route to destination"

    routed_ship_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="routed ship", kind="ship"),
            ShipComponent(name="routed ship"),
            NavigationRouteComponent(
                destination_id=str(destination_id),
                fuel_cost=5.0,
                status="jumping",
            ),
        ],
    )
    result = JumpHandler().execute(
        ctx,
        _handler_cmd(scenario, "jump", ship_id=str(routed_ship_id)),
    )
    assert result.ok is False
    assert result.reason == "ship is already jumping"

    replace_component(
        scenario.actor.world.get_entity(routed_ship_id),
        NavigationRouteComponent(destination_id=str(destination_id), fuel_cost=5.0),
    )
    result = JumpHandler().execute(
        ctx,
        _handler_cmd(scenario, "jump", ship_id=str(routed_ship_id)),
    )
    assert result.ok is False
    assert result.reason == "jump drive is not charged"

    scenario.actor.world.get_entity(routed_ship_id).add_component(JumpDriveComponent(charged=True))
    result = JumpHandler().execute(
        ctx,
        _handler_cmd(scenario, "jump", ship_id=str(routed_ship_id)),
    )
    assert result.ok is False
    assert result.reason == "ship has no fuel tank"

    scenario.actor.world.get_entity(routed_ship_id).add_component(
        FuelComponent(level=1.0, maximum=10.0)
    )
    result = JumpHandler().execute(
        ctx,
        _handler_cmd(scenario, "jump", ship_id=str(routed_ship_id)),
    )
    assert result.ok is False
    assert result.reason == "not enough fuel to jump"

    empty_sensor_ship_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="empty scanner", kind="ship"),
            ShipComponent(name="empty scanner"),
            SensorComponent(scan_range=1.0),
        ],
    )
    replace_component(
        scenario.actor.world.get_entity(signal_id),
        DistressSignalComponent(text="help", detected=True),
    )
    result = ScanHandler().execute(
        ctx,
        _handler_cmd(scenario, "scan", ship_id=str(empty_sensor_ship_id)),
    )
    assert result.ok is False
    assert result.reason == "scan finds nothing"

    low_fuel_ship_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="low tanker", kind="ship"),
            ShipComponent(name="low tanker"),
            FuelComponent(level=1.0, maximum=10.0),
        ],
    )
    result = RefuelHandler().execute(
        ctx,
        _handler_cmd(scenario, "refuel", ship_id=str(low_fuel_ship_id), amount="oops"),
    )
    assert result.ok is False
    assert result.reason == "invalid fuel amount"


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
            ShipSystemComponent(system_type="shields"),
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
            ShipSystemComponent(system_type="shields", online=False),
        ],
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "reroute-power", grid_id=str(grid_id), system_id=str(system_id), amount=50)
    )
    await scenario.actor.tick(HOUR)
    assert any(event.reason == "not enough power available" for event in rejects)


async def test_reroute_power_rejects_invalid_power_amount():
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
            ShipSystemComponent(system_type="shields", online=False),
        ],
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "reroute-power",
            grid_id=str(grid_id),
            system_id=str(system_id),
            amount="lots",
        )
    )
    await scenario.actor.tick(HOUR)

    grid = scenario.actor.world.get_entity(grid_id).get_component(PowerGridComponent)
    system = scenario.actor.world.get_entity(system_id).get_component(ShipSystemComponent)
    assert grid.available == 10.0
    assert system.online is False
    assert any(event.reason == "invalid power amount" for event in rejects)


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


async def test_chaos_influence_applies_barbarian_corruption_and_mutation_pressure():
    scenario = build_scenario()
    _install(scenario.actor)
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="warp breach", kind="chaos-source"),
            ChaosInfluenceComponent(
                source_type="warp breach",
                corruption_per_hour=2.0,
                mutation_pressure_per_corruption=0.5,
            ),
        ],
    )
    corruption: list[CorruptionGainedEvent] = []
    influence: list[ChaosInfluenceAppliedEvent] = []
    scenario.actor.bus.subscribe(CorruptionGainedEvent, corruption.append)
    scenario.actor.bus.subscribe(ChaosInfluenceAppliedEvent, influence.append)

    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(CorruptionComponent).amount == 2.0
    pressure = character.get_component(ChaosMutationPressureComponent)
    assert pressure.amount == 1.0
    assert corruption[0].amount == 2.0
    assert influence[0].amount == 2.0
    assert influence[0].corruption == 2.0
    assert influence[0].mutation_pressure == 1.0


async def test_chaos_wards_reduce_corruption_rate_and_radiation_shields_help():
    scenario = build_scenario()
    _install(scenario.actor)
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="gellar shrine", kind="ward"),
            ChaosWardComponent(protection_per_hour=1.0),
        ],
    )
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="radiation baffle", kind="shield"),
            RadiationShieldComponent(strength=50.0),
        ],
    )
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="daemon whisper", kind="chaos-source"),
            ChaosInfluenceComponent(source_type="daemon whisper", corruption_per_hour=2.0),
        ],
    )

    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(CorruptionComponent).amount == 0.5


async def test_chaos_influence_can_damage_nearby_ship_systems():
    scenario = build_scenario()
    _install(scenario.actor)
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="warp-tainted cogitator", kind="chaos-source"),
            ChaosInfluenceComponent(
                source_type="machine possession",
                corruption_per_hour=0.0,
                system_damage_per_hour=3.0,
            ),
        ],
    )
    system_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="void shields", kind="ship-system"),
            ShipSystemComponent(system_type="shields", integrity=10.0),
        ],
    )
    damaged: list[ShipSystemDamagedEvent] = []
    scenario.actor.bus.subscribe(ShipSystemDamagedEvent, damaged.append)

    await scenario.actor.tick(HOUR)

    system = scenario.actor.world.get_entity(system_id).get_component(ShipSystemComponent)
    assert system.integrity == 7.0
    assert system.online is True
    assert damaged[0].system_id == str(system_id)
    assert damaged[0].integrity == 7.0


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


def test_voidsim_fragments_describe_chaos_wards_and_mutation_pressure():
    scenario = build_scenario()
    _make_module(scenario, module_type="sanctum")
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(ChaosInfluenceComponent(source_type="warp scar", corruption_per_hour=2.0))
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="gellar charm", kind="ward"),
            ChaosWardComponent(protection_per_hour=1.0),
        ],
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(CorruptionComponent(amount=3.0))
    character.add_component(ChaosMutationPressureComponent(amount=2.0))
    character.add_component(RadiationMutationPressureComponent(amount=4.0))
    character.add_component(CyberneticMutationPressureComponent(amount=1.0))

    fragments = voidsim_fragments(scenario.actor.world, character)

    assert any("Chaos influence: warp scar" in line for line in fragments)
    assert any("Chaos ward gellar charm: 1/hour" in line for line in fragments)
    assert any("Chaos corruption: 3" in line for line in fragments)
    assert any("Chaos mutation pressure: 2" in line for line in fragments)
    assert any("Radiation mutation pressure: 4" in line for line in fragments)
    assert any("Cybernetic mutation pressure: 1" in line for line in fragments)


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


async def test_scan_rejects_when_all_signals_already_detected():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    ship_id = _ship_in(scenario, scenario.room_a)
    signal = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="old mayday", kind="signal"),
            DistressSignalComponent(text="Already logged.", detected=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), signal.id
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "scan", ship_id=str(ship_id)))
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "scan finds nothing" for event in rejects)


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


async def test_refuel_accepts_partial_amount_and_rejects_full_tank():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    ship_id = _ship_in(scenario, scenario.room_a, fuel=60.0)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "refuel", ship_id=str(ship_id), amount=15))
    await scenario.actor.tick(HOUR)
    assert scenario.actor.world.get_entity(ship_id).get_component(FuelComponent).level == 75.0

    await scenario.actor.submit(_cmd(scenario, "refuel", ship_id=str(ship_id), amount=25))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "refuel", ship_id=str(ship_id), amount=1))
    await scenario.actor.tick(HOUR)

    assert scenario.actor.world.get_entity(ship_id).get_component(FuelComponent).level == 100.0
    assert any(event.reason == "fuel tank is already full" for event in rejects)


async def test_refuel_rejects_invalid_amount():
    scenario = build_scenario()
    _install(scenario.actor)
    _system(scenario, scenario.room_a, "Sol")
    ship_id = _ship_in(scenario, scenario.room_a, fuel=60.0)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "refuel", ship_id=str(ship_id), amount="plenty"))
    await scenario.actor.tick(HOUR)

    assert scenario.actor.world.get_entity(ship_id).get_component(FuelComponent).level == 60.0
    assert any(event.reason == "invalid fuel amount" for event in rejects)


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


def test_voidsim_fragments_describe_navigation_status_and_signals():
    scenario = build_scenario()
    _system(scenario, scenario.room_a, "Sol")
    body = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Verdant III", kind="planet"),
            OrbitalBodyComponent(body_type="planet", landable=True),
        ],
    )
    station = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Moss Station", kind="station"),
            StationComponent(name="Moss Station"),
        ],
    )
    signal = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="mayday", kind="signal"),
            DistressSignalComponent(text="Hull breach.", detected=True),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    for entity_id in (body.id, station.id, signal.id):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity_id)
    ship_id = _ship_in(scenario, scenario.room_a, fuel=42.0)
    ship = scenario.actor.world.get_entity(ship_id)
    ship.add_relationship(DockedTo(), station.id)
    ship.add_component(OrbitComponent(body_id=str(body.id), altitude="orbit"))
    ship.add_component(
        NavigationRouteComponent(destination_id=str(scenario.room_b), hazard="ion storm")
    )

    fragments = voidsim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    assert "Current system: Sol." in fragments
    assert any("Burrow Runner is docked at Moss Station" in line for line in fragments)
    assert any("Burrow Runner fuel: 42/100" in line for line in fragments)
    assert any("Burrow Runner is in orbit of Verdant III" in line for line in fragments)
    assert any("Burrow Runner course: plotted (hazard: ion storm)" in line for line in fragments)
    assert "Distress signal: Hull breach." in fragments
    assert "Orbital body nearby: Verdant III (planet)." in fragments


def test_voidsim_fragments_cover_alternate_and_suppressed_states(monkeypatch):
    scenario = build_scenario()
    _make_module(scenario, module_type="airlock bay", pressure=0.0)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(LifeSupportComponent(online=False))

    body = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Verdant III", kind="planet"),
            OrbitalBodyComponent(body_type="planet"),
        ],
    )
    stale_station = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Lost Station", kind="station"), StationComponent(name="Lost")],
    )
    reachable = [
        [
            IdentityComponent(name="port airlock", kind="airlock"),
            AirlockComponent(state="cycled"),
        ],
        [
            IdentityComponent(name="emergency grid", kind="power-grid"),
            PowerGridComponent(capacity=50.0, available=12.0),
        ],
        [
            IdentityComponent(name="dark reactor", kind="ship-system"),
            ShipSystemComponent(system_type="reactor", integrity=0.0, online=False),
        ],
        [
            IdentityComponent(name="stranded shuttle", kind="ship"),
            ShipComponent(name="stranded shuttle"),
            OrbitComponent(body_id=str(body.id), altitude="surface"),
        ],
        [
            IdentityComponent(name="bad orbit", kind="ship"),
            OrbitComponent(body_id="entity_999999", altitude="orbit"),
        ],
        [
            IdentityComponent(name="answered mayday", kind="signal"),
            DistressSignalComponent(text="Already handled.", detected=True, answered=True),
        ],
        [
            IdentityComponent(name="silent mayday", kind="signal"),
            DistressSignalComponent(text="Not detected.", detected=False),
        ],
    ]
    for components in reachable:
        entity_id = _spawn_in_room_a(scenario, components)
        entity = scenario.actor.world.get_entity(entity_id)
        if entity.has_component(ShipComponent):
            entity.add_relationship(DockedTo(), stale_station.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), body.id)

    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(ChaosMutationPressureComponent(amount=0.0))
    character.add_component(RadiationMutationPressureComponent(amount=0.0))
    character.add_component(CyberneticMutationPressureComponent(amount=0.0))
    original_has_entity = scenario.actor.world.has_entity

    def has_entity(entity_id):
        if entity_id == stale_station.id:
            return False
        return original_has_entity(entity_id)

    monkeypatch.setattr(scenario.actor.world, "has_entity", has_entity)

    fragments = voidsim_fragments(scenario.actor.world, character)

    assert "Module pressure: vacuum." in fragments
    assert "Life support: OFFLINE." in fragments
    assert "Airlock port airlock: cycled." in fragments
    assert "Power grid: 12/50 available." in fragments
    assert "Ship system reactor: 0% (offline)." in fragments
    assert "stranded shuttle is landed on Verdant III." in fragments
    assert not any("docked at" in line for line in fragments)
    assert not any("Distress signal" in line for line in fragments)
    assert not any("mutation pressure" in line for line in fragments)


def test_voidsim_fragments_allow_character_without_container():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains, scenario.character
    )

    assert voidsim_fragments(scenario.actor.world, character) == []


def test_install_voidsim_registers_plugin_consequences():
    scenario = build_scenario()
    before = len(scenario.actor._consequences)

    install_voidsim(scenario.actor)

    registered = {
        type(consequence).__name__ for consequence in scenario.actor._consequences[before:]
    }
    assert registered == {
        "LifeSupportConsequence",
        "JumpTravelConsequence",
        "ChaosInfluenceConsequence",
    }
