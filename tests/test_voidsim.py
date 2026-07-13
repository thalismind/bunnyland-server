"""Tests for void-sim ships, stations, and habitats (catalogue 8.1)."""

from __future__ import annotations

from conftest import build_scenario, execute_handler

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    MutationPlan,
    build_submitted_command,
    container_of,
    execute_mutation_plan,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.components import CharacterComponent
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.core.handlers import HandlerContext
from bunnyland.prompts import ComponentPromptContext, PromptPerspective
from bunnyland.simpacks.barbariansim.mechanics import CorruptionComponent, CorruptionGainedEvent
from bunnyland.simpacks.colonysim.mechanics import ResourceStackComponent, TechUnlockComponent
from bunnyland.simpacks.voidsim.mechanics import (
    AcceptContractHandler,
    AcceptTradeProtocolHandler,
    AdjustGravityHandler,
    AirlockComponent,
    AirlockCycledEvent,
    AlienArtifactComponent,
    AlienArtifactStudiedEvent,
    AlienSpeciesComponent,
    AnswerDistressSignalHandler,
    AssignCrewShiftHandler,
    AstrogationComponent,
    AttemptTranslationHandler,
    AwayTeamComponent,
    AwayTeamDeployedEvent,
    BlueprintComponent,
    BoardingRepelledEvent,
    BoardingThreatComponent,
    BoostMoraleHandler,
    BulkheadComponent,
    CargoComponent,
    CargoDeliveredEvent,
    CargoLoadedEvent,
    ChaosInfluenceAppliedEvent,
    ChaosInfluenceComponent,
    ChaosInfluenceConsequence,
    ChaosMutationPressureComponent,
    ChaosWardComponent,
    ClaimInsuranceHandler,
    ClaimSalvageHandler,
    CommandDroneHandler,
    ContractAcceptedEvent,
    ContractCompletedEvent,
    ContractComponent,
    CoursePlottedEvent,
    CrewDutyChangedEvent,
    CrewDutyConsequence,
    CrewDutyStatusComponent,
    CrewShiftAssignedEvent,
    CrewShiftRelievedEvent,
    CustomsHoldComponent,
    CustomsInspectedEvent,
    CyberneticMutationPressureComponent,
    CycleAirlockHandler,
    DataSalvageComponent,
    DataSalvagedEvent,
    DeliverCargoHandler,
    DeliverPassengerHandler,
    DeployAwayTeamHandler,
    DiplomacyChangedEvent,
    DiplomaticMissionComponent,
    DistressSignalComponent,
    DockedTo,
    DockHandler,
    DockingCompletedEvent,
    DroneCommandedEvent,
    DroneComponent,
    DutyShiftComponent,
    EmergencyComponent,
    EmergencyResolvedEvent,
    EnterOrbitHandler,
    EvacuateModuleHandler,
    FabricateHandler,
    FabricatorComponent,
    FirstContactComponent,
    FirstContactEvent,
    FuelChangedEvent,
    FuelComponent,
    GravityAdjustedEvent,
    GravityComponent,
    HabitatModuleComponent,
    HackShipAIHandler,
    InitiateContactHandler,
    InspectCustomsHandler,
    InspectShipSystemHandler,
    InstallUpgradeHandler,
    InsuranceClaimedEvent,
    InsurancePolicyComponent,
    ItemFabricatedEvent,
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
    LoadCargoHandler,
    MineAsteroidHandler,
    MiningCompletedEvent,
    MiningSiteComponent,
    ModuleEvacuatedEvent,
    MoraleChangedEvent,
    MoraleComponent,
    MortgageComponent,
    MortgagePaidEvent,
    MutinyComponent,
    MutinyStartedEvent,
    NavigationHazardEncounteredEvent,
    NavigationRouteComponent,
    NegotiateAlienHandler,
    OpenAirlockHandler,
    OrbitalBodyComponent,
    OrbitComponent,
    OrbitEnteredEvent,
    OxygenComponent,
    PassengerComponent,
    PassengerDeliveredEvent,
    PayMortgageHandler,
    PlotCourseHandler,
    PowerGridComponent,
    PowerReroutedEvent,
    PressureChangedEvent,
    PressurizedComponent,
    QuarantineComponent,
    QuarantineSampleHandler,
    QuarantineStartedEvent,
    RadiationMutationPressureComponent,
    RadiationShieldComponent,
    ReactorComponent,
    ReactorStabilizedEvent,
    RefuelHandler,
    RelieveCrewShiftHandler,
    RepairSystemHandler,
    RepelBoardersHandler,
    ReroutePowerHandler,
    ResolveEmergencyHandler,
    SalvageClaimComponent,
    SalvageClaimedEvent,
    SalvageDataHandler,
    ScanHandler,
    SealBulkheadHandler,
    SearchSmugglingCompartmentHandler,
    SensorComponent,
    ShipAIComponent,
    ShipAIHackedEvent,
    ShipComponent,
    ShipSystemComponent,
    ShipSystemDamagedEvent,
    ShipSystemInspectedEvent,
    ShipSystemRepairedEvent,
    ShipUpgradeComponent,
    SignalDetectedEvent,
    SmugglingCompartmentComponent,
    SmugglingCompartmentSearchedEvent,
    StabilizeReactorHandler,
    StarSystemComponent,
    StartMutinyHandler,
    StationComponent,
    StudyAlienArtifactHandler,
    StudyXenobiologyHandler,
    SurveyCompletedEvent,
    SurveySiteComponent,
    SurveySiteHandler,
    TradeProtocolAcceptedEvent,
    TradeProtocolComponent,
    TranslationMatrixComponent,
    TranslationProgressedEvent,
    UndockHandler,
    UpgradeInstalledEvent,
    WorksShift,
    XenobiologySampleComponent,
    XenobiologyStudiedEvent,
    _spend_inventory_resource_operations,
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
    actor.register_handler(AssignCrewShiftHandler())
    actor.register_handler(RelieveCrewShiftHandler())
    actor.register_handler(FabricateHandler())
    actor.register_handler(InstallUpgradeHandler())
    actor.register_handler(AcceptContractHandler())
    actor.register_handler(LoadCargoHandler())
    actor.register_handler(DeliverCargoHandler())
    actor.register_handler(ClaimSalvageHandler())
    actor.register_handler(InitiateContactHandler())
    actor.register_handler(AttemptTranslationHandler())
    actor.register_handler(QuarantineSampleHandler())
    actor.register_handler(NegotiateAlienHandler())
    actor.register_handler(StudyAlienArtifactHandler())
    actor.register_consequence(LifeSupportConsequence())
    actor.register_consequence(JumpTravelConsequence())
    actor.register_consequence(ChaosInfluenceConsequence())
    actor.register_consequence(CrewDutyConsequence())


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


def test_voidsim_reachable_component_rejects_missing_character():
    scenario = build_scenario()
    result = execute_handler(
        OpenAirlockHandler(),
        HandlerContext(scenario.actor.world, scenario.actor.epoch),
        _handler_cmd(
            scenario,
            "open-airlock",
            character_id="entity_999999",
            airlock_id=str(scenario.room_a),
        ),
    )

    assert not result.ok
    assert result.reason == "character does not exist"


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


def test_voidsim_parity_handlers_mutate_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)

    def entity(entity_id):
        return scenario.actor.world.get_entity(entity_id)

    team_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="survey team", kind="team"), AwayTeamComponent()],
    )
    drone_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="repair drone", kind="drone"), DroneComponent()],
    )
    ai_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="ship mind", kind="ai"), ShipAIComponent(trust=1)],
    )
    data_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="black box", kind="data"), DataSalvageComponent()],
    )
    sample_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="glowing spore", kind="sample"),
            XenobiologySampleComponent(contamination=0.5),
        ],
    )
    protocol_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="trade code", kind="protocol"), TradeProtocolComponent()],
    )
    emergency_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="decompression", kind="emergency"), EmergencyComponent()],
    )
    reactor_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="main reactor", kind="reactor"),
            ReactorComponent(stability=40, online=False),
        ],
    )
    gravity_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="hab gravity", kind="gravity"), GravityComponent()],
    )
    threat_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="boarding party", kind="threat"),
            BoardingThreatComponent(threat_level=3),
        ],
    )
    passenger_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="scientist", kind="passenger"), PassengerComponent()],
    )
    survey_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="ice ridge", kind="survey"), SurveySiteComponent(resource="ice")],
    )
    mining_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="nickel rock", kind="mine"), MiningSiteComponent(remaining=5)],
    )
    hold_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="cargo hold", kind="hold"), CustomsHoldComponent()],
    )
    compartment_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="false panel", kind="compartment"),
            SmugglingCompartmentComponent(),
        ],
    )
    policy_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="hull policy", kind="policy"), InsurancePolicyComponent()],
    )
    mortgage_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="ship lien", kind="mortgage"),
            MortgageComponent(principal=100, balance=100),
        ],
    )

    calls = [
        (
            DeployAwayTeamHandler(),
            "deploy-away-team",
            {"team_id": str(team_id)},
            AwayTeamDeployedEvent,
        ),
        (BoostMoraleHandler(), "boost-morale", {"amount": 2}, MoraleChangedEvent),
        (StartMutinyHandler(), "start-mutiny", {}, MutinyStartedEvent),
        (
            CommandDroneHandler(),
            "command",
            {"target_id": str(drone_id), "instruction": "patch"},
            DroneCommandedEvent,
        ),
        (HackShipAIHandler(), "hack-ship-ai", {"ai_id": str(ai_id)}, ShipAIHackedEvent),
        (SalvageDataHandler(), "salvage-data", {"data_id": str(data_id)}, DataSalvagedEvent),
        (
            StudyXenobiologyHandler(),
            "study-xenobiology",
            {"sample_id": str(sample_id)},
            XenobiologyStudiedEvent,
        ),
        (
            AcceptTradeProtocolHandler(),
            "accept-trade-protocol",
            {"protocol_id": str(protocol_id)},
            TradeProtocolAcceptedEvent,
        ),
        (
            ResolveEmergencyHandler(),
            "resolve-emergency",
            {"emergency_id": str(emergency_id)},
            EmergencyResolvedEvent,
        ),
        (
            StabilizeReactorHandler(),
            "stabilize-reactor",
            {"reactor_id": str(reactor_id), "amount": 10},
            ReactorStabilizedEvent,
        ),
        (
            AdjustGravityHandler(),
            "adjust-gravity",
            {"gravity_id": str(gravity_id), "enabled": False, "strength": 0.5},
            GravityAdjustedEvent,
        ),
        (
            RepelBoardersHandler(),
            "repel-boarders",
            {"threat_id": str(threat_id)},
            BoardingRepelledEvent,
        ),
        (
            DeliverPassengerHandler(),
            "deliver-passenger",
            {"passenger_id": str(passenger_id)},
            PassengerDeliveredEvent,
        ),
        (SurveySiteHandler(), "survey-site", {"site_id": str(survey_id)}, SurveyCompletedEvent),
        (
            MineAsteroidHandler(),
            "mine-asteroid",
            {"site_id": str(mining_id), "quantity": 3},
            MiningCompletedEvent,
        ),
        (
            InspectCustomsHandler(),
            "inspect",
            {"hold_id": str(hold_id), "contraband_found": True},
            CustomsInspectedEvent,
        ),
        (
            SearchSmugglingCompartmentHandler(),
            "search-smuggling-compartment",
            {"compartment_id": str(compartment_id)},
            SmugglingCompartmentSearchedEvent,
        ),
        (
            ClaimInsuranceHandler(),
            "claim-insurance",
            {"policy_id": str(policy_id)},
            InsuranceClaimedEvent,
        ),
        (
            PayMortgageHandler(),
            "pay-mortgage",
            {"mortgage_id": str(mortgage_id), "amount": 40},
            MortgagePaidEvent,
        ),
    ]

    for handler, command_type, payload, event_type in calls:
        result = execute_handler(handler, ctx, _handler_cmd(scenario, command_type, **payload))
        assert result.ok, (command_type, result.reason)
        assert any(isinstance(event, event_type) for event in result.events)

    assert entity(team_id).get_component(AwayTeamComponent).deployed is True
    assert character.get_component(MoraleComponent).value == 2
    assert character.get_component(MutinyComponent).active is True
    assert entity(drone_id).get_component(DroneComponent).assigned_task == "patch"
    assert entity(ai_id).get_component(ShipAIComponent).hacked is True
    assert entity(data_id).get_component(DataSalvageComponent).encrypted is False
    assert (
        str(scenario.character)
        in entity(sample_id).get_component(XenobiologySampleComponent).studied_by
    )
    assert entity(protocol_id).get_component(TradeProtocolComponent).accepted is True
    assert entity(emergency_id).get_component(EmergencyComponent).resolved is True
    assert entity(reactor_id).get_component(ReactorComponent).stability == 50
    assert entity(gravity_id).get_component(GravityComponent).enabled is False
    assert entity(threat_id).get_component(BoardingThreatComponent).repelled is True
    assert entity(passenger_id).get_component(PassengerComponent).delivered is True
    assert (
        str(scenario.character) in entity(survey_id).get_component(SurveySiteComponent).surveyed_by
    )
    assert entity(mining_id).get_component(MiningSiteComponent).remaining == 2
    assert entity(hold_id).get_component(CustomsHoldComponent).contraband_found is True
    assert entity(compartment_id).get_component(SmugglingCompartmentComponent).discovered is True
    assert entity(policy_id).get_component(InsurancePolicyComponent).claimed is True
    assert entity(mortgage_id).get_component(MortgageComponent).balance == 60
    fragments = voidsim_fragments(scenario.actor.world, character)
    assert "Away team survey team: survey, deployed." in fragments
    assert "Drone repair drone: active patch." in fragments
    assert "Ship AI ship AI: trust 2, hacked." in fragments
    assert "Data salvage black box: logs, recovered." in fragments
    assert "Trade protocol trade code: accepted, cautious exchange." in fragments
    assert "Emergency decompression: decompression, resolved." in fragments
    assert "Reactor main reactor: stability 50." in fragments
    assert "Customs hold cargo hold: inspected." in fragments
    assert "Mortgage ship lien: balance 60." in fragments


def test_voidsim_parity_handlers_reject_invalid_targets_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    fake = "entity_999999"
    cases = [
        (DeployAwayTeamHandler(), "deploy-away-team", {"team_id": fake}),
        (CommandDroneHandler(), "command", {"target_id": fake}),
        (HackShipAIHandler(), "hack-ship-ai", {"ai_id": fake}),
        (SalvageDataHandler(), "salvage-data", {"data_id": fake}),
        (StudyXenobiologyHandler(), "study-xenobiology", {"sample_id": fake}),
        (AcceptTradeProtocolHandler(), "accept-trade-protocol", {"protocol_id": fake}),
        (ResolveEmergencyHandler(), "resolve-emergency", {"emergency_id": fake}),
        (StabilizeReactorHandler(), "stabilize-reactor", {"reactor_id": fake}),
        (AdjustGravityHandler(), "adjust-gravity", {"gravity_id": fake}),
        (RepelBoardersHandler(), "repel-boarders", {"threat_id": fake}),
        (DeliverPassengerHandler(), "deliver-passenger", {"passenger_id": fake}),
        (SurveySiteHandler(), "survey-site", {"site_id": fake}),
        (MineAsteroidHandler(), "mine-asteroid", {"site_id": fake}),
        (InspectCustomsHandler(), "inspect", {"hold_id": fake}),
        (
            SearchSmugglingCompartmentHandler(),
            "search-smuggling-compartment",
            {"compartment_id": fake},
        ),
        (ClaimInsuranceHandler(), "claim-insurance", {"policy_id": fake}),
        (PayMortgageHandler(), "pay-mortgage", {"mortgage_id": fake, "amount": 1}),
    ]

    for handler, command_type, payload in cases:
        bad_character = execute_handler(
            handler,
            ctx,
            _handler_cmd(scenario, command_type, character_id="not-an-id", **payload),
        )
        assert bad_character.ok is False
        assert bad_character.reason == "invalid character id"
        missing_target = execute_handler(
            handler, ctx, _handler_cmd(scenario, command_type, **payload)
        )
        assert missing_target.ok is False
        assert missing_target.reason == "target does not exist"

    character_only_cases = [
        (BoostMoraleHandler(), "boost-morale", {"amount": 1}),
        (StartMutinyHandler(), "start-mutiny", {}),
    ]
    for handler, command_type, payload in character_only_cases:
        result = execute_handler(
            handler,
            ctx,
            _handler_cmd(scenario, command_type, character_id="not-an-id", **payload),
        )
        assert result.ok is False
        assert result.reason == "invalid character id"


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


def test_open_airlock_covers_non_decompression_branches():
    scenario = build_scenario()
    _install(scenario.actor)
    _make_module(scenario, pressure=0.0)
    scenario.actor.world.get_entity(scenario.room_b).add_component(
        HabitatModuleComponent(module_type="cargo")
    )
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)

    airlocks = [
        AirlockComponent(module_id=str(scenario.room_a), exposes_vacuum=False),
        AirlockComponent(module_id="not-an-entity", exposes_vacuum=True),
        AirlockComponent(module_id=str(scenario.room_b), exposes_vacuum=True),
        AirlockComponent(module_id=str(scenario.room_a), exposes_vacuum=True),
    ]

    for state in airlocks:
        airlock = spawn_entity(
            scenario.actor.world,
            [IdentityComponent(name="test airlock", kind="airlock"), state],
        )
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), airlock.id)

        result = execute_handler(
            OpenAirlockHandler(),
            ctx,
            _handler_cmd(scenario, "open-airlock", airlock_id=str(airlock.id)),
        )

        assert result.ok is True
        assert [type(event) for event in result.events] == [AirlockCycledEvent]


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
            _handler_cmd(scenario, "inspect", system_id=str(wrong_kind_id)),
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
        result = execute_handler(handler, ctx, command)
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
            "inspect",
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
        result = execute_handler(
            handler,
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
        result = execute_handler(handler, ctx, command)
        assert result.ok is False
        assert result.reason == reason

    result = execute_handler(
        PlotCourseHandler(),
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
    result = execute_handler(
        JumpHandler(),
        ctx,
        _handler_cmd(scenario, "jump", ship_id=str(routed_ship_id)),
    )
    assert result.ok is False
    assert result.reason == "ship is already jumping"

    replace_component(
        scenario.actor.world.get_entity(routed_ship_id),
        NavigationRouteComponent(destination_id=str(destination_id), fuel_cost=5.0),
    )
    result = execute_handler(
        JumpHandler(),
        ctx,
        _handler_cmd(scenario, "jump", ship_id=str(routed_ship_id)),
    )
    assert result.ok is False
    assert result.reason == "jump drive is not charged"

    scenario.actor.world.get_entity(routed_ship_id).add_component(JumpDriveComponent(charged=True))
    result = execute_handler(
        JumpHandler(),
        ctx,
        _handler_cmd(scenario, "jump", ship_id=str(routed_ship_id)),
    )
    assert result.ok is False
    assert result.reason == "ship has no fuel tank"

    scenario.actor.world.get_entity(routed_ship_id).add_component(
        FuelComponent(level=1.0, maximum=10.0)
    )
    result = execute_handler(
        JumpHandler(),
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
    result = execute_handler(
        ScanHandler(),
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
    result = execute_handler(
        RefuelHandler(),
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
    inspected: list[ShipSystemInspectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)
    scenario.actor.bus.subscribe(ShipSystemInspectedEvent, inspected.append)

    await scenario.actor.submit(_cmd(scenario, "inspect", system_id=str(system_id)))
    await scenario.actor.tick(HOUR)
    assert rejects == []
    assert inspected and inspected[0].system_type == "engines"


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


def test_life_support_consequence_skips_zero_elapsed_and_uses_default_generation():
    scenario = build_scenario()
    skipped = spawn_entity(
        scenario.actor.world,
        [OxygenComponent(level=10.0, maximum=100.0, last_updated_epoch=HOUR)],
    )
    generated = spawn_entity(
        scenario.actor.world,
        [OxygenComponent(level=10.0, maximum=100.0, last_updated_epoch=0)],
    )

    assert LifeSupportConsequence().process(scenario.actor.world, HOUR) == []

    assert skipped.get_component(OxygenComponent).level == 10.0
    assert generated.get_component(OxygenComponent).level == 15.0


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


def test_voidsim_component_prompt_fragments_cover_module_and_target_state():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    room = world.get_entity(scenario.room_a)
    room.add_component(HabitatModuleComponent(module_type="engineering"))
    contract_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="survey charter", kind="contract"),
            ContractComponent(contract_type="survey", reward=40),
        ],
    )
    artifact_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="alien idol", kind="artifact"),
            AlienArtifactComponent(studied_by=(str(character.id),)),
        ],
    )

    room_ctx = ComponentPromptContext.for_entity(world, room, room=room)
    target_ctx = ComponentPromptContext.for_entity(
        world, world.get_entity(contract_id), target=character
    )
    artifact_ctx = ComponentPromptContext.for_entity(
        world, world.get_entity(artifact_id), target=character
    )

    assert room.get_component(HabitatModuleComponent).prompt_fragments(room_ctx) == (
        f"You are in the engineering module ({room.id}).",
    )
    assert world.get_entity(contract_id).get_component(ContractComponent).prompt_fragments(
        target_ctx
    ) == ("Available survey contract: survey charter for 40 credits.",)
    assert (
        world.get_entity(artifact_id)
        .get_component(AlienArtifactComponent)
        .prompt_fragments(artifact_ctx)
        == ()
    )


def test_voidsim_component_prompt_fragments_cover_alternate_branches():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    self_ctx = ComponentPromptContext.for_entity(world, character)
    observer = spawn_entity(world, [CharacterComponent()])

    def room_entity(name, kind, component):
        entity_id = _spawn_in_room_a(scenario, [IdentityComponent(name=name, kind=kind), component])
        entity = world.get_entity(entity_id)
        return entity, ComponentPromptContext.for_entity(
            world,
            entity,
            perspective=self_ctx.perspective,
            target=character,
        )

    def observer_ctx(entity):
        return ComponentPromptContext.for_entity(
            world,
            entity,
            perspective=PromptPerspective(viewer=observer),
            target=character,
        )

    source, source_ctx = room_entity(
        "warp crack", "hazard", ChaosInfluenceComponent(source_type="warp crack")
    )
    upgrade, upgrade_ctx = room_entity(
        "installed kit", "upgrade", ShipUpgradeComponent(system_type="engines", installed=True)
    )
    active_contract, active_contract_ctx = room_entity(
        "cargo run",
        "contract",
        ContractComponent(contract_type="cargo", status="active", accepted_by=str(character.id)),
    )
    other_contract, other_contract_ctx = room_entity(
        "other run",
        "contract",
        ContractComponent(contract_type="cargo", status="active", accepted_by="someone_else"),
    )
    delivered_cargo, delivered_cargo_ctx = room_entity(
        "ore crates", "cargo", CargoComponent(delivered=True)
    )
    loaded_cargo, loaded_cargo_ctx = room_entity(
        "med crates", "cargo", CargoComponent(loaded_on="ship_1")
    )
    claimed_salvage, claimed_salvage_ctx = room_entity(
        "wreck claim", "salvage", SalvageClaimComponent(site_id="site_1", claimed=True)
    )
    contacted, contacted_ctx = room_entity(
        "envoy",
        "contact",
        FirstContactComponent(species_id="sp", contacted_by=(str(character.id),)),
    )
    complete_matrix, complete_matrix_ctx = room_entity(
        "lexicon", "matrix", TranslationMatrixComponent(species_id="sp", complete=True)
    )
    inactive_quarantine, inactive_quarantine_ctx = room_entity(
        "sample", "sample", QuarantineComponent(active=False)
    )
    artifact, artifact_ctx = room_entity("idol", "artifact", AlienArtifactComponent(studied_by=()))

    assert source.get_component(ChaosInfluenceComponent).prompt_fragments(source_ctx) == (
        "Chaos source warp crack: warp crack (1/hour).",
    )
    assert upgrade.get_component(ShipUpgradeComponent).prompt_fragments(upgrade_ctx) == ()
    assert active_contract.get_component(ContractComponent).prompt_fragments(
        active_contract_ctx
    ) == ("Cargo contract cargo run: active.",)
    assert (
        other_contract.get_component(ContractComponent).prompt_fragments(other_contract_ctx) == ()
    )
    assert delivered_cargo.get_component(CargoComponent).prompt_fragments(delivered_cargo_ctx) == (
        "Cargo delivered: ore crates.",
    )
    assert loaded_cargo.get_component(CargoComponent).prompt_fragments(loaded_cargo_ctx) == (
        "Cargo loaded on ship_1: med crates.",
    )
    assert (
        claimed_salvage.get_component(SalvageClaimComponent).prompt_fragments(claimed_salvage_ctx)
        == ()
    )
    assert contacted.get_component(FirstContactComponent).prompt_fragments(contacted_ctx) == ()
    assert contacted.get_component(FirstContactComponent).prompt_fragments(
        observer_ctx(contacted)
    ) == ("First contact opportunity: envoy.",)
    assert complete_matrix.get_component(TranslationMatrixComponent).prompt_fragments(
        complete_matrix_ctx
    ) == ("Translation matrix lexicon: complete.",)
    assert (
        inactive_quarantine.get_component(QuarantineComponent).prompt_fragments(
            inactive_quarantine_ctx
        )
        == ()
    )
    assert artifact.get_component(AlienArtifactComponent).prompt_fragments(artifact_ctx) == (
        "Alien artifact ready for study: idol.",
    )
    studied_artifact = world.get_entity(
        _spawn_in_room_a(
            scenario,
            [
                IdentityComponent(name="tablet", kind="artifact"),
                AlienArtifactComponent(studied_by=(str(character.id),)),
            ],
        )
    )
    assert (
        studied_artifact.get_component(AlienArtifactComponent).prompt_fragments(
            ComponentPromptContext.for_entity(
                world,
                studied_artifact,
                perspective=self_ctx.perspective,
                target=character,
            )
        )
        == ()
    )
    assert studied_artifact.get_component(AlienArtifactComponent).prompt_fragments(
        observer_ctx(studied_artifact)
    ) == ("Alien artifact ready for study: tablet.",)


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
        JumpRoute(fuel_cost=fuel_cost, hazard=hazard, jump_seconds=jump_seconds, label="moss lane"),
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


def test_jump_travel_consequence_skips_pending_invalid_and_originless_routes():
    scenario = build_scenario()
    _system(scenario, scenario.room_b, "Proxima")
    ship_id = _ship_in(scenario, scenario.room_a)
    ship = scenario.actor.world.get_entity(ship_id)
    consequence = JumpTravelConsequence()
    ship.add_component(
        NavigationRouteComponent(
            destination_id=str(scenario.room_b),
            fuel_cost=1.0,
            arrive_at_epoch=HOUR,
            status="plotted",
        )
    )

    assert consequence.process(scenario.actor.world, HOUR) == []

    replace_component(
        ship,
        NavigationRouteComponent(
            destination_id="not-an-entity",
            fuel_cost=1.0,
            arrive_at_epoch=HOUR,
            status="jumping",
        ),
    )
    assert consequence.process(scenario.actor.world, HOUR) == []

    replace_component(
        ship,
        NavigationRouteComponent(
            destination_id=str(scenario.room_b),
            fuel_cost=1.0,
            arrive_at_epoch=HOUR,
            status="jumping",
        ),
    )
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(Contains, ship.id)

    events = consequence.process(scenario.actor.world, HOUR)

    assert len(events) == 1
    assert isinstance(events[0], JumpCompletedEvent)
    assert container_of(ship) == scenario.room_b


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

    await scenario.actor.submit(_cmd(scenario, "answer-distress-signal", signal_id=str(signal.id)))
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
        "CrewDutyConsequence",
    }


def _make_shift(scenario, *, name="alpha", start_hour=8, end_hour=16, role="engineering"):
    return spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=f"{name} watch", kind="shift"),
            DutyShiftComponent(name=name, start_hour=start_hour, end_hour=end_hour, role=role),
        ],
    ).id


async def test_assign_and_relieve_crew_shift_updates_roster_edge():
    scenario = build_scenario()
    _install(scenario.actor)
    shift = _make_shift(scenario)
    assigned: list[CrewShiftAssignedEvent] = []
    relieved: list[CrewShiftRelievedEvent] = []
    scenario.actor.bus.subscribe(CrewShiftAssignedEvent, assigned.append)
    scenario.actor.bus.subscribe(CrewShiftRelievedEvent, relieved.append)

    await scenario.actor.submit(
        _cmd(scenario, "assign-crew-shift", shift_id=str(shift), station="reactor")
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(WorksShift, shift)
    assert assigned[0].station == "reactor"
    assert assigned[0].shift_name == "alpha"

    await scenario.actor.submit(_cmd(scenario, "relieve-crew-shift", shift_id=str(shift)))
    await scenario.actor.tick(HOUR)
    assert not character.has_relationship(WorksShift, shift)
    assert relieved[0].shift_name == "alpha"


def test_crew_duty_consequence_flips_on_and_off_watch():
    scenario = build_scenario()
    _install(scenario.actor)
    shift = _make_shift(scenario, start_hour=8, end_hour=16)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(WorksShift(station="reactor"), shift)
    consequence = CrewDutyConsequence()

    # Before the watch: status initialised off duty, no event.
    assert consequence.process(scenario.actor.world, 6 * HOUR) == []
    assert character.get_component(CrewDutyStatusComponent).on_duty is False

    # The clock enters the watch window.
    on_events = consequence.process(scenario.actor.world, 9 * HOUR)
    assert len(on_events) == 1
    assert isinstance(on_events[0], CrewDutyChangedEvent)
    assert on_events[0].on_duty is True
    assert character.get_component(CrewDutyStatusComponent).on_duty is True
    # Re-running mid-watch is idempotent.
    assert consequence.process(scenario.actor.world, 12 * HOUR) == []

    # The clock leaves the watch window.
    off_events = consequence.process(scenario.actor.world, 18 * HOUR)
    assert len(off_events) == 1
    assert off_events[0].on_duty is False
    assert character.get_component(CrewDutyStatusComponent).on_duty is False

    fragments = voidsim_fragments(scenario.actor.world, character)
    assert any("Duty shift: alpha watch (08:00-16:00) as engineering" in line for line in fragments)


def test_crew_duty_consequence_handles_overnight_watch_and_skips_unrostered_crew():
    scenario = build_scenario()
    _install(scenario.actor)
    overnight = _make_shift(scenario, name="gamma", start_hour=22, end_hour=6, role="watch")
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(WorksShift(), overnight)
    consequence = CrewDutyConsequence()

    assert consequence.process(scenario.actor.world, 23 * HOUR)[0].on_duty is True
    assert consequence.process(scenario.actor.world, 3 * HOUR) == []  # still within 22->06
    assert consequence.process(scenario.actor.world, 12 * HOUR)[0].on_duty is False

    # A character with neither a shift nor a status component is ignored entirely.
    bystander = spawn_entity(scenario.actor.world, [CharacterComponent(species="bunny")])
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), bystander.id
    )
    assert consequence.process(scenario.actor.world, 9 * HOUR) == []
    assert not scenario.actor.world.get_entity(bystander.id).has_component(CrewDutyStatusComponent)


def test_crew_shift_handlers_reject_invalid_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    not_a_shift = spawn_entity(scenario.actor.world, [IdentityComponent(name="crate", kind="prop")])
    shift = _make_shift(scenario)

    assign = AssignCrewShiftHandler()
    relieve = RelieveCrewShiftHandler()
    reasons = {
        execute_handler(
            assign, ctx, _handler_cmd(scenario, "assign-crew-shift", character_id="x", shift_id="y")
        ).reason,
        execute_handler(
            assign, ctx, _handler_cmd(scenario, "assign-crew-shift", shift_id="entity_999")
        ).reason,
        execute_handler(
            assign, ctx, _handler_cmd(scenario, "assign-crew-shift", shift_id=str(not_a_shift.id))
        ).reason,
        execute_handler(
            relieve,
            ctx,
            _handler_cmd(scenario, "relieve-crew-shift", character_id="x", shift_id="y"),
        ).reason,
        execute_handler(
            relieve, ctx, _handler_cmd(scenario, "relieve-crew-shift", shift_id="entity_999")
        ).reason,
        execute_handler(
            relieve, ctx, _handler_cmd(scenario, "relieve-crew-shift", shift_id=str(shift))
        ).reason,
    }
    assert "invalid crew or shift id" in reasons
    assert "shift does not exist" in reasons
    assert "target is not a duty shift" in reasons
    assert "not assigned to this shift" in reasons

    assert execute_handler(
        assign, ctx, _handler_cmd(scenario, "assign-crew-shift", shift_id=str(shift))
    ).ok
    assert (
        execute_handler(
            assign, ctx, _handler_cmd(scenario, "assign-crew-shift", shift_id=str(shift))
        ).reason
        == "already assigned to this shift"
    )


def _fabricator(scenario):
    return _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="nanoforge", kind="module"), FabricatorComponent(online=True)],
    )


def _blueprint(scenario, *, required_tech="", system_type="shields", resource_inputs=()):
    return _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="shield booster", kind="blueprint"),
            BlueprintComponent(
                name="shield booster",
                system_type=system_type,
                required_tech=required_tech,
                integrity_bonus=30.0,
                resource_inputs=resource_inputs,
            ),
        ],
    )


def _inventory_resource(scenario, resource_type, quantity):
    entity = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=resource_type, kind="resource"),
            ResourceStackComponent(resource_type=resource_type, quantity=quantity),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), entity.id
    )
    return entity.id


def _unlock_tech(scenario, tech_id):
    return _spawn_in_room_a(scenario, [TechUnlockComponent(tech_id=tech_id, unlocked_at_epoch=0)])


def test_voidsim_inventory_resource_spending_plan_covers_edge_cases():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    rock = spawn_entity(world, [IdentityComponent(name="rock", kind="prop")])
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), rock.id)
    scrap = _inventory_resource(scenario, "scrap", 3)

    assert _spend_inventory_resource_operations(character, world, (("crystal", 1),)) is None
    assert _spend_inventory_resource_operations(character, world, (("scrap", 4),)) is None
    assert _spend_inventory_resource_operations(character, world, (("scrap", 0),)) == []
    assert world.get_entity(scrap).get_component(ResourceStackComponent).quantity == 3
    operations = _spend_inventory_resource_operations(character, world, (("scrap", 2),))
    assert operations is not None
    execute_mutation_plan(world, MutationPlan(tuple(operations)))
    assert world.get_entity(scrap).get_component(ResourceStackComponent).quantity == 1


async def test_fabricate_requires_unlocked_tech_then_yields_an_upgrade_part():
    scenario = build_scenario()
    _install(scenario.actor)
    fabricator = _fabricator(scenario)
    blueprint = _blueprint(scenario, required_tech="shield-tech")
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    # Without the research, fabrication is refused.
    await scenario.actor.submit(
        _cmd(scenario, "fabricate", fabricator_id=str(fabricator), blueprint_id=str(blueprint))
    )
    await scenario.actor.tick(HOUR)
    assert any("technology" in event.reason for event in rejects)

    # After colony-sim research unlocks the tech, fabrication succeeds.
    _unlock_tech(scenario, "shield-tech")
    fabricated: list[ItemFabricatedEvent] = []
    scenario.actor.bus.subscribe(ItemFabricatedEvent, fabricated.append)
    await scenario.actor.submit(
        _cmd(scenario, "fabricate", fabricator_id=str(fabricator), blueprint_id=str(blueprint))
    )
    await scenario.actor.tick(HOUR)

    assert fabricated and fabricated[0].system_type == "shields"
    part_id = parse_entity_id(fabricated[0].item_id)
    part = scenario.actor.world.get_entity(part_id)
    assert part.get_component(ShipUpgradeComponent).system_type == "shields"
    assert container_of(part) == scenario.character


async def test_fabricate_consumes_colony_resource_inputs():
    scenario = build_scenario()
    _install(scenario.actor)
    fabricator = _fabricator(scenario)
    blueprint = _blueprint(
        scenario,
        resource_inputs=(("scrap", 2), ("crystal", 1)),
    )
    scrap = _inventory_resource(scenario, "scrap", 3)
    crystal = _inventory_resource(scenario, "crystal", 1)
    fabricated: list[ItemFabricatedEvent] = []
    scenario.actor.bus.subscribe(ItemFabricatedEvent, fabricated.append)

    await scenario.actor.submit(
        _cmd(scenario, "fabricate", fabricator_id=str(fabricator), blueprint_id=str(blueprint))
    )
    await scenario.actor.tick(HOUR)

    assert fabricated[0].resource_inputs == (("scrap", 2), ("crystal", 1))
    assert (
        scenario.actor.world.get_entity(scrap).get_component(ResourceStackComponent).quantity == 1
    )
    assert (
        scenario.actor.world.get_entity(crystal).get_component(ResourceStackComponent).quantity == 0
    )


async def test_fabricate_rejects_missing_colony_resource_inputs():
    scenario = build_scenario()
    _install(scenario.actor)
    fabricator = _fabricator(scenario)
    blueprint = _blueprint(scenario, resource_inputs=(("scrap", 2),))
    _inventory_resource(scenario, "scrap", 1)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "fabricate", fabricator_id=str(fabricator), blueprint_id=str(blueprint))
    )
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "not enough resources to fabricate" for event in rejects)


async def test_install_upgrade_boosts_matching_ship_system():
    scenario = build_scenario()
    _install(scenario.actor)
    system = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="shield emitter", kind="system"),
            ShipSystemComponent(system_type="shields", integrity=40.0, online=False),
        ],
    )
    upgrade = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="shield booster", kind="upgrade"),
            ShipUpgradeComponent(system_type="shields", integrity_bonus=30.0),
        ],
    )
    installed: list[UpgradeInstalledEvent] = []
    scenario.actor.bus.subscribe(UpgradeInstalledEvent, installed.append)

    await scenario.actor.submit(
        _cmd(scenario, "install-upgrade", upgrade_id=str(upgrade), system_id=str(system))
    )
    await scenario.actor.tick(HOUR)

    system_state = scenario.actor.world.get_entity(system).get_component(ShipSystemComponent)
    assert system_state.integrity == 70.0
    assert system_state.online is True
    assert scenario.actor.world.get_entity(upgrade).get_component(ShipUpgradeComponent).installed
    assert installed and installed[0].integrity == 70.0


def _cargo_contract(scenario):
    contract = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="med freight contract", kind="contract"),
            ContractComponent(
                contract_type="cargo",
                destination_id=str(scenario.room_b),
                reward=75,
            ),
        ],
    )
    cargo = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="medical freight", kind="cargo"),
            CargoComponent(cargo_type="medicine", destination_id=str(scenario.room_b)),
        ],
    )
    ship = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="Burrow Runner", kind="ship"), ShipComponent(name="Burrow Runner")],
    )
    contract_entity = scenario.actor.world.get_entity(contract)
    contract_entity.remove_component(ContractComponent)
    contract_entity.add_component(
        ContractComponent(
            contract_type="cargo",
            destination_id=str(scenario.room_b),
            reward=75,
            cargo_id=str(cargo),
        )
    )
    return contract, cargo, ship


async def test_cargo_contract_loads_and_delivers_cargo():
    scenario = build_scenario()
    _install(scenario.actor)
    contract, cargo, ship = _cargo_contract(scenario)
    accepted: list[ContractAcceptedEvent] = []
    loaded: list[CargoLoadedEvent] = []
    delivered: list[CargoDeliveredEvent] = []
    completed: list[ContractCompletedEvent] = []
    scenario.actor.bus.subscribe(ContractAcceptedEvent, accepted.append)
    scenario.actor.bus.subscribe(CargoLoadedEvent, loaded.append)
    scenario.actor.bus.subscribe(CargoDeliveredEvent, delivered.append)
    scenario.actor.bus.subscribe(ContractCompletedEvent, completed.append)

    await scenario.actor.submit(_cmd(scenario, "accept-contract", contract_id=str(contract)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "load-cargo",
            contract_id=str(contract),
            cargo_id=str(cargo),
            ship_id=str(ship),
        )
    )
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    assert accepted and accepted[0].contract_type == "cargo"
    assert container_of(world.get_entity(contract)) == scenario.character
    assert container_of(world.get_entity(cargo)) == ship
    assert loaded and loaded[0].ship_id == str(ship)

    world.get_entity(scenario.room_a).remove_relationship(Contains, ship)
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), ship
    )
    await scenario.actor.submit(
        _cmd(
            scenario,
            "deliver-cargo",
            contract_id=str(contract),
            cargo_id=str(cargo),
            ship_id=str(ship),
        )
    )
    await scenario.actor.tick(HOUR)

    assert container_of(world.get_entity(cargo)) == scenario.room_b
    assert world.get_entity(cargo).get_component(CargoComponent).delivered is True
    assert world.get_entity(contract).get_component(ContractComponent).status == "completed"
    assert delivered and delivered[0].destination_id == str(scenario.room_b)
    assert completed and completed[0].reward == 75


async def test_claim_salvage_requires_accepted_rights_and_marks_claim():
    scenario = build_scenario()
    _install(scenario.actor)
    claim = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="derelict hulk rights", kind="salvage"),
            SalvageClaimComponent(
                site_id=str(scenario.room_b),
                resource_outputs=(("scrap", 4), ("fuel", 1), ("empty", 0)),
            ),
        ],
    )
    contract = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="derelict salvage writ", kind="contract"),
            ContractComponent(
                contract_type="salvage",
                destination_id=str(scenario.room_b),
                salvage_claim_id=str(claim),
            ),
        ],
    )
    claimed: list[SalvageClaimedEvent] = []
    scenario.actor.bus.subscribe(SalvageClaimedEvent, claimed.append)

    await scenario.actor.submit(_cmd(scenario, "accept-contract", contract_id=str(contract)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "claim-salvage", claim_id=str(claim), contract_id=str(contract))
    )
    await scenario.actor.tick(HOUR)

    claim_state = scenario.actor.world.get_entity(claim).get_component(SalvageClaimComponent)
    assert claim_state.claimed is True
    assert claim_state.claimed_by == str(scenario.character)
    assert claimed and claimed[0].contract_id == str(contract)
    output_ids = [parse_entity_id(raw) for raw in claimed[0].output_ids]
    assert all(output_id is not None for output_id in output_ids)
    outputs = [
        scenario.actor.world.get_entity(output_id).get_component(ResourceStackComponent)
        for output_id in output_ids
        if output_id is not None
    ]
    assert {(stack.resource_type, stack.quantity) for stack in outputs} == {
        ("scrap", 4),
        ("fuel", 1),
    }
    assert all(
        container_of(scenario.actor.world.get_entity(output_id)) == scenario.character
        for output_id in output_ids
        if output_id is not None
    )


def test_command_drone_can_handle_only_drone_targets():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    drone = _spawn_in_room_a(scenario, [DroneComponent()])

    assert CommandDroneHandler().can_handle(
        ctx, _handler_cmd(scenario, "command", target_id=str(drone))
    )
    assert not CommandDroneHandler().can_handle(
        ctx, _handler_cmd(scenario, "command", target_id="not-an-id")
    )


async def test_alien_contact_translation_quarantine_diplomacy_and_artifact_study():
    scenario = build_scenario()
    _install(scenario.actor)
    species = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="Glass Choir", kind="species"),
            AlienSpeciesComponent(name="Glass Choir", disposition="wary"),
        ],
    )
    contact = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="first contact ping", kind="contact"),
            FirstContactComponent(species_id=str(species)),
        ],
    )
    matrix = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="choir lexicon", kind="translation"),
            TranslationMatrixComponent(species_id=str(species), progress=80.0),
        ],
    )
    sample = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="glowing spore", kind="sample")],
    )
    mission = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="choir envoy", kind="mission"),
            DiplomaticMissionComponent(species_id=str(species), standing=1),
        ],
    )
    artifact = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="glass knot", kind="artifact"),
            AlienArtifactComponent(species_id=str(species), insight="harmony map"),
        ],
    )
    contacted: list[FirstContactEvent] = []
    translated: list[TranslationProgressedEvent] = []
    quarantined: list[QuarantineStartedEvent] = []
    diplomacy: list[DiplomacyChangedEvent] = []
    studied: list[AlienArtifactStudiedEvent] = []
    scenario.actor.bus.subscribe(FirstContactEvent, contacted.append)
    scenario.actor.bus.subscribe(TranslationProgressedEvent, translated.append)
    scenario.actor.bus.subscribe(QuarantineStartedEvent, quarantined.append)
    scenario.actor.bus.subscribe(DiplomacyChangedEvent, diplomacy.append)
    scenario.actor.bus.subscribe(AlienArtifactStudiedEvent, studied.append)

    await scenario.actor.submit(_cmd(scenario, "initiate-contact", contact_id=str(contact)))
    await scenario.actor.tick(HOUR)
    assert contacted[0].status == "contacted"
    assert scenario.actor.world.get_entity(contact).get_component(
        FirstContactComponent
    ).contacted_by == (str(scenario.character),)

    await scenario.actor.submit(
        _cmd(scenario, "attempt-translation", matrix_id=str(matrix), progress=25)
    )
    await scenario.actor.tick(HOUR)
    assert (
        scenario.actor.world.get_entity(matrix).get_component(TranslationMatrixComponent).complete
        is True
    )
    assert translated[0].progress == 100.0

    await scenario.actor.submit(
        _cmd(scenario, "quarantine-sample", target_id=str(sample), reason="unknown spores")
    )
    await scenario.actor.tick(HOUR)
    assert (
        scenario.actor.world.get_entity(sample).get_component(QuarantineComponent).reason
        == "unknown spores"
    )
    assert quarantined[0].target_id == str(sample)

    await scenario.actor.submit(
        _cmd(scenario, "negotiate-alien", mission_id=str(mission), standing_delta=2)
    )
    await scenario.actor.tick(HOUR)
    assert (
        scenario.actor.world.get_entity(mission).get_component(DiplomaticMissionComponent).standing
        == 3
    )
    assert diplomacy[0].standing == 3

    await scenario.actor.submit(_cmd(scenario, "study-alien-artifact", artifact_id=str(artifact)))
    await scenario.actor.tick(HOUR)
    assert scenario.actor.world.get_entity(artifact).get_component(
        AlienArtifactComponent
    ).studied_by == (str(scenario.character),)
    assert studied[0].insight == "harmony map"

    fragments = voidsim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )
    assert any("Glass Choir" in line for line in fragments)
    assert any("choir lexicon" in line and "complete" in line for line in fragments)
    assert any("choir envoy" in line and "standing 3" in line for line in fragments)


def test_contract_cargo_and_salvage_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    contract, cargo, ship = _cargo_contract(scenario)
    wrong = _spawn_in_room_a(scenario, [IdentityComponent(name="loose panel", kind="prop")])
    other_cargo = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="wrong crate", kind="cargo"),
            CargoComponent(cargo_type="ore"),
        ],
    )
    loaded_cargo = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="loaded crate", kind="cargo"),
            CargoComponent(cargo_type="ore", loaded_on=str(ship)),
        ],
    )
    delivered_cargo = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="delivered crate", kind="cargo"),
            CargoComponent(cargo_type="ore", delivered=True),
        ],
    )
    claim = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="wreck claim", kind="salvage"),
            SalvageClaimComponent(site_id=str(scenario.room_b)),
        ],
    )

    accept = AcceptContractHandler()
    load = LoadCargoHandler()
    deliver = DeliverCargoHandler()
    salvage = ClaimSalvageHandler()

    assert (
        execute_handler(
            accept, ctx, _handler_cmd(scenario, "accept-contract", character_id="x")
        ).reason
        == "invalid character id"
    )
    assert (
        execute_handler(
            accept, ctx, _handler_cmd(scenario, "accept-contract", contract_id=str(wrong))
        ).reason
        == "target is the wrong kind"
    )
    assert execute_handler(
        accept, ctx, _handler_cmd(scenario, "accept-contract", contract_id=str(contract))
    ).ok
    assert (
        execute_handler(
            accept, ctx, _handler_cmd(scenario, "accept-contract", contract_id=str(contract))
        ).reason
        == "contract is not available"
    )

    assert (
        execute_handler(load, ctx, _handler_cmd(scenario, "load-cargo", character_id="x")).reason
        == "invalid character id"
    )
    inactive = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="inactive contract", kind="contract"),
            ContractComponent(contract_type="cargo"),
        ],
    )
    assert (
        execute_handler(
            load,
            ctx,
            _handler_cmd(
                scenario,
                "load-cargo",
                contract_id=str(inactive),
                cargo_id=str(cargo),
                ship_id=str(ship),
            ),
        ).reason
        == "cargo contract is not active"
    )
    assert (
        execute_handler(
            load,
            ctx,
            _handler_cmd(
                scenario,
                "load-cargo",
                contract_id=str(contract),
                cargo_id=str(other_cargo),
                ship_id=str(ship),
            ),
        ).reason
        == "cargo does not match contract"
    )
    delivered_contract = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="delivered contract", kind="contract"),
            ContractComponent(
                contract_type="cargo",
                status="active",
                accepted_by=str(scenario.character),
            ),
        ],
    )
    assert (
        execute_handler(
            load,
            ctx,
            _handler_cmd(
                scenario,
                "load-cargo",
                contract_id=str(delivered_contract),
                cargo_id=str(delivered_cargo),
                ship_id=str(ship),
            ),
        ).reason
        == "cargo is already delivered"
    )
    assert (
        execute_handler(
            load,
            ctx,
            _handler_cmd(
                scenario,
                "load-cargo",
                contract_id=str(contract),
                cargo_id=str(cargo),
                ship_id=str(wrong),
            ),
        ).reason
        == "target is the wrong kind"
    )
    assert execute_handler(
        load,
        ctx,
        _handler_cmd(
            scenario,
            "load-cargo",
            contract_id=str(contract),
            cargo_id=str(cargo),
            ship_id=str(ship),
        ),
    ).ok
    assert (
        execute_handler(
            load,
            ctx,
            _handler_cmd(
                scenario,
                "load-cargo",
                contract_id=str(contract),
                cargo_id=str(cargo),
                ship_id=str(ship),
            ),
        ).reason
        == "target is not reachable"
    )
    flexible_contract = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="flex contract", kind="contract"),
            ContractComponent(
                contract_type="cargo",
                status="active",
                accepted_by=str(scenario.character),
            ),
        ],
    )
    assert (
        execute_handler(
            load,
            ctx,
            _handler_cmd(
                scenario,
                "load-cargo",
                contract_id=str(flexible_contract),
                cargo_id=str(loaded_cargo),
                ship_id=str(ship),
            ),
        ).reason
        == "cargo is already loaded"
    )

    assert (
        execute_handler(
            deliver, ctx, _handler_cmd(scenario, "deliver-cargo", character_id="x")
        ).reason
        == "invalid character id"
    )
    assert (
        execute_handler(
            deliver,
            ctx,
            _handler_cmd(
                scenario,
                "deliver-cargo",
                contract_id=str(contract),
                cargo_id="x",
                ship_id=str(ship),
            ),
        ).reason
        == "invalid cargo or ship id"
    )
    assert (
        execute_handler(
            deliver,
            ctx,
            _handler_cmd(
                scenario,
                "deliver-cargo",
                contract_id=str(inactive),
                cargo_id=str(cargo),
                ship_id=str(ship),
            ),
        ).reason
        == "cargo contract is not active"
    )
    assert (
        execute_handler(
            deliver,
            ctx,
            _handler_cmd(
                scenario,
                "deliver-cargo",
                contract_id=str(contract),
                cargo_id="entity_999",
                ship_id=str(ship),
            ),
        ).reason
        == "cargo or ship does not exist"
    )
    assert (
        execute_handler(
            deliver,
            ctx,
            _handler_cmd(
                scenario,
                "deliver-cargo",
                contract_id=str(contract),
                cargo_id=str(wrong),
                ship_id=str(ship),
            ),
        ).reason
        == "target is not cargo"
    )
    assert (
        execute_handler(
            deliver,
            ctx,
            _handler_cmd(
                scenario,
                "deliver-cargo",
                contract_id=str(contract),
                cargo_id=str(cargo),
                ship_id=str(wrong),
            ),
        ).reason
        == "target is not a ship"
    )
    assert (
        execute_handler(
            deliver,
            ctx,
            _handler_cmd(
                scenario,
                "deliver-cargo",
                contract_id=str(contract),
                cargo_id=str(other_cargo),
                ship_id=str(ship),
            ),
        ).reason
        == "cargo is not loaded on that ship"
    )
    assert (
        execute_handler(
            deliver,
            ctx,
            _handler_cmd(
                scenario,
                "deliver-cargo",
                contract_id=str(contract),
                cargo_id=str(cargo),
                ship_id=str(ship),
            ),
        ).reason
        == "ship is not at the destination"
    )
    missing_destination_contract = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="missing destination contract", kind="contract"),
            ContractComponent(
                contract_type="cargo",
                status="active",
                accepted_by=str(scenario.character),
                destination_id="entity_999",
            ),
        ],
    )
    assert (
        execute_handler(
            deliver,
            ctx,
            _handler_cmd(
                scenario,
                "deliver-cargo",
                contract_id=str(missing_destination_contract),
                cargo_id=str(cargo),
                ship_id=str(ship),
            ),
        ).reason
        == "destination does not exist"
    )

    assert (
        execute_handler(
            salvage, ctx, _handler_cmd(scenario, "claim-salvage", character_id="x")
        ).reason
        == "invalid character id"
    )
    assert (
        execute_handler(
            salvage, ctx, _handler_cmd(scenario, "claim-salvage", claim_id=str(wrong))
        ).reason
        == "target is the wrong kind"
    )
    assert (
        execute_handler(
            salvage,
            ctx,
            _handler_cmd(scenario, "claim-salvage", claim_id=str(claim), contract_id=str(inactive)),
        ).reason
        == "salvage rights are not held"
    )
    rights_claim = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="rights claim", kind="salvage"),
            SalvageClaimComponent(
                site_id=str(scenario.room_b),
                rights_contract_id="entity_999",
            ),
        ],
    )
    assert (
        execute_handler(
            salvage, ctx, _handler_cmd(scenario, "claim-salvage", claim_id=str(rights_claim))
        ).reason
        == "salvage contract does not exist"
    )
    assert execute_handler(
        salvage, ctx, _handler_cmd(scenario, "claim-salvage", claim_id=str(claim))
    ).ok
    assert (
        execute_handler(
            salvage, ctx, _handler_cmd(scenario, "claim-salvage", claim_id=str(claim))
        ).reason
        == "salvage is already claimed"
    )


def test_fabrication_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    offline = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="dead forge", kind="module"), FabricatorComponent(online=False)],
    )
    blueprint = _blueprint(scenario)
    system = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="reactor", kind="system"),
            ShipSystemComponent(system_type="reactor"),
        ],
    )
    wrong_upgrade = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="shield booster", kind="upgrade"),
            ShipUpgradeComponent(system_type="shields"),
        ],
    )
    installed_upgrade = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="spent part", kind="upgrade"),
            ShipUpgradeComponent(system_type="reactor", installed=True),
        ],
    )

    online_forge = _fabricator(scenario)
    cases = [
        (
            FabricateHandler(),
            _handler_cmd(scenario, "fabricate", character_id="x"),
            "invalid character",
        ),
        (
            FabricateHandler(),
            _handler_cmd(
                scenario, "fabricate", fabricator_id=str(system), blueprint_id=str(blueprint)
            ),
            "wrong kind",
        ),
        (
            FabricateHandler(),
            _handler_cmd(
                scenario, "fabricate", fabricator_id=str(online_forge), blueprint_id=str(system)
            ),
            "wrong kind",
        ),
        (
            FabricateHandler(),
            _handler_cmd(
                scenario, "fabricate", fabricator_id=str(offline), blueprint_id=str(blueprint)
            ),
            "offline",
        ),
        (
            InstallUpgradeHandler(),
            _handler_cmd(scenario, "install-upgrade", character_id="x"),
            "invalid character",
        ),
        (
            InstallUpgradeHandler(),
            _handler_cmd(
                scenario, "install-upgrade", upgrade_id=str(system), system_id=str(system)
            ),
            "wrong kind",
        ),
        (
            InstallUpgradeHandler(),
            _handler_cmd(
                scenario, "install-upgrade", upgrade_id=str(wrong_upgrade), system_id=str(blueprint)
            ),
            "wrong kind",
        ),
        (
            InstallUpgradeHandler(),
            _handler_cmd(
                scenario,
                "install-upgrade",
                upgrade_id=str(installed_upgrade),
                system_id=str(system),
            ),
            "already installed",
        ),
        (
            InstallUpgradeHandler(),
            _handler_cmd(
                scenario, "install-upgrade", upgrade_id=str(wrong_upgrade), system_id=str(system)
            ),
            "does not fit",
        ),
    ]
    for handler, command, expected in cases:
        result = execute_handler(handler, ctx, command)
        assert not result.ok, expected
        assert expected in result.reason, (expected, result.reason)


def test_voidsim_fragments_show_fabricator_blueprint_and_upgrade():
    scenario = build_scenario()
    _install(scenario.actor)
    _fabricator(scenario)
    _blueprint(scenario, required_tech="shield-tech")
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="shield booster", kind="upgrade"),
            ShipUpgradeComponent(system_type="shields"),
        ],
    )
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="survey charter", kind="contract"),
            ContractComponent(contract_type="survey", reward=40),
        ],
    )
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="ore crates", kind="cargo"),
            CargoComponent(cargo_type="ore"),
        ],
    )
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="wreck claim", kind="salvage"),
            SalvageClaimComponent(site_id=str(scenario.room_b)),
        ],
    )

    world = scenario.actor.world
    lines = voidsim_fragments(world, world.get_entity(scenario.character))
    assert any("Fabricator" in line for line in lines)
    assert any(
        "Blueprint shield booster" in line and "needs tech shield-tech" in line for line in lines
    )
    assert any("Upgrade part ready for shields" in line for line in lines)
    assert any("Available survey contract" in line for line in lines)
    assert any("Cargo waiting: ore crates" in line for line in lines)
    assert any("Salvage claim available: wreck claim" in line for line in lines)


async def test_fabricate_without_required_tech_succeeds():
    scenario = build_scenario()
    _install(scenario.actor)
    fabricator = _fabricator(scenario)
    blueprint = _blueprint(scenario, required_tech="")  # no research needed
    fabricated: list[ItemFabricatedEvent] = []
    scenario.actor.bus.subscribe(ItemFabricatedEvent, fabricated.append)

    await scenario.actor.submit(
        _cmd(scenario, "fabricate", fabricator_id=str(fabricator), blueprint_id=str(blueprint))
    )
    await scenario.actor.tick(HOUR)

    assert fabricated and fabricated[0].name == "shield booster"


def _reachable_wrong_kind(scenario):
    return _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="plain crate", kind="item")],
    )


def test_inspect_handlers_can_handle_resolve_target_id_and_reject_unrelated():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    system_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="reactor", kind="system"),
            ShipSystemComponent(system_type="reactor"),
        ],
    )
    hold_id = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="cargo hold", kind="hold"), CustomsHoldComponent()],
    )
    other_id = _reachable_wrong_kind(scenario)

    ship_inspect = InspectShipSystemHandler()
    customs_inspect = InspectCustomsHandler()

    # Explicit hold_id/system_id key short-circuits to True (covers 1028-1029, 3049-3050).
    assert ship_inspect.can_handle(ctx, _handler_cmd(scenario, "inspect", system_id=str(system_id)))
    assert customs_inspect.can_handle(ctx, _handler_cmd(scenario, "inspect", hold_id=str(hold_id)))
    # No system_id/hold_id key: can_handle resolves via target_id (covers 1030-1031, 3051-3052).
    assert ship_inspect.can_handle(ctx, _handler_cmd(scenario, "inspect", target_id=str(system_id)))
    assert customs_inspect.can_handle(
        ctx, _handler_cmd(scenario, "inspect", target_id=str(hold_id))
    )
    # target_id is an unrelated entity: _payload_entity_id resolves but the component check fails.
    assert not ship_inspect.can_handle(
        ctx, _handler_cmd(scenario, "inspect", target_id=str(other_id))
    )
    assert not customs_inspect.can_handle(
        ctx, _handler_cmd(scenario, "inspect", target_id=str(other_id))
    )
    # No usable key: _payload_entity_id loops over both keys and returns None (covers 61->60, 63).
    assert not ship_inspect.can_handle(ctx, _handler_cmd(scenario, "inspect", junk="x"))
    assert not customs_inspect.can_handle(ctx, _handler_cmd(scenario, "inspect", junk="x"))


def test_alien_handlers_reject_invalid_character_and_wrong_kind():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    wrong = _reachable_wrong_kind(scenario)

    cases = [
        (InitiateContactHandler(), "initiate-contact", "contact_id", "target is not a contact"),
        (
            AttemptTranslationHandler(),
            "attempt-translation",
            "matrix_id",
            "target is not a translation matrix",
        ),
        (
            NegotiateAlienHandler(),
            "negotiate-alien",
            "mission_id",
            "target is not a diplomatic mission",
        ),
        (
            StudyAlienArtifactHandler(),
            "study-alien-artifact",
            "artifact_id",
            "target is not an alien artifact",
        ),
    ]
    for handler, command_type, key, _fallback in cases:
        # invalid character id branch
        bad = _handler_cmd(scenario, command_type, character_id="not-an-id", **{key: str(wrong)})
        assert execute_handler(handler, ctx, bad).reason == "invalid character id"
        # reachable but wrong-kind target -> _reachable_component yields truthy error text
        assert (
            execute_handler(
                handler, ctx, _handler_cmd(scenario, command_type, **{key: str(wrong)})
            ).reason
            == "target is the wrong kind"
        )

    # QuarantineSampleHandler has its own id/reachability checks.
    quarantine = QuarantineSampleHandler()
    assert (
        execute_handler(
            quarantine, ctx, _handler_cmd(scenario, "quarantine-sample", target_id="x")
        ).reason
        == "invalid character or target id"
    )
    assert (
        execute_handler(
            quarantine, ctx, _handler_cmd(scenario, "quarantine-sample", target_id="entity_999")
        ).reason
        == "target does not exist"
    )
    detached = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="far spore", kind="sample")]
    ).id
    assert (
        execute_handler(
            quarantine, ctx, _handler_cmd(scenario, "quarantine-sample", target_id=str(detached))
        ).reason
        == "target is not reachable"
    )


def test_alien_handlers_reject_already_done_state():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = str(scenario.character)
    contact = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="envoy", kind="contact"),
            FirstContactComponent(species_id="sp", contacted_by=(character,)),
        ],
    )
    matrix = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="lexicon", kind="matrix"),
            TranslationMatrixComponent(species_id="sp", complete=True),
        ],
    )
    artifact = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="idol", kind="artifact"),
            AlienArtifactComponent(studied_by=(character,)),
        ],
    )
    assert (
        execute_handler(
            InitiateContactHandler(),
            ctx,
            _handler_cmd(scenario, "initiate-contact", contact_id=str(contact)),
        ).reason
        == "contact already initiated"
    )
    assert (
        execute_handler(
            AttemptTranslationHandler(),
            ctx,
            _handler_cmd(scenario, "attempt-translation", matrix_id=str(matrix)),
        ).reason
        == "translation is already complete"
    )
    assert (
        execute_handler(
            StudyAlienArtifactHandler(),
            ctx,
            _handler_cmd(scenario, "study-alien-artifact", artifact_id=str(artifact)),
        ).reason
        == "artifact already studied"
    )


def test_orbit_and_jump_handlers_reject_wrong_kind_ship():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    wrong = _reachable_wrong_kind(scenario)
    for handler, command_type in (
        (LeaveOrbitHandler(), "leave-orbit"),
        (LandHandler(), "land"),
        (LaunchHandler(), "launch"),
        (JumpHandler(), "jump"),
    ):
        assert (
            execute_handler(
                handler, ctx, _handler_cmd(scenario, command_type, ship_id=str(wrong))
            ).reason
            == "target is the wrong kind"
        )


def test_plot_course_rejects_ship_outside_star_system():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # room_a is the character's container and has no container of its own; treating it as the
    # "ship" makes container_of(ship) None, so the handler reports it is not in a star system.
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(ShipComponent(name="hollow hull"))
    destination_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Vega", kind="star-system"), StarSystemComponent(name="Vega")],
    ).id
    result = execute_handler(
        PlotCourseHandler(),
        ctx,
        _handler_cmd(
            scenario,
            "plot-course",
            ship_id=str(scenario.room_a),
            destination_id=str(destination_id),
        ),
    )
    assert result.reason == "ship is not in a star system"


def test_scan_rejects_ship_outside_star_system():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(ShipComponent(name="hollow hull"))
    room.add_component(SensorComponent(scan_range=1.0))
    result = execute_handler(
        ScanHandler(), ctx, _handler_cmd(scenario, "scan", ship_id=str(scenario.room_a))
    )
    assert result.reason == "ship is not in a star system"


def test_cargo_handlers_reject_wrong_kind_contract():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    wrong = _reachable_wrong_kind(scenario)
    assert (
        execute_handler(
            AcceptContractHandler(),
            ctx,
            _handler_cmd(scenario, "accept-contract", contract_id=str(wrong)),
        ).reason
        == "target is the wrong kind"
    )
    assert (
        execute_handler(
            LoadCargoHandler(), ctx, _handler_cmd(scenario, "load-cargo", contract_id=str(wrong))
        ).reason
        == "target is the wrong kind"
    )
    assert (
        execute_handler(
            DeliverCargoHandler(),
            ctx,
            _handler_cmd(
                scenario,
                "deliver-cargo",
                contract_id=str(wrong),
                cargo_id=str(wrong),
                ship_id=str(wrong),
            ),
        ).reason
        == "target is the wrong kind"
    )


def test_active_contract_for_rejects_non_owner_and_wrong_type():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    cargo = _spawn_in_room_a(
        scenario, [IdentityComponent(name="crate", kind="cargo"), CargoComponent(cargo_type="ore")]
    )
    ship = _spawn_in_room_a(
        scenario, [IdentityComponent(name="hauler", kind="ship"), ShipComponent(name="hauler")]
    )
    # Active contract owned by someone else -> _active_contract_for returns None (covers 1279 path).
    other_owner = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="not mine", kind="contract"),
            ContractComponent(contract_type="cargo", status="active", accepted_by="entity_424242"),
        ],
    )
    assert (
        execute_handler(
            LoadCargoHandler(),
            ctx,
            _handler_cmd(
                scenario,
                "load-cargo",
                contract_id=str(other_owner),
                cargo_id=str(cargo),
                ship_id=str(ship),
            ),
        ).reason
        == "cargo contract is not active"
    )
    # Active, owned, but the wrong contract type -> expected_type mismatch (covers 1279).
    wrong_type = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="survey job", kind="contract"),
            ContractComponent(
                contract_type="survey", status="active", accepted_by=str(scenario.character)
            ),
        ],
    )
    assert (
        execute_handler(
            DeliverCargoHandler(),
            ctx,
            _handler_cmd(
                scenario,
                "deliver-cargo",
                contract_id=str(wrong_type),
                cargo_id=str(cargo),
                ship_id=str(ship),
            ),
        ).reason
        == "cargo contract is not active"
    )


def test_reachable_entity_with_rejection_branches():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    handler = DeployAwayTeamHandler()
    # invalid target id
    assert (
        execute_handler(
            handler, ctx, _handler_cmd(scenario, "deploy-away-team", team_id="x")
        ).reason
        == "invalid target id"
    )
    # character does not exist (character id parses but is absent)
    assert (
        execute_handler(
            handler,
            ctx,
            _handler_cmd(
                scenario, "deploy-away-team", character_id="entity_999999", team_id="entity_1"
            ),
        ).reason
        == "character does not exist"
    )
    # target does not exist
    assert (
        execute_handler(
            handler, ctx, _handler_cmd(scenario, "deploy-away-team", team_id="entity_999999")
        ).reason
        == "target does not exist"
    )
    # target not reachable
    detached = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="lost team", kind="team"), AwayTeamComponent()],
    ).id
    assert (
        execute_handler(
            handler, ctx, _handler_cmd(scenario, "deploy-away-team", team_id=str(detached))
        ).reason
        == "target is not reachable"
    )
    # target has wrong component
    wrong = _reachable_wrong_kind(scenario)
    assert (
        execute_handler(
            handler, ctx, _handler_cmd(scenario, "deploy-away-team", team_id=str(wrong))
        ).reason
        == "target has wrong component"
    )
    # already deployed
    deployed = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="busy team", kind="team"), AwayTeamComponent(deployed=True)],
    )
    assert (
        execute_handler(
            handler, ctx, _handler_cmd(scenario, "deploy-away-team", team_id=str(deployed))
        ).reason
        == "away team already deployed"
    )


def test_economy_handlers_reject_already_done_and_bad_amount():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    depleted = _spawn_in_room_a(
        scenario,
        [IdentityComponent(name="dry rock", kind="mine"), MiningSiteComponent(remaining=0)],
    )
    claimed_policy = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="spent policy", kind="policy"),
            InsurancePolicyComponent(claimed=True),
        ],
    )
    mortgage = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="ship lien", kind="mortgage"),
            MortgageComponent(principal=100, balance=100),
        ],
    )
    assert (
        execute_handler(
            MineAsteroidHandler(),
            ctx,
            _handler_cmd(scenario, "mine-asteroid", site_id=str(depleted)),
        ).reason
        == "mining site is depleted"
    )
    assert (
        execute_handler(
            ClaimInsuranceHandler(),
            ctx,
            _handler_cmd(scenario, "claim-insurance", policy_id=str(claimed_policy)),
        ).reason
        == "insurance already claimed"
    )
    assert (
        execute_handler(
            PayMortgageHandler(),
            ctx,
            _handler_cmd(scenario, "pay-mortgage", mortgage_id=str(mortgage), amount=0),
        ).reason
        == "mortgage payment must be positive"
    )


def test_round_the_clock_shift_covers_any_hour():
    from bunnyland.simpacks.voidsim.mechanics import DutyShiftComponent as _Shift
    from bunnyland.simpacks.voidsim.mechanics import _shift_covers_hour

    shift = _Shift(name="watch", start_hour=4, end_hour=4)
    assert _shift_covers_hour(shift, 0) is True
    assert _shift_covers_hour(shift, 17) is True


def test_voidsim_fragments_cover_crew_morale_mutiny_and_shift_edges():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    character.add_component(MoraleComponent(value=5))
    character.add_component(MutinyComponent(active=True, ringleader_id="x"))
    character.add_component(CrewDutyStatusComponent(on_duty=True))
    shift_id = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="alpha", kind="shift"),
            DutyShiftComponent(name="alpha", start_hour=0, end_hour=8, role="pilot"),
        ],
    )
    character.add_relationship(WorksShift(station="helm"), shift_id)
    # An assignment to a reachable entity lacking the shift component (covers 3345->3341).
    non_shift = _spawn_in_room_a(scenario, [IdentityComponent(name="not a shift", kind="item")])
    character.add_relationship(WorksShift(station=""), non_shift)

    lines = voidsim_fragments(world, character)
    assert any("Crew morale: 5." == line for line in lines)
    assert any("Mutiny is active." == line for line in lines)
    assert any("You are currently on duty." == line for line in lines)
    assert any("Duty shift: alpha watch" in line and "station helm" in line for line in lines)


def test_morale_and_mutiny_non_first_person_are_silent():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    observer = spawn_entity(world, [CharacterComponent()])
    perspective = PromptPerspective(viewer=observer)
    morale_ctx = ComponentPromptContext.for_entity(world, character, perspective=perspective)
    assert MoraleComponent(value=5).prompt_fragments(morale_ctx) == ()
    # Inactive mutiny is silent even first-person.
    self_ctx = ComponentPromptContext.for_entity(world, character)
    assert MutinyComponent(active=False).prompt_fragments(self_ctx) == ()
    assert MutinyComponent(active=True).prompt_fragments(morale_ctx) == ()
    assert CrewDutyStatusComponent(on_duty=False).prompt_fragments(self_ctx) == ()


def test_chaos_consequence_covers_no_source_targets_and_no_change_paths():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    from bunnyland.simpacks.voidsim.mechanics import (
        _chaos_targets_for_source,
        _ship_systems_near_source,
    )

    # A chaos source with no reachable characters: the targets loop body never runs (2199->2193).
    detached_source = spawn_entity(
        world,
        [
            IdentityComponent(name="floating scar", kind="hazard"),
            ChaosInfluenceComponent(source_type="warp scar", corruption_per_hour=1.0),
        ],
    )
    assert _chaos_targets_for_source(world, detached_source.id) == []
    # A source with no container yields no nearby ship systems (covers 2207).
    assert _ship_systems_near_source(world, detached_source) == []

    # Run the consequence twice: the first call records the epoch with elapsed<=0 (covers 2227),
    # the second has elapsed but no reachable target, so it short-circuits cleanly.
    consequence = ChaosInfluenceConsequence()
    assert consequence.process(world, 0) == []
    assert consequence.process(world, 3600) == []


def test_chaos_consequence_skips_systems_with_no_integrity_change():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    # The chaos source must be a contained entity so _ship_systems_near_source finds the
    # systems sharing its container; room_a has no container, so place the source inside it.
    source = _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="warp scar", kind="hazard"),
            ChaosInfluenceComponent(
                source_type="warp scar",
                corruption_per_hour=0.0,
                system_damage_per_hour=2.0,
                last_updated_epoch=0,
            ),
        ],
    )
    # A fully-destroyed system sharing the source's room: integrity already 0 and offline, so
    # further damage is a no-op and the system is skipped (covers the `continue` at 2301).
    _spawn_in_room_a(
        scenario,
        [
            IdentityComponent(name="dead reactor", kind="system"),
            ShipSystemComponent(system_type="reactor", integrity=0.0, online=False),
        ],
    )
    assert source  # source placed; processing must not damage the dead system
    events = ChaosInfluenceConsequence().process(world, 3600)
    assert all(getattr(e, "system_id", None) is None for e in events)


def test_fabricate_skips_dangling_inventory_and_respects_unrelated_tech():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    fabricator = _fabricator(scenario)
    # required_tech that is unlocked elsewhere only via a non-matching TechUnlock first, so the
    # _tech_unlocked loop iterates past a mismatch (covers 1069->1068) before finding a match.
    _unlock_tech(scenario, "unrelated-tech")
    _unlock_tech(scenario, "shield-tech")
    blueprint = _blueprint(scenario, required_tech="shield-tech", resource_inputs=(("scrap", 1),))
    _inventory_resource(scenario, "scrap", 2)

    result = execute_handler(
        FabricateHandler(),
        ctx,
        _handler_cmd(
            scenario, "fabricate", fabricator_id=str(fabricator), blueprint_id=str(blueprint)
        ),
    )
    assert result.ok


def test_active_contract_for_returns_none_for_non_contract_entity():
    from bunnyland.simpacks.voidsim.mechanics import _active_contract_for

    scenario = build_scenario()
    world = scenario.actor.world
    plain = spawn_entity(world, [IdentityComponent(name="rock", kind="item")])
    assert _active_contract_for(plain, scenario.character) is None


def test_load_and_accept_handle_uncontained_targets():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    room = world.get_entity(scenario.room_a)
    character = str(scenario.character)
    # An offered contract placed directly on the (uncontained) room: AcceptContract finds no
    # origin container to detach from (covers 1247->1249). Use a separate scenario so the room
    # stays uncontained for the move test below.
    room.add_component(ContractComponent(contract_type="cargo", reward=10))
    assert execute_handler(
        AcceptContractHandler(),
        ctx,
        _handler_cmd(scenario, "accept-contract", contract_id=str(scenario.room_a)),
    ).ok
    assert room.get_component(ContractComponent).accepted_by == character

    # Fresh scenario: cargo lives on the uncontained room, so _move_entity sees no origin
    # container to remove from (covers 1224->1226).
    move_scenario = build_scenario()
    _install(move_scenario.actor)
    move_ctx = HandlerContext(move_scenario.actor.world, move_scenario.actor.epoch)
    move_room = move_scenario.actor.world.get_entity(move_scenario.room_a)
    move_room.add_component(CargoComponent(cargo_type="cargo"))
    contract = _spawn_in_room_a(
        move_scenario,
        [
            IdentityComponent(name="cargo run", kind="contract"),
            ContractComponent(
                contract_type="cargo",
                status="active",
                accepted_by=str(move_scenario.character),
            ),
        ],
    )
    ship = _spawn_in_room_a(
        move_scenario,
        [IdentityComponent(name="hauler", kind="ship"), ShipComponent(name="hauler")],
    )
    result = execute_handler(
        LoadCargoHandler(),
        move_ctx,
        _handler_cmd(
            move_scenario,
            "load-cargo",
            contract_id=str(contract),
            cargo_id=str(move_scenario.room_a),
            ship_id=str(ship),
        ),
    )
    assert result.ok
    assert move_room.get_component(CargoComponent).loaded_on == str(ship)


def test_jump_route_scans_past_non_matching_destinations():
    from bunnyland.simpacks.voidsim.mechanics import _jump_route as _route_lookup

    scenario = build_scenario()
    world = scenario.actor.world
    origin = world.get_entity(scenario.room_a)
    other = spawn_entity(world, [IdentityComponent(name="elsewhere", kind="star-system")])
    # A route to some other destination is iterated and skipped before the missing one is sought
    # (covers 1753->1752, then the loop falls through to return None).
    origin.add_relationship(JumpRoute(fuel_cost=1.0, label="lane"), other.id)
    target = spawn_entity(world, [IdentityComponent(name="goal", kind="star-system")])
    assert _route_lookup(origin, target.id) is None


def test_tech_unlocked_scans_past_non_matching_unlocks():
    from bunnyland.simpacks.voidsim.mechanics import _tech_unlocked

    scenario = build_scenario()
    world = scenario.actor.world
    _unlock_tech(scenario, "unrelated-tech")
    # The only unlock present does not match, so the loop iterates past it (covers 1069->1068)
    # and falls through to return False.
    assert _tech_unlocked(world, "shield-tech") is False
    # An empty required tech is treated as always available without scanning.
    assert _tech_unlocked(world, "") is True
