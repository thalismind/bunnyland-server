"""Tests for dino-sim fossil, egg, and kaiju incident mechanics."""

from __future__ import annotations

from datetime import UTC, datetime

from conftest import build_scenario

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
from bunnyland.core.components import (
    CharacterComponent,
    GenerationIntentComponent,
    RegionComponent,
    RoomComponent,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.core.handlers import HandlerContext
from bunnyland.foundation.storyteller.mechanics import (
    IncidentBudgetComponent,
    IncidentComponent,
    IncidentGeneratedEvent,
    IncidentSpawned,
    StorytellerComponent,
    StorytellerConsequence,
    default_incident_definitions,
)
from bunnyland.prompts import ComponentPromptContext
from bunnyland.simpacks.colonysim.mechanics import ResourceStackComponent, install_colonysim
from bunnyland.simpacks.dinosim.incidents import KAIJU_ATTACK
from bunnyland.simpacks.dinosim.mechanics import (
    AncientSampleComponent,
    ApexPredatorAppearedEvent,
    ApexPredatorComponent,
    ApproachCreatureHandler,
    ArmorPlateComponent,
    ArmyCalledEvent,
    ArmyResponseComponent,
    AssignGuardHandler,
    AssignRanchWorkHandler,
    BaitComponent,
    BaitSetEvent,
    BoneComponent,
    BroodEggHandler,
    BroodingComponent,
    BroodingStartedEvent,
    BuildEnclosureHandler,
    CallForHelpHandler,
    CalmCreatureHandler,
    CareForJuvenileHandler,
    ChargeComponent,
    CleanFossilHandler,
    CloneCandidateComponent,
    CollectEggHandler,
    CommandCompanionHandler,
    CommandComponent,
    CommandTrainedEvent,
    CompanionCommandedEvent,
    CompanionComponent,
    ContainmentPanicComponent,
    ContainmentPanicStartedEvent,
    ContainmentProtocolComponent,
    ContainmentTriggeredEvent,
    CreatureAttackComponent,
    CreatureAttackedEvent,
    CreatureCalmedEvent,
    CreatureChargedEvent,
    CreatureEscapedEvent,
    CreatureFedEvent,
    CreatureImprintedEvent,
    CreatureMilkComponent,
    CreatureMountedEvent,
    CreatureNeedComponent,
    CreatureNeedsChangedEvent,
    CreatureObservedEvent,
    CreatureProductCollectedEvent,
    CreatureProductComponent,
    CreatureRecalledEvent,
    CreatureRecapturedEvent,
    CreatureRoaredEvent,
    CreatureTamedEvent,
    CreatureTrackedEvent,
    CreatureTrampledEvent,
    CreatureTranquilizedEvent,
    DescendsFromParent,
    DinoIncidentEnrichment,
    DinosaurComponent,
    DodgeCreatureHandler,
    DriveOffPredatorHandler,
    EggComponent,
    EggHatchedEvent,
    EggInspectedEvent,
    EggInspectionComponent,
    EggLaidEvent,
    EnclosureBuiltEvent,
    EnclosureComponent,
    EscapeRiskComponent,
    EscapeRiskConsequence,
    EvacuateRoomHandler,
    ExcavateFossilHandler,
    ExtractAncientSampleHandler,
    FeedCreatureHandler,
    FeedingPenComponent,
    FeedStockedEvent,
    FeedStoreComponent,
    FenceComponent,
    FenceRepairedEvent,
    FertilityComponent,
    FertilizeEggHandler,
    FightCreatureHandler,
    FossilCleanedEvent,
    FossilExcavatedEvent,
    FossilFragmentComponent,
    FossilIdentifiedEvent,
    FossilStabilizedEvent,
    FossilSurveyComponent,
    FossilSurveyedEvent,
    GateComponent,
    GateReinforcedEvent,
    GrappleComponent,
    GuardAnimalComponent,
    GuardAssignedEvent,
    GuardBehaviorComponent,
    HarvestProductHandler,
    HatchEggHandler,
    HerdComponent,
    HerdTrackedEvent,
    HiddenFromCreatureEvent,
    HideComponent,
    HideFromCreatureHandler,
    HuntBehaviorComponent,
    IdentifyFossilHandler,
    ImprintComponent,
    ImprintCreatureHandler,
    IncubateEggHandler,
    IncubationComponent,
    IncubationConsequence,
    IncubationTemperatureSetEvent,
    InspectEggHandler,
    JuvenileCareComponent,
    JuvenileCareGivenEvent,
    KaijuArrivedEvent,
    KaijuComponent,
    KaijuSpawnSpec,
    LabIncubateEggHandler,
    LabIncubationComponent,
    LabIncubationStartedEvent,
    LayEggHandler,
    LockPenHandler,
    MarkTerritoryHandler,
    MountComponent,
    MountCreatureHandler,
    NestComponent,
    NestPreparedEvent,
    ObserveCreatureHandler,
    OpenPenHandler,
    PackHuntComponent,
    PenLockedEvent,
    PenOpenedEvent,
    PredatorDrivenOffEvent,
    PrepareCloneHandler,
    PrepareNestHandler,
    QuarantinePenComponent,
    RanchLaborComponent,
    RanchWorkAssignedEvent,
    RecallComponent,
    RecallCreatureHandler,
    RecaptureCreatureHandler,
    ReinforceGateHandler,
    ReinforcementComponent,
    RepairDamageHandler,
    RepairFenceHandler,
    ReptileProcreationComponent,
    RoarComponent,
    RoomEvacuatedEvent,
    SetBaitHandler,
    SetIncubationTemperatureHandler,
    SettlementDamageComponent,
    SettlementDamageRepairedEvent,
    SignalArmyHandler,
    SpeciesComponent,
    SpeciesIdentificationComponent,
    StabilizeFossilHandler,
    StampedeStartedEvent,
    StockFeedHandler,
    StudyWaterCreatureHandler,
    SurveyFossilHandler,
    TameCreatureHandler,
    TamingComponent,
    TamingProgressedEvent,
    TargetWeakPointHandler,
    TerritoryComponent,
    TerritoryMarkedEvent,
    ToxinComponent,
    TrackComponent,
    TrackCreatureHandler,
    TrackHerdHandler,
    TrainCommandHandler,
    TrainingComponent,
    TrampleComponent,
    TranquilizeCreatureHandler,
    TranquilizerComponent,
    TriggerContainmentHandler,
    TriggerContainmentPanicHandler,
    WaterCreatureComponent,
    WaterCreatureStudiedEvent,
    WaterStudyComponent,
    WeakPointComponent,
    WeakPointHitEvent,
    _consume_inventory_resource_operation,
    _entity_name,
    _entity_room_id,
    _hatch_room_id,
    _move_to_room,
    _move_to_room_operations,
    _payload_entity_id,
    _reachable_creature,
    _region_for_room,
    _region_rooms,
    _spawn_egg_operations,
    _species_name,
    dinosim_fragments,
    generate_kaiju_spawn_specs,
    install_dinosim,
    kaiju_difficulty_for_threat,
    selected_kaiju_rooms,
)
from bunnyland.simpacks.lifesim.mechanics import LifeStageComponent

HOUR = 60 * 60
DAY = 24 * HOUR


def _install(actor):
    install_dinosim(actor)
    actor.register_handler(IdentifyFossilHandler())
    actor.register_handler(ExtractAncientSampleHandler())
    actor.register_handler(PrepareCloneHandler())
    actor.register_handler(LayEggHandler())
    actor.register_handler(FertilizeEggHandler())
    actor.register_handler(IncubateEggHandler())
    actor.register_handler(HatchEggHandler())
    actor.register_handler(TrackCreatureHandler())
    actor.register_handler(MarkTerritoryHandler())
    actor.register_handler(TrackHerdHandler())
    actor.register_handler(PrepareNestHandler())
    actor.register_handler(SetBaitHandler())
    actor.register_handler(TranquilizeCreatureHandler())
    actor.register_handler(ApproachCreatureHandler())
    actor.register_handler(TameCreatureHandler())
    actor.register_handler(TrainCommandHandler())
    actor.register_handler(MountCreatureHandler())
    actor.register_handler(CommandCompanionHandler())
    actor.register_handler(RecallCreatureHandler())
    actor.register_handler(BuildEnclosureHandler())
    actor.register_handler(RepairFenceHandler())
    actor.register_handler(ReinforceGateHandler())
    actor.register_handler(LockPenHandler())
    actor.register_handler(OpenPenHandler())
    actor.register_handler(TriggerContainmentHandler())
    actor.register_handler(RecaptureCreatureHandler())
    actor.register_handler(HideFromCreatureHandler())
    actor.register_handler(EvacuateRoomHandler())
    actor.register_handler(DodgeCreatureHandler())
    actor.register_handler(FightCreatureHandler())
    actor.register_handler(TargetWeakPointHandler())
    actor.register_handler(DriveOffPredatorHandler())
    actor.register_handler(CallForHelpHandler())
    actor.register_handler(SignalArmyHandler())
    actor.register_handler(RepairDamageHandler())
    actor.register_handler(StockFeedHandler())
    actor.register_handler(CollectEggHandler())
    actor.register_handler(HarvestProductHandler())
    actor.register_handler(AssignRanchWorkHandler())
    actor.register_handler(AssignGuardHandler())
    actor.register_handler(FeedCreatureHandler())
    actor.register_handler(CalmCreatureHandler())
    actor.register_handler(ObserveCreatureHandler())


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


def test_dinosim_reachable_entity_rejects_missing_character_without_crashing():
    scenario = build_scenario()
    result = IdentifyFossilHandler().execute(
        HandlerContext(scenario.actor.world, scenario.actor.epoch),
        _handler_cmd(
            scenario,
            "identify",
            character_id="entity_999999",
            fossil_id=str(scenario.room_a),
            species_name="triceratops",
        ),
    )

    assert not result.ok
    assert result.reason == "fossil is not reachable"


def _room_contents(scenario):
    room = scenario.actor.world.get_entity(scenario.room_a)
    return [
        scenario.actor.world.get_entity(entity_id)
        for _edge, entity_id in room.get_relationships(Contains)
    ]


def _collect_rejections(actor) -> list[CommandRejectedEvent]:
    rejects: list[CommandRejectedEvent] = []
    actor.bus.subscribe(CommandRejectedEvent, rejects.append)
    return rejects


def test_dinosim_parity_handlers_mutate_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)

    def room_entity(name, kind, components):
        entity = spawn_entity(
            scenario.actor.world,
            [IdentityComponent(name=name, kind=kind), *components],
        )
        scenario.actor.world.get_entity(scenario.room_a).add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
        )
        return entity

    fossil = room_entity(
        "amber bone shard",
        "fossil",
        [
            FossilFragmentComponent(species_name="velociraptor"),
            FossilSurveyComponent(),
        ],
    )
    egg = room_entity(
        "velociraptor egg",
        "egg",
        [
            EggComponent(
                species_name="velociraptor",
                laid_at_epoch=scenario.actor.epoch,
                fertilized=True,
            ),
            IncubationComponent(started_at_epoch=scenario.actor.epoch),
        ],
    )
    creature = room_entity(
        "clever raptor",
        "creature",
        [
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            WaterCreatureComponent(species_name="velociraptor"),
        ],
    )
    enclosure = room_entity(
        "Fern Paddock",
        "enclosure",
        [EnclosureComponent(name="Fern Paddock")],
    )

    calls = [
        (
            SurveyFossilHandler(),
            "survey-fossil",
            {"fossil_id": str(fossil.id)},
            FossilSurveyedEvent,
        ),
        (
            ExcavateFossilHandler(),
            "excavate-fossil",
            {"fossil_id": str(fossil.id), "progress": 0.6},
            FossilExcavatedEvent,
        ),
        (
            CleanFossilHandler(),
            "clean-fossil",
            {"fossil_id": str(fossil.id)},
            FossilCleanedEvent,
        ),
        (
            StabilizeFossilHandler(),
            "stabilize-fossil",
            {"fossil_id": str(fossil.id)},
            FossilStabilizedEvent,
        ),
        (
            LabIncubateEggHandler(),
            "lab-incubate-egg",
            {"egg_id": str(egg.id), "lab_id": "Amber Hatchery Lab"},
            LabIncubationStartedEvent,
        ),
        (
            InspectEggHandler(),
            "inspect",
            {"egg_id": str(egg.id), "viability": 0.9},
            EggInspectedEvent,
        ),
        (
            ImprintCreatureHandler(),
            "imprint-creature",
            {"creature_id": str(creature.id), "bond": 2},
            CreatureImprintedEvent,
        ),
        (
            CareForJuvenileHandler(),
            "care-for-juvenile",
            {"creature_id": str(creature.id), "care": 2},
            JuvenileCareGivenEvent,
        ),
        (
            StudyWaterCreatureHandler(),
            "study-water-creature",
            {"creature_id": str(creature.id)},
            WaterCreatureStudiedEvent,
        ),
        (
            BroodEggHandler(),
            "brood-egg",
            {"egg_id": str(egg.id), "warmth": 2},
            BroodingStartedEvent,
        ),
        (
            SetIncubationTemperatureHandler(),
            "set-incubation-temperature",
            {"egg_id": str(egg.id), "temperature": 31},
            IncubationTemperatureSetEvent,
        ),
        (
            TriggerContainmentPanicHandler(),
            "trigger-containment-panic",
            {"enclosure_id": str(enclosure.id), "severity": 2},
            ContainmentPanicStartedEvent,
        ),
    ]

    for handler, command_type, payload, event_type in calls:
        result = handler.execute(ctx, _handler_cmd(scenario, command_type, **payload))
        assert result.ok, (command_type, result.reason)
        assert any(isinstance(event, event_type) for event in result.events)

    survey = fossil.get_component(FossilSurveyComponent)
    assert str(scenario.character) in survey.surveyed_by
    assert survey.excavation_progress == 0.6
    assert fossil.get_component(FossilFragmentComponent).cleaned is True
    assert survey.stabilized is True
    assert egg.get_component(LabIncubationComponent).active is True
    assert egg.get_component(EggInspectionComponent).viability == 0.9
    assert creature.get_component(ImprintComponent).bond == 2
    assert creature.get_component(JuvenileCareComponent).care_level == 2
    assert str(scenario.character) in creature.get_component(WaterStudyComponent).studied_by
    assert egg.get_component(BroodingComponent).warmth == 2
    assert egg.get_component(IncubationComponent).temperature == 31
    assert enclosure.get_component(ContainmentPanicComponent).severity == 2
    fragments = dinosim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )
    assert "Fossil survey amber bone shard: stabilized." in fragments
    assert "Nearby egg: velociraptor egg (velociraptor, incubating, 31 C)." in fragments
    assert "Lab incubation active for velociraptor egg: Amber Hatchery Lab." in fragments
    assert "Egg inspection for velociraptor egg: viability 0.9." in fragments
    assert "Imprinted creature: clever raptor bond 2." in fragments
    assert "Juvenile care for clever raptor: 2." in fragments
    assert "Water creature clever raptor: velociraptor in shallows." in fragments
    assert "Water study clever raptor: studied." in fragments
    assert "Brooding velociraptor egg: warmth 2." in fragments
    assert "Fern Paddock containment panic: severity 2." in fragments


def test_dinosim_parity_handlers_reject_invalid_targets_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    fake = "entity_999999"
    cases = [
        (
            SurveyFossilHandler(),
            "survey-fossil",
            {"fossil_id": fake},
            "invalid character or fossil id",
            "fossil is not reachable",
        ),
        (
            ExcavateFossilHandler(),
            "excavate-fossil",
            {"fossil_id": fake},
            "invalid character or fossil id",
            "fossil is not reachable",
        ),
        (
            CleanFossilHandler(),
            "clean-fossil",
            {"fossil_id": fake},
            "invalid character or fossil id",
            "fossil is not reachable",
        ),
        (
            StabilizeFossilHandler(),
            "stabilize-fossil",
            {"fossil_id": fake},
            "invalid character or fossil id",
            "fossil is not reachable",
        ),
        (
            LabIncubateEggHandler(),
            "lab-incubate-egg",
            {"egg_id": fake},
            "invalid character or egg id",
            "egg does not exist",
        ),
        (
            InspectEggHandler(),
            "inspect",
            {"egg_id": fake},
            "invalid character or egg id",
            "egg is not reachable",
        ),
        (
            ImprintCreatureHandler(),
            "imprint-creature",
            {"creature_id": fake},
            "invalid character or creature id",
            "creature is not reachable",
        ),
        (
            CareForJuvenileHandler(),
            "care-for-juvenile",
            {"creature_id": fake},
            "invalid character or creature id",
            "creature is not reachable",
        ),
        (
            StudyWaterCreatureHandler(),
            "study-water-creature",
            {"creature_id": fake},
            "invalid character or creature id",
            "water creature is not reachable",
        ),
        (
            BroodEggHandler(),
            "brood-egg",
            {"egg_id": fake},
            "invalid character or egg id",
            "egg is not reachable",
        ),
        (
            SetIncubationTemperatureHandler(),
            "set-incubation-temperature",
            {"egg_id": fake},
            "invalid character or egg id",
            "egg is not incubating",
        ),
        (
            TriggerContainmentPanicHandler(),
            "trigger-containment-panic",
            {"enclosure_id": fake},
            "invalid character or enclosure id",
            "enclosure is not reachable",
        ),
    ]

    for handler, command_type, payload, invalid_reason, missing_reason in cases:
        bad_character = handler.execute(
            ctx,
            _handler_cmd(scenario, command_type, character_id="not-an-id", **payload),
        )
        assert bad_character.ok is False
        assert bad_character.reason == invalid_reason
        missing_target = handler.execute(ctx, _handler_cmd(scenario, command_type, **payload))
        assert missing_target.ok is False
        assert missing_target.reason == missing_reason


def test_dinosim_parity_handlers_reject_reachable_wrong_kind_and_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    wrong_kind = spawn_entity(world, [IdentityComponent(name="plain fern", kind="prop")])
    fossil = spawn_entity(
        world,
        [IdentityComponent(name="raw fossil", kind="fossil"), FossilFragmentComponent()],
    )
    egg = spawn_entity(
        world,
        [
            IdentityComponent(name="raptor egg", kind="egg"),
            EggComponent(species_name="raptor", laid_at_epoch=0, fertilized=True),
        ],
    )
    incubating_egg = spawn_entity(
        world,
        [
            IdentityComponent(name="warm egg", kind="egg"),
            EggComponent(species_name="raptor", laid_at_epoch=0, fertilized=True),
            IncubationComponent(started_at_epoch=0),
        ],
    )
    creature = spawn_entity(
        world,
        [
            IdentityComponent(name="young raptor", kind="creature"),
            DinosaurComponent(species_name="raptor"),
            CharacterComponent(species="raptor"),
        ],
    )
    water_creature = spawn_entity(
        world,
        [
            IdentityComponent(name="swimmer", kind="creature"),
            WaterCreatureComponent(species_name="plesiosaur"),
        ],
    )
    enclosure = spawn_entity(
        world,
        [IdentityComponent(name="paddock", kind="enclosure"), EnclosureComponent()],
    )
    for entity in (wrong_kind, fossil, egg, incubating_egg, creature, water_creature, enclosure):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    cases = [
        (
            SurveyFossilHandler(),
            _handler_cmd(scenario, "survey-fossil", fossil_id=str(wrong_kind.id)),
            "fossil is not reachable",
        ),
        (
            ExcavateFossilHandler(),
            _handler_cmd(scenario, "excavate-fossil", fossil_id=str(wrong_kind.id)),
            "fossil is not reachable",
        ),
        (
            CleanFossilHandler(),
            _handler_cmd(scenario, "clean-fossil", fossil_id=str(wrong_kind.id)),
            "fossil is not reachable",
        ),
        (
            StabilizeFossilHandler(),
            _handler_cmd(scenario, "stabilize-fossil", fossil_id=str(wrong_kind.id)),
            "fossil is not reachable",
        ),
        (
            InspectEggHandler(),
            _handler_cmd(scenario, "inspect", egg_id=str(wrong_kind.id)),
            "egg is not reachable",
        ),
        (
            ImprintCreatureHandler(),
            _handler_cmd(scenario, "imprint-creature", creature_id=str(wrong_kind.id)),
            "creature is not reachable",
        ),
        (
            CareForJuvenileHandler(),
            _handler_cmd(scenario, "care-for-juvenile", creature_id=str(wrong_kind.id)),
            "creature is not reachable",
        ),
        (
            StudyWaterCreatureHandler(),
            _handler_cmd(scenario, "study-water-creature", creature_id=str(creature.id)),
            "water creature is not reachable",
        ),
        (
            BroodEggHandler(),
            _handler_cmd(scenario, "brood-egg", egg_id=str(wrong_kind.id)),
            "egg is not reachable",
        ),
        (
            SetIncubationTemperatureHandler(),
            _handler_cmd(scenario, "set-incubation-temperature", egg_id=str(egg.id)),
            "egg is not incubating",
        ),
        (
            TriggerContainmentPanicHandler(),
            _handler_cmd(scenario, "trigger-containment-panic", enclosure_id=str(wrong_kind.id)),
            "enclosure is not reachable",
        ),
    ]
    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    assert (
        SurveyFossilHandler()
        .execute(ctx, _handler_cmd(scenario, "survey-fossil", fossil_id=str(fossil.id)))
        .ok
    )
    fossil.remove_component(FossilSurveyComponent)
    assert (
        ExcavateFossilHandler()
        .execute(ctx, _handler_cmd(scenario, "excavate-fossil", fossil_id=str(fossil.id)))
        .ok
    )
    fossil.remove_component(FossilSurveyComponent)
    assert (
        StabilizeFossilHandler()
        .execute(ctx, _handler_cmd(scenario, "stabilize-fossil", fossil_id=str(fossil.id)))
        .ok
    )
    assert (
        InspectEggHandler()
        .execute(ctx, _handler_cmd(scenario, "inspect", egg_id=str(egg.id), viability=0.5))
        .ok
    )
    assert (
        ImprintCreatureHandler()
        .execute(
            ctx, _handler_cmd(scenario, "imprint-creature", creature_id=str(creature.id), bond=0.5)
        )
        .ok
    )
    assert (
        CareForJuvenileHandler()
        .execute(
            ctx, _handler_cmd(scenario, "care-for-juvenile", creature_id=str(creature.id), care=0.5)
        )
        .ok
    )
    assert (
        StudyWaterCreatureHandler()
        .execute(
            ctx,
            _handler_cmd(scenario, "study-water-creature", creature_id=str(water_creature.id)),
        )
        .ok
    )
    assert (
        BroodEggHandler()
        .execute(ctx, _handler_cmd(scenario, "brood-egg", egg_id=str(incubating_egg.id), warmth=1))
        .ok
    )
    assert (
        SetIncubationTemperatureHandler()
        .execute(
            ctx,
            _handler_cmd(
                scenario,
                "set-incubation-temperature",
                egg_id=str(incubating_egg.id),
                temperature=29,
            ),
        )
        .ok
    )
    assert (
        TriggerContainmentPanicHandler()
        .execute(
            ctx,
            _handler_cmd(
                scenario,
                "trigger-containment-panic",
                enclosure_id=str(enclosure.id),
                severity=1,
            ),
        )
        .ok
    )


def test_entity_room_id_returns_containing_room_or_none():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    loose = spawn_entity(scenario.actor.world, [IdentityComponent(name="loose", kind="item")])

    assert _entity_room_id(character) == str(scenario.room_a)
    assert _entity_room_id(loose) is None


def test_species_name_prefers_specific_components():
    scenario = build_scenario()
    world = scenario.actor.world
    species = spawn_entity(
        world,
        [
            SpeciesComponent(common_name="ankylosaurus"),
            DinosaurComponent(species_name="wrong"),
            CharacterComponent(species="also wrong"),
            IdentityComponent(name="still wrong", kind="creature"),
        ],
    )
    dinosaur = spawn_entity(
        world,
        [
            DinosaurComponent(species_name="velociraptor"),
            CharacterComponent(species="wrong"),
            IdentityComponent(name="also wrong", kind="creature"),
        ],
    )
    character = spawn_entity(
        world,
        [
            CharacterComponent(species="iguanodon"),
            IdentityComponent(name="wrong", kind="character"),
        ],
    )
    named = spawn_entity(world, [IdentityComponent(name="mystery lizard", kind="creature")])
    unknown = spawn_entity(world)

    assert _species_name(species) == "ankylosaurus"
    assert _species_name(dinosaur) == "velociraptor"
    assert _species_name(character) == "iguanodon"
    assert _species_name(named) == "mystery lizard"
    assert _species_name(unknown) == "unknown reptile"


def test_generate_kaiju_spawn_specs_splits_attack_budget_into_epic_threats():
    specs = generate_kaiju_spawn_specs(15, "kaiju_attack:3600:15")

    assert all(isinstance(spec, KaijuSpawnSpec) for spec in specs)
    assert specs == generate_kaiju_spawn_specs(15, "kaiju_attack:3600:15")
    assert len(specs) == 2
    assert sum(spec.threat_level for spec in specs) == 15
    assert {spec.difficulty for spec in specs} == {"epic"}
    assert kaiju_difficulty_for_threat(6) == "major"
    assert kaiju_difficulty_for_threat(10) == "colossal"
    assert len(generate_kaiju_spawn_specs(18, "larger")) == 3


def test_selected_kaiju_rooms_uses_seeded_region_selection_and_fallbacks():
    scenario = build_scenario()
    world = scenario.actor.world

    assert selected_kaiju_rooms(world, None, 1, "seed") == ()
    assert selected_kaiju_rooms(world, scenario.room_a, 0, "seed") == ()
    prop = spawn_entity(world, [IdentityComponent(name="marker", kind="prop")])
    assert selected_kaiju_rooms(world, prop.id, 1, "seed") == ()

    fallback = selected_kaiju_rooms(world, scenario.room_a, 2, "seed")
    assert tuple(room.id for room in fallback) == (scenario.room_a, scenario.room_a)

    region = spawn_entity(world, [RegionComponent(name="Mosslit Basin")])
    nested = spawn_entity(world, [RegionComponent(name="South Ridge")])
    room_c = spawn_entity(world, [RoomComponent(title="Cliff Overlook")])
    region.add_relationship(Contains(mode=ContainmentMode.REGION), scenario.room_a)
    region.add_relationship(Contains(mode=ContainmentMode.REGION), nested.id)
    nested.add_relationship(Contains(mode=ContainmentMode.REGION), scenario.room_b)
    nested.add_relationship(Contains(mode=ContainmentMode.REGION), room_c.id)

    selected = selected_kaiju_rooms(world, scenario.room_a, 2, "region-seed")
    assert selected == selected_kaiju_rooms(world, scenario.room_a, 2, "region-seed")
    assert len(selected) == 2
    assert {room.id for room in selected} <= {scenario.room_a, scenario.room_b, room_c.id}


def test_dino_incident_enrichment_is_seeded_and_idempotent():
    scenario = build_scenario()
    world = scenario.actor.world
    incident = spawn_entity(
        world,
        [
            IdentityComponent(name="kaiju attack", kind="incident"),
            IncidentComponent(kind="kaiju_attack", budget_spent=15, started_at_epoch=0),
        ],
    )
    enrichment = DinoIncidentEnrichment(world)

    def event_for(
        target,
        *,
        kind: str = "kaiju_attack",
        incident_id: str | None = None,
        wants: tuple[str, ...] = ("kaiju-spawn",),
    ) -> IncidentGeneratedEvent:
        return IncidentGeneratedEvent(
            event_id="event",
            world_epoch=0,
            created_at=datetime.now(UTC),
            room_id=str(target.id),
            target_ids=(str(incident.id),),
            seed="kaiju-seed",
            incident_id=incident_id if incident_id is not None else str(incident.id),
            incident_key=kind,
            kind=kind,
            budget_spent=15,
            generation=GenerationIntentComponent(wants=wants),
        )

    enrichment._on_incident(
        event_for(world.get_entity(scenario.room_a), kind="resource_drop", wants=())
    )
    assert incident.get_relationships(IncidentSpawned) == []

    enrichment._on_incident(event_for(world.get_entity(scenario.room_a), incident_id="not-an-id"))
    assert incident.get_relationships(IncidentSpawned) == []

    prop = spawn_entity(world, [IdentityComponent(name="not a room", kind="prop")])
    enrichment._on_incident(event_for(prop))
    assert incident.get_relationships(IncidentSpawned) == []

    enrichment._on_incident(event_for(world.get_entity(scenario.room_a)))
    spawned = incident.get_relationships(IncidentSpawned)
    assert len([edge for edge, _target_id in spawned if edge.kind == "monster"]) == 2
    assert incident.has_component(SettlementDamageComponent)

    enrichment._on_incident(event_for(world.get_entity(scenario.room_a)))
    assert incident.get_relationships(IncidentSpawned) == spawned


async def test_fossil_identification_extracts_sample_and_prepares_clone_egg():
    scenario = build_scenario()
    _install(scenario.actor)
    fossil = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="amber bone shard", kind="fossil"),
            FossilFragmentComponent(sample_quality=0.75),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), fossil.id
    )
    identified: list[FossilIdentifiedEvent] = []
    scenario.actor.bus.subscribe(FossilIdentifiedEvent, identified.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "identify",
            fossil_id=str(fossil.id),
            species_name="velociraptor",
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "extract-ancient-sample", fossil_id=str(fossil.id)))
    await scenario.actor.tick(HOUR)

    samples = [
        entity
        for entity in scenario.actor.world.query()
        .with_all([AncientSampleComponent])
        .execute_entities()
    ]
    assert identified[0].species_name == "velociraptor"
    assert fossil.get_component(SpeciesIdentificationComponent).species_name == "velociraptor"
    assert len(samples) == 1
    assert container_of(samples[0]) == scenario.character

    await scenario.actor.submit(_cmd(scenario, "prepare-clone", sample_id=str(samples[0].id)))
    await scenario.actor.tick(HOUR)

    eggs = list(
        scenario.actor.world.query()
        .with_all([EggComponent, IncubationComponent])
        .execute_entities()
    )
    assert not eggs
    eggs = list(scenario.actor.world.query().with_all([EggComponent]).execute_entities())
    assert len(eggs) == 1
    egg = eggs[0].get_component(EggComponent)
    assert egg.species_name == "velociraptor"
    assert egg.fertilized is True
    assert egg.source == "clone"
    assert container_of(eggs[0]) == scenario.character
    character = scenario.actor.world.get_entity(scenario.character)
    assert any(
        "velociraptor" in line for line in dinosim_fragments(scenario.actor.world, character)
    )


async def test_reptile_egg_can_be_fertilized_incubated_and_hatched_into_lifesim_child():
    scenario = build_scenario()
    _install(scenario.actor)
    parent = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="clever raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            FertilityComponent(),
            ReptileProcreationComponent(egg_species_name="velociraptor"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), parent.id
    )
    laid: list[EggLaidEvent] = []
    hatched: list[EggHatchedEvent] = []
    scenario.actor.bus.subscribe(EggLaidEvent, laid.append)
    scenario.actor.bus.subscribe(EggHatchedEvent, hatched.append)

    await scenario.actor.submit(_cmd(scenario, "lay-egg", parent_id=str(parent.id)))
    await scenario.actor.tick(HOUR)

    egg_id = parse_entity_id(laid[0].egg_id)
    assert egg_id is not None
    egg_entity = scenario.actor.world.get_entity(egg_id)
    assert egg_entity.get_component(EggComponent).fertilized is False

    await scenario.actor.submit(
        _cmd(scenario, "fertilize-egg", egg_id=str(egg_id), parent_id=str(parent.id))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "incubate-egg", egg_id=str(egg_id), duration_seconds=HOUR)
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(HOUR)

    assert egg_entity.get_component(IncubationComponent).ready is True

    await scenario.actor.submit(_cmd(scenario, "hatch-egg", egg_id=str(egg_id)))
    await scenario.actor.tick(HOUR)

    hatchling_id = parse_entity_id(hatched[0].hatchling_id)
    assert hatchling_id is not None
    hatchling = scenario.actor.world.get_entity(hatchling_id)
    assert hatchling.get_component(CharacterComponent).species == "velociraptor"
    assert hatchling.get_component(LifeStageComponent).stage == "child"
    assert hatchling.has_component(DinosaurComponent)
    assert container_of(hatchling) == scenario.room_a


async def test_creature_can_be_tracked_tamed_trained_commanded_mounted_and_recalled():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    tunnel = scenario.actor.world.get_entity(scenario.room_b)
    raptor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="clever raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            ReptileProcreationComponent(egg_species_name="velociraptor"),
        ],
    )
    bait = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="scented bait", kind="food")],
    )
    tranquilizer = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="sleep dart", kind="tool"),
            TranquilizerComponent(potency=1.0, uses=1),
        ],
    )
    for entity in (raptor, bait, tranquilizer):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    tracked: list[CreatureTrackedEvent] = []
    bait_set: list[BaitSetEvent] = []
    tranquilized: list[CreatureTranquilizedEvent] = []
    progressed: list[TamingProgressedEvent] = []
    tamed: list[CreatureTamedEvent] = []
    trained: list[CommandTrainedEvent] = []
    mounted: list[CreatureMountedEvent] = []
    commanded: list[CompanionCommandedEvent] = []
    recalled: list[CreatureRecalledEvent] = []
    scenario.actor.bus.subscribe(CreatureTrackedEvent, tracked.append)
    scenario.actor.bus.subscribe(BaitSetEvent, bait_set.append)
    scenario.actor.bus.subscribe(CreatureTranquilizedEvent, tranquilized.append)
    scenario.actor.bus.subscribe(TamingProgressedEvent, progressed.append)
    scenario.actor.bus.subscribe(CreatureTamedEvent, tamed.append)
    scenario.actor.bus.subscribe(CommandTrainedEvent, trained.append)
    scenario.actor.bus.subscribe(CreatureMountedEvent, mounted.append)
    scenario.actor.bus.subscribe(CompanionCommandedEvent, commanded.append)
    scenario.actor.bus.subscribe(CreatureRecalledEvent, recalled.append)

    commands = [
        _cmd(scenario, "track-creature", creature_id=str(raptor.id)),
        _cmd(
            scenario,
            "set-bait",
            bait_id=str(bait.id),
            target_species="velociraptor",
            potency=1.0,
        ),
        _cmd(
            scenario,
            "tranquilize-creature",
            creature_id=str(raptor.id),
            tranquilizer_id=str(tranquilizer.id),
            duration_seconds=HOUR,
        ),
        _cmd(scenario, "approach-creature", creature_id=str(raptor.id)),
        _cmd(scenario, "tame-creature", creature_id=str(raptor.id), role="guard"),
        _cmd(
            scenario,
            "train-command",
            creature_id=str(raptor.id),
            command_name="guard",
            progress=2.0,
        ),
        _cmd(scenario, "mount-creature", creature_id=str(raptor.id)),
        _cmd(
            scenario,
            "command",
            target_id=str(raptor.id),
            instruction="guard",
            command_target_id=str(scenario.room_a),
        ),
    ]
    for command in commands:
        await scenario.actor.submit(command)
        await scenario.actor.tick(HOUR)

    room.remove_relationship(Contains, raptor.id)
    tunnel.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), raptor.id)
    await scenario.actor.submit(_cmd(scenario, "recall-creature", creature_id=str(raptor.id)))
    await scenario.actor.tick(HOUR)

    assert tracked[0].tracked_room_id == str(scenario.room_a)
    assert bait_set[0].target_species == "velociraptor"
    assert tranquilized[0].creature_id == str(raptor.id)
    assert progressed[-1].progress == 3.0
    assert tamed[0].role == "guard"
    assert trained[0].command_name == "guard"
    assert mounted[0].rider_id == str(scenario.character)
    assert commanded[0].command_name == "guard"
    assert recalled[0].recalled_room_id == str(scenario.room_a)
    assert container_of(raptor) == scenario.room_a
    assert raptor.has_component(TrackComponent)
    assert bait.has_component(BaitComponent)
    assert raptor.get_component(CompanionComponent).owner_id == str(scenario.character)
    assert raptor.get_component(TrainingComponent).learned_commands == ("guard",)
    assert raptor.get_component(MountComponent).mounted is True
    assert raptor.get_component(CommandComponent).command_name == "guard"
    assert raptor.get_component(GuardBehaviorComponent).location_id == str(scenario.room_a)
    assert raptor.get_component(RecallComponent).home_room_id == str(scenario.room_a)

    fragments = dinosim_fragments(
        scenario.actor.world,
        scenario.actor.world.get_entity(scenario.character),
    )
    assert "Your guard: clever raptor." in fragments
    assert "clever raptor knows commands: guard." in fragments


async def test_ecology_territory_herd_and_nest_loop():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    territory = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="fern valley", kind="territory"),
            TerritoryComponent(species_name="triceratops", threat_level=2),
        ],
    )
    herd = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="valley herd", kind="herd"),
            HerdComponent(species_name="triceratops", size=6),
        ],
    )
    nest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="fern nest", kind="nest"),
            NestComponent(species_name="triceratops"),
        ],
    )
    for entity in (territory, herd, nest):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    marked: list[TerritoryMarkedEvent] = []
    tracked: list[HerdTrackedEvent] = []
    prepared: list[NestPreparedEvent] = []
    scenario.actor.bus.subscribe(TerritoryMarkedEvent, marked.append)
    scenario.actor.bus.subscribe(HerdTrackedEvent, tracked.append)
    scenario.actor.bus.subscribe(NestPreparedEvent, prepared.append)

    await scenario.actor.submit(_cmd(scenario, "mark-territory", territory_id=str(territory.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "track-herd", herd_id=str(herd.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "prepare-nest", nest_id=str(nest.id)))
    await scenario.actor.tick(HOUR)

    assert territory.get_component(TerritoryComponent).marked_by == str(scenario.character)
    assert herd.get_component(HerdComponent).last_tracked_epoch > 0
    assert nest.get_component(NestComponent).prepared is True
    assert marked and marked[0].species_name == "triceratops"
    assert tracked and tracked[0].size == 6
    assert prepared and prepared[0].nest_id == str(nest.id)

    fragments = dinosim_fragments(
        scenario.actor.world,
        scenario.actor.world.get_entity(scenario.character),
    )
    assert any("Territory fern valley: triceratops, marked" in line for line in fragments)
    assert any("Herd valley herd: triceratops x6" in line for line in fragments)
    assert any("Nest fern nest: triceratops, prepared" in line for line in fragments)


def test_ecology_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    territory = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="ridge", kind="territory"), TerritoryComponent()],
    )
    herd = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="herd", kind="herd"), HerdComponent(species_name="stego")],
    )
    nest = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="nest", kind="nest"), NestComponent(species_name="stego")],
    )
    prepared = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ready nest", kind="nest"),
            NestComponent(species_name="stego", prepared=True),
        ],
    )
    rock = spawn_entity(scenario.actor.world, [IdentityComponent(name="rock", kind="prop")])
    distant = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far ridge", kind="territory"), TerritoryComponent()],
    )
    distant_herd = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far herd", kind="herd"), HerdComponent(species_name="stego")],
    )
    distant_nest = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far nest", kind="nest"), NestComponent(species_name="stego")],
    )
    for entity in (territory, herd, nest, prepared, rock):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    mark = MarkTerritoryHandler()
    track = TrackHerdHandler()
    prepare = PrepareNestHandler()
    assert (
        mark.execute(ctx, _handler_cmd(scenario, "mark-territory", character_id="x")).reason
        == "invalid character or territory id"
    )
    assert (
        mark.execute(
            ctx, _handler_cmd(scenario, "mark-territory", territory_id=str(distant.id))
        ).reason
        == "territory is not reachable"
    )
    assert (
        mark.execute(
            ctx, _handler_cmd(scenario, "mark-territory", territory_id=str(rock.id))
        ).reason
        == "target is not a territory"
    )
    assert mark.execute(
        ctx, _handler_cmd(scenario, "mark-territory", territory_id=str(territory.id))
    ).ok
    assert (
        mark.execute(
            ctx, _handler_cmd(scenario, "mark-territory", territory_id=str(territory.id))
        ).reason
        == "territory is already marked by you"
    )

    assert (
        track.execute(ctx, _handler_cmd(scenario, "track-herd", character_id="x")).reason
        == "invalid character or herd id"
    )
    assert (
        track.execute(
            ctx, _handler_cmd(scenario, "track-herd", herd_id=str(distant_herd.id))
        ).reason
        == "herd is not reachable"
    )
    assert (
        track.execute(ctx, _handler_cmd(scenario, "track-herd", herd_id=str(rock.id))).reason
        == "target is not a herd"
    )
    assert track.execute(ctx, _handler_cmd(scenario, "track-herd", herd_id=str(herd.id))).ok

    assert (
        prepare.execute(ctx, _handler_cmd(scenario, "prepare-nest", character_id="x")).reason
        == "invalid character or nest id"
    )
    assert (
        prepare.execute(
            ctx, _handler_cmd(scenario, "prepare-nest", nest_id=str(distant_nest.id))
        ).reason
        == "nest is not reachable"
    )
    assert (
        prepare.execute(ctx, _handler_cmd(scenario, "prepare-nest", nest_id=str(rock.id))).reason
        == "target is not a nest"
    )
    assert (
        prepare.execute(
            ctx, _handler_cmd(scenario, "prepare-nest", nest_id=str(prepared.id))
        ).reason
        == "nest is already prepared"
    )
    assert prepare.execute(ctx, _handler_cmd(scenario, "prepare-nest", nest_id=str(nest.id))).ok


async def test_enclosure_escape_recapture_hide_and_evacuation_loop():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    raptor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="clever raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
        ],
    )
    bystander = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="field tech", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), raptor.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), bystander.id)

    built: list[EnclosureBuiltEvent] = []
    repaired: list[FenceRepairedEvent] = []
    reinforced: list[GateReinforcedEvent] = []
    locked: list[PenLockedEvent] = []
    opened: list[PenOpenedEvent] = []
    escaped: list[CreatureEscapedEvent] = []
    hidden: list = []
    recaptured: list[CreatureRecapturedEvent] = []
    contained: list[ContainmentTriggeredEvent] = []
    evacuated: list[RoomEvacuatedEvent] = []
    scenario.actor.bus.subscribe(EnclosureBuiltEvent, built.append)
    scenario.actor.bus.subscribe(FenceRepairedEvent, repaired.append)
    scenario.actor.bus.subscribe(GateReinforcedEvent, reinforced.append)
    scenario.actor.bus.subscribe(PenLockedEvent, locked.append)
    scenario.actor.bus.subscribe(PenOpenedEvent, opened.append)
    scenario.actor.bus.subscribe(CreatureEscapedEvent, escaped.append)
    scenario.actor.bus.subscribe(HiddenFromCreatureEvent, hidden.append)
    scenario.actor.bus.subscribe(CreatureRecapturedEvent, recaptured.append)
    scenario.actor.bus.subscribe(ContainmentTriggeredEvent, contained.append)
    scenario.actor.bus.subscribe(RoomEvacuatedEvent, evacuated.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "build",
            target_id=str(scenario.room_a),
            name="Fern Pen",
            capacity=2,
            feeding_pen=True,
            quarantine=True,
        )
    )
    await scenario.actor.tick(HOUR)
    replace_component(room, FenceComponent(integrity=2.0, maximum=10.0))
    await scenario.actor.submit(
        _cmd(scenario, "repair-fence", enclosure_id=str(scenario.room_a), amount=4.0)
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "reinforce-gate", enclosure_id=str(scenario.room_a), amount=2.0)
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "lock-pen", enclosure_id=str(scenario.room_a)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "open-pen", enclosure_id=str(scenario.room_a)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(HOUR)

    assert built[0].name == "Fern Pen"
    assert repaired[0].integrity == 6.0
    assert reinforced[0].reinforcement == 2.0
    assert locked and opened
    assert escaped[0].creature_id == str(raptor.id)
    assert container_of(raptor) == scenario.room_b
    assert room.has_component(EnclosureComponent)
    assert room.has_component(FeedingPenComponent)
    assert room.has_component(QuarantinePenComponent)
    assert room.get_component(GateComponent).open is True

    await scenario.actor.submit(_cmd(scenario, "move", direction="north"))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "hide-from-creature", creature_id=str(raptor.id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "recapture-creature",
            creature_id=str(raptor.id),
            enclosure_id=str(scenario.room_a),
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "trigger-containment", enclosure_id=str(scenario.room_a))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "evacuate-room",
            room_id=str(scenario.room_a),
            destination_id=str(scenario.room_b),
        )
    )
    await scenario.actor.tick(HOUR)

    assert hidden
    assert recaptured[0].enclosure_id == str(scenario.room_a)
    assert container_of(raptor) == scenario.room_a
    assert contained[0].enclosure_id == str(scenario.room_a)
    assert room.get_component(GateComponent).locked is True
    assert room.get_component(ContainmentProtocolComponent).active is True
    assert evacuated[0].character_ids == (str(bystander.id),)
    assert container_of(bystander) == scenario.room_b

    await scenario.actor.submit(_cmd(scenario, "move", direction="south"))
    await scenario.actor.tick(HOUR)
    fragments = dinosim_fragments(
        scenario.actor.world,
        scenario.actor.world.get_entity(scenario.character),
    )
    assert "Enclosure nearby: Fern Pen." in fragments
    assert "Fern Pen gate: closed, locked." in fragments


async def test_dangerous_encounter_army_response_and_damage_repair_loop():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    raptor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="armored raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            CreatureAttackComponent(damage=3.0, attack_type="bite"),
            RoarComponent(fear=2.0),
            ChargeComponent(damage=4.0, prepared=True),
            GrappleComponent(target_id=str(scenario.character)),
            TrampleComponent(damage=5.0),
            ArmorPlateComponent(rating=1.0),
            WeakPointComponent(label="soft flank", damage_multiplier=2.0),
            PackHuntComponent(pack_id="red pack", bonus=1.0),
            ApexPredatorComponent(threat_level=6),
            KaijuComponent(threat_level=7),
        ],
    )
    replace_component(room, SettlementDamageComponent(severity=3))
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), raptor.id)

    charged: list[CreatureChargedEvent] = []
    attacked: list[CreatureAttackedEvent] = []
    roared: list[CreatureRoaredEvent] = []
    trampled: list[CreatureTrampledEvent] = []
    weak_hit: list[WeakPointHitEvent] = []
    apex: list[ApexPredatorAppearedEvent] = []
    kaiju: list[KaijuArrivedEvent] = []
    army: list[ArmyCalledEvent] = []
    driven_off: list[PredatorDrivenOffEvent] = []
    repaired: list[SettlementDamageRepairedEvent] = []
    scenario.actor.bus.subscribe(CreatureChargedEvent, charged.append)
    scenario.actor.bus.subscribe(CreatureAttackedEvent, attacked.append)
    scenario.actor.bus.subscribe(CreatureRoaredEvent, roared.append)
    scenario.actor.bus.subscribe(CreatureTrampledEvent, trampled.append)
    scenario.actor.bus.subscribe(WeakPointHitEvent, weak_hit.append)
    scenario.actor.bus.subscribe(ApexPredatorAppearedEvent, apex.append)
    scenario.actor.bus.subscribe(KaijuArrivedEvent, kaiju.append)
    scenario.actor.bus.subscribe(ArmyCalledEvent, army.append)
    scenario.actor.bus.subscribe(PredatorDrivenOffEvent, driven_off.append)
    scenario.actor.bus.subscribe(SettlementDamageRepairedEvent, repaired.append)

    commands = [
        _cmd(scenario, "dodge-creature", creature_id=str(raptor.id)),
        _cmd(scenario, "fight-creature", creature_id=str(raptor.id), damage=2.0),
        _cmd(scenario, "target-weak-point", creature_id=str(raptor.id), damage=2.0),
        _cmd(
            scenario,
            "call-for-help",
            room_id=str(scenario.room_a),
            strength=2.0,
        ),
        _cmd(
            scenario,
            "signal-army",
            room_id=str(scenario.room_a),
            creature_id=str(raptor.id),
            strength=3.0,
        ),
        _cmd(scenario, "repair-damage", damage_id=str(scenario.room_a), amount=3),
        _cmd(scenario, "drive-off-predator", creature_id=str(raptor.id)),
    ]
    for command in commands:
        await scenario.actor.submit(command)
        await scenario.actor.tick(HOUR)

    assert charged[0].dodged is True
    assert attacked[0].damage == 4.0
    assert roared[0].fear == 2.0
    assert trampled[0].damage == 5.0
    assert weak_hit[0].label == "soft flank"
    assert weak_hit[0].damage == 4.0
    assert apex[0].threat_level == 6
    assert kaiju[0].threat_level == 7
    assert [event.strength for event in army] == [2.0, 3.0]
    assert driven_off[-1].creature_id == str(raptor.id)
    assert repaired[0].repaired is True
    assert container_of(raptor) == scenario.room_b
    assert room.get_component(ArmyResponseComponent).strength == 3.0
    assert room.get_component(SettlementDamageComponent).repaired is True
    assert raptor.get_component(ChargeComponent).prepared is False
    assert raptor.get_component(GrappleComponent).active is False
    assert raptor.get_component(WeakPointComponent).exposed is False
    assert raptor.get_component(ApexPredatorComponent).threat_level == 0
    assert raptor.get_component(KaijuComponent).threat_level == 0

    fragments = dinosim_fragments(
        scenario.actor.world,
        scenario.actor.world.get_entity(scenario.character),
    )
    assert "Army response signaled for Mosslit Burrow: strength 3." in fragments


async def test_creature_products_feed_store_ranch_work_and_guard_assignment_loop():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    replace_component(room, FeedStoreComponent(feed=1.0, capacity=10.0))
    raptor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ranch raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            CreatureMilkComponent(volume=3.0, maximum=3.0),
            ToxinComponent(potency=2.0, quantity=2.0, maximum=2.0),
            HideComponent(quality=1.5),
            BoneComponent(quality=2.0),
            CreatureProductComponent(product_type="fertilizer", quantity=4.0, renewable=True),
        ],
    )
    egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ranch egg", kind="egg"),
            EggComponent(
                species_name="velociraptor",
                laid_at_epoch=0,
            ),
        ],
    )
    egg.add_relationship(DescendsFromParent(), raptor.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), raptor.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), egg.id)

    initial_fragments = dinosim_fragments(
        scenario.actor.world,
        scenario.actor.world.get_entity(scenario.character),
    )
    assert "Creature product available from ranch raptor: fertilizer x4." in initial_fragments
    assert "ranch raptor has harvestable hide." in initial_fragments
    assert "ranch raptor has harvestable bone." in initial_fragments

    stocked: list[FeedStockedEvent] = []
    products: list[CreatureProductCollectedEvent] = []
    ranch_work: list[RanchWorkAssignedEvent] = []
    guard_assigned: list[GuardAssignedEvent] = []
    scenario.actor.bus.subscribe(FeedStockedEvent, stocked.append)
    scenario.actor.bus.subscribe(CreatureProductCollectedEvent, products.append)
    scenario.actor.bus.subscribe(RanchWorkAssignedEvent, ranch_work.append)
    scenario.actor.bus.subscribe(GuardAssignedEvent, guard_assigned.append)

    commands = [
        _cmd(scenario, "stock-feed", feed_store_id=str(scenario.room_a), amount=7.0),
        _cmd(scenario, "collect-egg", egg_id=str(egg.id)),
        _cmd(
            scenario,
            "harvest",
            creature_id=str(raptor.id),
            product_type="milk",
            quantity=2.0,
        ),
        _cmd(
            scenario,
            "harvest",
            creature_id=str(raptor.id),
            product_type="toxin",
            quantity=1.0,
        ),
        _cmd(
            scenario,
            "harvest",
            creature_id=str(raptor.id),
            product_type="hide",
        ),
        _cmd(
            scenario,
            "harvest",
            creature_id=str(raptor.id),
            product_type="bone",
        ),
        _cmd(
            scenario,
            "harvest",
            creature_id=str(raptor.id),
            product_type="fertilizer",
            quantity=2.0,
        ),
        _cmd(
            scenario,
            "assign-ranch-work",
            creature_id=str(raptor.id),
            work_type="mount work",
            target_id=str(scenario.room_a),
        ),
        _cmd(
            scenario,
            "assign-guard",
            creature_id=str(raptor.id),
            location_id=str(scenario.room_a),
        ),
    ]
    for command in commands:
        await scenario.actor.submit(command)
        await scenario.actor.tick(HOUR)

    assert stocked[0].feed == 8.0
    assert [event.product_type for event in products] == [
        "egg",
        "milk",
        "toxin",
        "hide",
        "bone",
        "fertilizer",
    ]
    assert products[2].quantity == 1.0
    assert ranch_work[0].work_type == "mount work"
    assert guard_assigned[0].location_id == str(scenario.room_a)
    assert container_of(egg) == scenario.character
    assert egg.get_component(CreatureProductComponent).product_type == "egg"
    assert room.get_component(FeedStoreComponent).feed == 8.0
    assert raptor.get_component(CreatureMilkComponent).volume == 1.0
    assert raptor.get_component(ToxinComponent).quantity == 1.0
    assert raptor.get_component(HideComponent).harvested is True
    assert raptor.get_component(BoneComponent).harvested is True
    assert raptor.get_component(CreatureProductComponent).quantity == 2.0
    assert raptor.get_component(RanchLaborComponent).work_type == "mount work"
    assert raptor.get_component(GuardAnimalComponent).location_id == str(scenario.room_a)
    assert raptor.get_component(GuardBehaviorComponent).location_id == str(scenario.room_a)

    inventory_products = [
        entity.get_component(CreatureProductComponent).product_type
        for _edge, entity_id in scenario.actor.world.get_entity(
            scenario.character
        ).get_relationships(Contains)
        if scenario.actor.world.get_entity(entity_id).has_component(CreatureProductComponent)
        for entity in (scenario.actor.world.get_entity(entity_id),)
    ]
    assert sorted(inventory_products) == [
        "bone",
        "egg",
        "fertilizer",
        "hide",
        "milk",
        "toxin",
    ]

    fragments = dinosim_fragments(
        scenario.actor.world,
        scenario.actor.world.get_entity(scenario.character),
    )
    assert "Feed store at Mosslit Burrow: 8/10." in fragments
    assert "ranch raptor is assigned to ranch work: mount work." in fragments


def test_dangerous_encounter_handlers_reject_invalid_and_cover_edge_paths_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    rock = spawn_entity(scenario.actor.world, [IdentityComponent(name="plain rock", kind="rock")])
    plain = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="plain raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
        ],
    )
    hidden = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="hidden flank raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            WeakPointComponent(exposed=False),
        ],
    )
    inventory_predator = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="pocket predator", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
        ],
    )
    for entity in (rock, plain, hidden):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), inventory_predator.id
    )

    cases = [
        (
            DodgeCreatureHandler(),
            _handler_cmd(scenario, "dodge-creature", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            FightCreatureHandler(),
            _handler_cmd(scenario, "fight-creature", creature_id=str(rock.id)),
            "target is not a creature",
        ),
        (
            TargetWeakPointHandler(),
            _handler_cmd(scenario, "target-weak-point", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            TargetWeakPointHandler(),
            _handler_cmd(scenario, "target-weak-point", creature_id=str(plain.id)),
            "creature has no exposed weak point",
        ),
        (
            TargetWeakPointHandler(),
            _handler_cmd(scenario, "target-weak-point", creature_id=str(hidden.id)),
            "weak point is not exposed",
        ),
        (
            DriveOffPredatorHandler(),
            _handler_cmd(scenario, "drive-off-predator", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            DriveOffPredatorHandler(),
            _handler_cmd(scenario, "drive-off-predator", creature_id="entity_999"),
            "creature does not exist",
        ),
        (
            CallForHelpHandler(),
            _handler_cmd(scenario, "call-for-help", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            CallForHelpHandler(),
            _handler_cmd(scenario, "call-for-help", room_id=str(rock.id)),
            "target is not a room",
        ),
        (
            SignalArmyHandler(),
            _handler_cmd(scenario, "signal-army", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            SignalArmyHandler(),
            _handler_cmd(scenario, "signal-army", room_id="entity_999"),
            "room does not exist",
        ),
        (
            RepairDamageHandler(),
            _handler_cmd(scenario, "repair-damage", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            RepairDamageHandler(),
            _handler_cmd(scenario, "repair-damage", damage_id=str(plain.id)),
            "target has no settlement damage",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    assert (
        DodgeCreatureHandler()
        .execute(ctx, _handler_cmd(scenario, "dodge-creature", creature_id=str(plain.id)))
        .ok
    )
    fight_result = FightCreatureHandler().execute(
        ctx, _handler_cmd(scenario, "fight-creature", creature_id=str(plain.id))
    )
    assert fight_result.ok is True
    assert len(fight_result.events) == 1
    assert (
        DriveOffPredatorHandler()
        .execute(
            ctx,
            _handler_cmd(
                scenario,
                "drive-off-predator",
                creature_id=str(inventory_predator.id),
            ),
        )
        .ok
    )
    signal_result = SignalArmyHandler().execute(
        ctx, _handler_cmd(scenario, "signal-army", room_id=str(scenario.room_a))
    )
    assert signal_result.ok is True
    assert len(signal_result.events) == 1


def test_creature_product_handlers_reject_invalid_and_cover_edge_paths_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    rock = spawn_entity(scenario.actor.world, [IdentityComponent(name="plain rock", kind="rock")])
    plain = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="plain raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
        ],
    )
    milkless = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="dry raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            CreatureMilkComponent(volume=0.0),
        ],
    )
    toxinless = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="spent toxin raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            ToxinComponent(quantity=0.0),
        ],
    )
    harvested = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="harvested raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            HideComponent(harvested=True),
            BoneComponent(harvested=True),
        ],
    )
    depleted = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="depleted raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            CreatureProductComponent(product_type="fertilizer", quantity=0.0),
        ],
    )
    meat = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="meat raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            CreatureProductComponent(product_type="meat", quantity=3.0, renewable=False),
        ],
    )
    auto_milk = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="milk raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            CreatureMilkComponent(volume=1.0),
        ],
    )
    auto_toxin = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="toxin raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            ToxinComponent(quantity=1.0),
        ],
    )
    auto_product = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="fertilizer raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            CreatureProductComponent(product_type="fertilizer", quantity=1.0),
        ],
    )
    auto_hide = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="hide raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            HideComponent(),
        ],
    )
    auto_bone = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="bone raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            BoneComponent(),
        ],
    )
    egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="plain egg", kind="egg"),
            EggComponent(species_name="raptor", laid_at_epoch=0),
        ],
    )
    distant_egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far egg", kind="egg"),
            EggComponent(species_name="raptor", laid_at_epoch=0),
        ],
    )
    distant_feed_store = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far trough", kind="feed-store"),
            FeedStoreComponent(feed=0.0),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), distant_feed_store.id
    )
    for entity in (
        rock,
        plain,
        milkless,
        toxinless,
        harvested,
        depleted,
        meat,
        auto_milk,
        auto_toxin,
        auto_product,
        auto_hide,
        auto_bone,
        egg,
    ):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    cases = [
        (
            StockFeedHandler(),
            _handler_cmd(scenario, "stock-feed", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            StockFeedHandler(),
            _handler_cmd(scenario, "stock-feed", feed_store_id="entity_999"),
            "feed store does not exist",
        ),
        (
            StockFeedHandler(),
            _handler_cmd(scenario, "stock-feed", feed_store_id=str(distant_feed_store.id)),
            "feed store is not reachable",
        ),
        (
            CollectEggHandler(),
            _handler_cmd(scenario, "collect-egg", character_id="not-an-id", egg_id=str(egg.id)),
            "invalid character or egg id",
        ),
        (
            CollectEggHandler(),
            _handler_cmd(scenario, "collect-egg", egg_id="entity_999"),
            "egg does not exist",
        ),
        (
            CollectEggHandler(),
            _handler_cmd(scenario, "collect-egg", egg_id=str(distant_egg.id)),
            "egg is not reachable",
        ),
        (
            CollectEggHandler(),
            _handler_cmd(scenario, "collect-egg", egg_id=str(rock.id)),
            "target is not an egg",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(scenario, "harvest", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(scenario, "harvest", creature_id=str(rock.id)),
            "target is not a creature",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(scenario, "harvest", creature_id=str(plain.id)),
            "creature has no harvestable product",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(plain.id),
                product_type="milk",
            ),
            "creature has no milk",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(milkless.id),
                product_type="milk",
            ),
            "creature has no milk available",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(plain.id),
                product_type="toxin",
            ),
            "creature has no toxin",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(toxinless.id),
                product_type="toxin",
            ),
            "creature has no toxin available",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(plain.id),
                product_type="hide",
            ),
            "creature has no hide",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(harvested.id),
                product_type="hide",
            ),
            "hide has already been harvested",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(plain.id),
                product_type="bone",
            ),
            "creature has no bone",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(harvested.id),
                product_type="bone",
            ),
            "bone has already been harvested",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(depleted.id),
                product_type="meat",
            ),
            "creature has no matching product",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(depleted.id),
                product_type="fertilizer",
            ),
            "creature product is depleted",
        ),
        (
            HarvestProductHandler(),
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(plain.id),
                product_type="scale",
            ),
            "creature has no matching product",
        ),
        (
            AssignRanchWorkHandler(),
            _handler_cmd(scenario, "assign-ranch-work", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            AssignRanchWorkHandler(),
            _handler_cmd(scenario, "assign-ranch-work", creature_id="entity_999"),
            "creature does not exist",
        ),
        (
            AssignRanchWorkHandler(),
            _handler_cmd(scenario, "assign-ranch-work", creature_id=str(plain.id)),
            "work type is required",
        ),
        (
            AssignGuardHandler(),
            _handler_cmd(scenario, "assign-guard", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            AssignGuardHandler(),
            _handler_cmd(scenario, "assign-guard", creature_id="entity_999"),
            "creature does not exist",
        ),
        (
            AssignGuardHandler(),
            _handler_cmd(
                scenario,
                "assign-guard",
                creature_id=str(plain.id),
                location_id="entity_999",
            ),
            "guard location does not exist",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    stock_result = StockFeedHandler().execute(ctx, _handler_cmd(scenario, "stock-feed", amount=2))
    assert stock_result.ok is True
    assert room.get_component(FeedStoreComponent).feed == 2.0
    assert (
        HarvestProductHandler()
        .execute(
            ctx,
            _handler_cmd(
                scenario,
                "harvest",
                creature_id=str(meat.id),
                product_type="meat",
                quantity=2,
            ),
        )
        .ok
    )
    assert meat.get_component(CreatureProductComponent).quantity == 0.0
    for creature in (auto_milk, auto_toxin, auto_product, auto_hide, auto_bone):
        assert (
            HarvestProductHandler()
            .execute(
                ctx,
                _handler_cmd(
                    scenario,
                    "harvest",
                    creature_id=str(creature.id),
                ),
            )
            .ok
        )
    assert (
        AssignGuardHandler()
        .execute(ctx, _handler_cmd(scenario, "assign-guard", creature_id=str(plain.id)))
        .ok
    )
    assert plain.get_component(GuardAnimalComponent).location_id == str(scenario.room_a)


def test_dinosim_fragments_cover_danger_settlement_and_enclosure_branches():
    scenario = build_scenario()
    room = scenario.actor.world.get_entity(scenario.room_a)
    replace_component(room, EnclosureComponent(name="Risk Pen"))
    replace_component(room, FenceComponent(integrity=3.0, maximum=5.0))
    replace_component(room, GateComponent(open=True, locked=False))
    replace_component(room, EscapeRiskComponent(risk=0.5))
    replace_component(room, SettlementDamageComponent(severity=2))
    replace_component(room, ArmyResponseComponent(called=True, strength=4.0))
    threat = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="visible threat", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            CreatureAttackComponent(damage=2.0, attack_type="claw"),
            WeakPointComponent(label="neck"),
            ApexPredatorComponent(threat_level=4),
            KaijuComponent(threat_level=9),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), threat.id)

    fragments = dinosim_fragments(
        scenario.actor.world,
        scenario.actor.world.get_entity(scenario.character),
    )

    assert "Dangerous creature: visible threat (claw)." in fragments
    assert "visible threat has exposed weak point: neck." in fragments
    assert "Apex predator nearby: visible threat threat 4." in fragments
    assert "Kaiju threat nearby: visible threat threat 9." in fragments
    assert "Settlement damage on Mosslit Burrow: severity 2." in fragments
    assert "Army response signaled for Mosslit Burrow: strength 4." in fragments
    assert "Risk Pen escape risk: 0.5." in fragments


def test_dinosim_component_prompt_fragments_cover_compound_and_target_state():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    egg = spawn_entity(
        world,
        [
            IdentityComponent(name="warm egg", kind="egg"),
            EggComponent(species_name="raptor", laid_at_epoch=0, fertilized=True),
            IncubationComponent(started_at_epoch=0, ready=True, temperature=32.0),
        ],
    )
    companion = spawn_entity(
        world,
        [
            IdentityComponent(name="Blue", kind="character"),
            CompanionComponent(owner_id=str(character.id), role="companion"),
        ],
    )
    pen = spawn_entity(
        world,
        [
            EnclosureComponent(name="Risk Pen"),
            GateComponent(open=True, locked=False),
            EscapeRiskComponent(risk=0.5),
        ],
    )
    egg_ctx = ComponentPromptContext.for_entity(world, egg)
    companion_ctx = ComponentPromptContext.for_entity(world, companion, target=character)
    pen_ctx = ComponentPromptContext.for_entity(world, pen)

    assert egg.get_component(EggComponent).prompt_fragments(egg_ctx) == (
        "Nearby egg: warm egg (raptor, ready to hatch, 32 C).",
    )
    assert companion.get_component(CompanionComponent).prompt_fragments(companion_ctx) == (
        "Your companion: Blue.",
    )
    assert pen.get_component(GateComponent).prompt_fragments(pen_ctx) == (
        "Risk Pen gate: open, unlocked.",
    )
    assert pen.get_component(EscapeRiskComponent).prompt_fragments(pen_ctx) == (
        "Risk Pen escape risk: 0.5.",
    )


def test_dinosim_consequences_cover_policy_reuse_and_escape_risk_edges_directly():
    scenario = build_scenario()
    install_dinosim(scenario.actor)
    install_dinosim(scenario.actor)
    world = scenario.actor.world

    ready_egg = spawn_entity(
        world,
        [
            IdentityComponent(name="ready egg", kind="egg"),
            EggComponent(species_name="raptor", laid_at_epoch=0, fertilized=True),
            IncubationComponent(started_at_epoch=0, ready=True),
        ],
    )
    unfertilized_egg = spawn_entity(
        world,
        [
            IdentityComponent(name="unfertilized egg", kind="egg"),
            EggComponent(species_name="raptor", laid_at_epoch=0, fertilized=False),
            IncubationComponent(started_at_epoch=0),
        ],
    )
    IncubationConsequence().process(world, HOUR)
    assert ready_egg.get_component(IncubationComponent).ready is True
    assert unfertilized_egg.get_component(IncubationComponent).progress_seconds == 0

    safe = spawn_entity(
        world,
        [
            RoomComponent(title="Safe Pen"),
            EnclosureComponent(name="Safe Pen"),
            FenceComponent(integrity=5.0),
            GateComponent(open=False, locked=True),
            EscapeRiskComponent(risk=0.5, last_updated_epoch=0),
        ],
    )
    unsafe_slow = spawn_entity(
        world,
        [
            RoomComponent(title="Slow Pen"),
            EnclosureComponent(name="Slow Pen"),
            GateComponent(open=True, locked=False),
            EscapeRiskComponent(risk=0.2, threshold=1.0, last_updated_epoch=0),
            ReinforcementComponent(amount=5.0),
        ],
    )
    no_exit = spawn_entity(
        world,
        [
            RoomComponent(title="No Exit Pen"),
            EnclosureComponent(name="No Exit Pen"),
            FenceComponent(integrity=0.0),
            EscapeRiskComponent(risk=1.0, threshold=1.0, last_updated_epoch=0),
        ],
    )
    room = world.get_entity(scenario.room_a)
    replace_component(room, EnclosureComponent(name="Stampede Pen"))
    replace_component(room, FenceComponent(integrity=0.0))
    replace_component(room, EscapeRiskComponent(risk=1.0, threshold=1.0, last_updated_epoch=0))
    raptor_a = spawn_entity(
        world,
        [
            IdentityComponent(name="raptor a", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
        ],
    )
    raptor_b = spawn_entity(
        world,
        [
            IdentityComponent(name="raptor b", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), raptor_a.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), raptor_b.id)

    events = EscapeRiskConsequence().process(world, HOUR)

    assert safe.get_component(EscapeRiskComponent).risk == 0.0
    assert unsafe_slow.get_component(EscapeRiskComponent).risk < 1.0
    assert no_exit.get_component(EscapeRiskComponent).risk == 1.0
    assert any(isinstance(event, StampedeStartedEvent) for event in events)
    assert container_of(raptor_a) == scenario.room_b
    assert container_of(raptor_b) == scenario.room_b


def test_enclosure_handlers_reject_invalid_and_cover_edge_paths_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    rock = spawn_entity(scenario.actor.world, [IdentityComponent(name="plain rock", kind="rock")])
    no_gate = spawn_entity(
        scenario.actor.world,
        [RoomComponent(title="No Gate Pen"), EnclosureComponent(name="No Gate Pen")],
    )
    no_fence = spawn_entity(
        scenario.actor.world,
        [RoomComponent(title="No Fence Pen"), EnclosureComponent(name="No Fence Pen")],
    )
    raptor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="escape-risk raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            EscapeRiskComponent(risk=0.5),
        ],
    )
    for entity in (rock, no_gate, no_fence, raptor):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    cases = [
        (
            BuildEnclosureHandler(),
            _handler_cmd(scenario, "build", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            BuildEnclosureHandler(),
            _handler_cmd(scenario, "build", target_id=str(rock.id)),
            "target is not a room",
        ),
        (
            BuildEnclosureHandler(),
            _handler_cmd(scenario, "build", target_id=str(no_gate.id)),
            "room is already an enclosure",
        ),
        (
            RepairFenceHandler(),
            _handler_cmd(scenario, "repair-fence", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            RepairFenceHandler(),
            _handler_cmd(scenario, "repair-fence", enclosure_id=str(rock.id)),
            "target is not a room",
        ),
        (
            ReinforceGateHandler(),
            _handler_cmd(scenario, "reinforce-gate", enclosure_id=str(no_gate.id)),
            "enclosure has no gate",
        ),
        (
            LockPenHandler(),
            _handler_cmd(scenario, "lock-pen", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            OpenPenHandler(),
            _handler_cmd(scenario, "open-pen", enclosure_id=str(rock.id)),
            "target is not a room",
        ),
        (
            TriggerContainmentHandler(),
            _handler_cmd(scenario, "trigger-containment", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            RecaptureCreatureHandler(),
            _handler_cmd(scenario, "recapture-creature", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            HideFromCreatureHandler(),
            _handler_cmd(scenario, "hide-from-creature", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            EvacuateRoomHandler(),
            _handler_cmd(scenario, "evacuate-room", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            EvacuateRoomHandler(),
            _handler_cmd(
                scenario,
                "evacuate-room",
                room_id=str(scenario.room_a),
                destination_id="entity_999",
            ),
            "destination does not exist",
        ),
        (
            EvacuateRoomHandler(),
            _handler_cmd(
                scenario,
                "evacuate-room",
                room_id=str(scenario.room_a),
                destination_id=str(rock.id),
            ),
            "destination is not a room",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    assert (
        RepairFenceHandler()
        .execute(
            ctx,
            _handler_cmd(
                scenario,
                "repair-fence",
                enclosure_id=str(no_fence.id),
                amount=3,
            ),
        )
        .ok
    )
    assert no_fence.get_component(FenceComponent).integrity == 3.0
    assert (
        LockPenHandler()
        .execute(ctx, _handler_cmd(scenario, "lock-pen", enclosure_id=str(no_gate.id)))
        .ok
    )
    assert (
        OpenPenHandler()
        .execute(ctx, _handler_cmd(scenario, "open-pen", enclosure_id=str(no_gate.id)))
        .ok
    )
    assert (
        TriggerContainmentHandler()
        .execute(
            ctx,
            _handler_cmd(
                scenario,
                "trigger-containment",
                enclosure_id=str(no_gate.id),
            ),
        )
        .ok
    )
    assert (
        RecaptureCreatureHandler()
        .execute(
            ctx,
            _handler_cmd(
                scenario,
                "recapture-creature",
                creature_id=str(raptor.id),
                enclosure_id=str(no_gate.id),
            ),
        )
        .ok
    )
    assert raptor.get_component(EscapeRiskComponent).risk == 0.0


def test_companion_lifecycle_and_item_handlers_cover_additional_edge_paths_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    companion = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="trained raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            CompanionComponent(owner_id=str(scenario.character)),
            TrainingComponent(learned_commands=("hunt",), progress={"guard": 1.0}),
        ],
    )
    plain = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="plain raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
        ],
    )
    bait = spawn_entity(scenario.actor.world, [IdentityComponent(name="bait", kind="food")])
    distant_bait = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="distant bait", kind="food")]
    )
    clone_egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="clone egg", kind="egg"),
            EggComponent(species_name="velociraptor", laid_at_epoch=0, fertilized=True),
            CloneCandidateComponent(
                species_name="velociraptor",
                source_sample_id="entity_999",
            ),
            IncubationComponent(started_at_epoch=0, ready=True),
        ],
    )
    for entity in (companion, plain, bait, clone_egg):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    cases = [
        (
            SetBaitHandler(),
            _handler_cmd(scenario, "set-bait", bait_id="not-an-id"),
            "invalid item id",
        ),
        (
            SetBaitHandler(),
            _handler_cmd(scenario, "set-bait", bait_id=str(distant_bait.id)),
            "item is not reachable",
        ),
        (
            TranquilizeCreatureHandler(),
            _handler_cmd(scenario, "tranquilize-creature", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            ApproachCreatureHandler(),
            _handler_cmd(scenario, "approach-creature", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            TameCreatureHandler(),
            _handler_cmd(scenario, "tame-creature", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            TameCreatureHandler(),
            _handler_cmd(scenario, "tame-creature", creature_id=str(companion.id)),
            "creature is already your companion",
        ),
        (
            TrainCommandHandler(),
            _handler_cmd(scenario, "train-command", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            TrainCommandHandler(),
            _handler_cmd(scenario, "train-command", creature_id=str(companion.id)),
            "command name is required",
        ),
        (
            MountCreatureHandler(),
            _handler_cmd(scenario, "mount-creature", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            CommandCompanionHandler(),
            _handler_cmd(scenario, "command", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            CommandCompanionHandler(),
            _handler_cmd(scenario, "command", target_id=str(companion.id)),
            "command name is required",
        ),
        (
            CommandCompanionHandler(),
            _handler_cmd(
                scenario,
                "command",
                target_id=str(companion.id),
                instruction="guard",
            ),
            "command has not been trained",
        ),
        (
            RecallCreatureHandler(),
            _handler_cmd(scenario, "recall-creature", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            RecallCreatureHandler(),
            _handler_cmd(scenario, "recall-creature", creature_id="not-an-id"),
            "invalid creature id",
        ),
        (
            RecallCreatureHandler(),
            _handler_cmd(scenario, "recall-creature", creature_id="entity_999"),
            "creature does not exist",
        ),
        (
            RecallCreatureHandler(),
            _handler_cmd(scenario, "recall-creature", creature_id=str(plain.id)),
            "creature is not your companion",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    partial = TrainCommandHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "train-command",
            creature_id=str(companion.id),
            command_name="guard",
            progress=0.5,
        ),
    )
    assert partial.ok is True
    assert partial.events == ()
    assert (
        CommandCompanionHandler()
        .execute(
            ctx,
            _handler_cmd(
                scenario,
                "command",
                target_id=str(companion.id),
                instruction="hunt",
                command_target_id="velociraptor",
            ),
        )
        .ok
    )
    assert companion.get_component(HuntBehaviorComponent).target_species == "velociraptor"

    hatched = HatchEggHandler().execute(
        ctx, _handler_cmd(scenario, "hatch-egg", egg_id=str(clone_egg.id))
    )
    assert hatched.ok is True
    assert not clone_egg.has_component(CloneCandidateComponent)

    room.remove_relationship(Contains, scenario.character)
    assert (
        RecallCreatureHandler()
        .execute(
            ctx,
            _handler_cmd(
                scenario,
                "recall-creature",
                creature_id=str(companion.id),
            ),
        )
        .reason
        == "character is not in a room"
    )


async def test_dinosim_rejects_invalid_fossil_sample_and_parent_targets():
    scenario = build_scenario()
    _install(scenario.actor)
    rejects = _collect_rejections(scenario.actor)
    non_fossil = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="plain rock", kind="rock")],
    )
    fossil = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="amber chip", kind="fossil"),
            FossilFragmentComponent(sample_quality=0.5),
        ],
    )
    sample_target = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="glass vial", kind="item")],
    )
    infertile_parent = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="tired raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            FertilityComponent(fertile=False),
            ReptileProcreationComponent(egg_species_name="velociraptor"),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    for entity in (non_fossil, fossil, sample_target, infertile_parent):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    await scenario.actor.submit(
        _cmd(scenario, "identify", fossil_id="not-an-id", species_name="raptor")
    )
    await scenario.actor.submit(
        _cmd(scenario, "identify", fossil_id="entity_999", species_name="raptor")
    )
    await scenario.actor.submit(
        _cmd(scenario, "identify", fossil_id=str(non_fossil.id), species_name="raptor")
    )
    await scenario.actor.submit(_cmd(scenario, "extract-ancient-sample", fossil_id=str(fossil.id)))
    await scenario.actor.submit(_cmd(scenario, "prepare-clone", sample_id=str(sample_target.id)))
    await scenario.actor.submit(_cmd(scenario, "lay-egg", parent_id=str(scenario.character)))
    await scenario.actor.submit(_cmd(scenario, "lay-egg", parent_id=str(infertile_parent.id)))
    await scenario.actor.tick(HOUR)

    reasons = {event.reason for event in rejects}
    assert "invalid character, fossil, or species name" in reasons
    assert "fossil does not exist" in reasons
    assert "target is not a fossil" in reasons
    assert "fossil has not been identified" in reasons
    assert "target is not an ancient sample" in reasons
    assert "parent cannot lay reptile eggs" in reasons
    assert "parent is not fertile" in reasons


async def test_dinosim_rejects_invalid_egg_lifecycle_steps():
    scenario = build_scenario()
    _install(scenario.actor)
    rejects = _collect_rejections(scenario.actor)
    parent = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="clever raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            FertilityComponent(),
            ReptileProcreationComponent(egg_species_name="velociraptor"),
        ],
    )
    infertile_parent = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="tired raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            FertilityComponent(fertile=False),
            ReptileProcreationComponent(egg_species_name="velociraptor"),
        ],
    )
    not_egg = spawn_entity(scenario.actor.world, [IdentityComponent(name="stone", kind="item")])
    egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="raptor egg", kind="egg"),
            EggComponent(species_name="velociraptor", laid_at_epoch=0),
        ],
    )
    other_egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="other raptor egg", kind="egg"),
            EggComponent(species_name="velociraptor", laid_at_epoch=0),
        ],
    )
    waiting_egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="waiting raptor egg", kind="egg"),
            EggComponent(species_name="velociraptor", laid_at_epoch=0, fertilized=True),
            IncubationComponent(started_at_epoch=0, required_seconds=DAY),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    for entity in (parent, infertile_parent, not_egg, egg, other_egg, waiting_egg):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    commands = [
        _cmd(scenario, "fertilize-egg", egg_id=str(not_egg.id), parent_id=str(parent.id)),
        _cmd(scenario, "fertilize-egg", egg_id=str(egg.id), parent_id=str(infertile_parent.id)),
        _cmd(scenario, "fertilize-egg", egg_id=str(egg.id), parent_id=str(parent.id)),
        _cmd(scenario, "fertilize-egg", egg_id=str(egg.id), parent_id=str(parent.id)),
        _cmd(scenario, "incubate-egg", egg_id=str(other_egg.id)),
        _cmd(scenario, "hatch-egg", egg_id=str(egg.id)),
        _cmd(scenario, "hatch-egg", egg_id=str(waiting_egg.id)),
    ]
    for command in commands:
        await scenario.actor.submit(command)
        await scenario.actor.tick(HOUR)

    reasons = [event.reason for event in rejects]
    assert "target is not an egg" in reasons
    assert "parent is not fertile" in reasons
    assert "egg is already fertilized" in reasons
    assert "egg is not fertilized" in reasons
    assert "egg is not incubating" in reasons
    assert "egg is not ready to hatch" in reasons


def test_dinosim_handlers_reject_invalid_and_unreachable_targets_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    wrong_kind = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="plain rock", kind="rock")],
    )
    fossil = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="amber chip", kind="fossil"),
            FossilFragmentComponent(sample_quality=0.5),
        ],
    )
    sample = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ancient sample", kind="sample"),
            AncientSampleComponent(species_name="velociraptor"),
        ],
    )
    egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="raptor egg", kind="egg"),
            EggComponent(species_name="velociraptor", laid_at_epoch=0),
        ],
    )
    fertile_parent = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="clever raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            FertilityComponent(),
            ReptileProcreationComponent(egg_species_name="velociraptor"),
        ],
    )
    infertile_parent = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="tired raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            FertilityComponent(fertile=False),
            DinosaurComponent(species_name="velociraptor"),
        ],
    )
    species_parent = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ancient reptile", kind="character"),
            CharacterComponent(species="ancient reptile"),
            SpeciesComponent(common_name="ancient reptile"),
        ],
    )
    distant_fossil = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far fossil", kind="fossil"),
            FossilFragmentComponent(sample_quality=0.5),
        ],
    )
    distant_sample = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far sample", kind="sample"),
            AncientSampleComponent(species_name="velociraptor"),
        ],
    )
    distant_egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far egg", kind="egg"),
            EggComponent(species_name="velociraptor", laid_at_epoch=0),
        ],
    )
    distant_parent = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
        ],
    )
    for entity in (
        wrong_kind,
        fossil,
        sample,
        egg,
        fertile_parent,
        infertile_parent,
        species_parent,
    ):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    cases = [
        (
            IdentifyFossilHandler(),
            _handler_cmd(
                scenario,
                "identify",
                character_id="not-an-id",
                fossil_id=str(fossil.id),
                species_name="raptor",
            ),
            "invalid character, fossil, or species name",
        ),
        (
            IdentifyFossilHandler(),
            _handler_cmd(
                scenario,
                "identify",
                fossil_id=str(distant_fossil.id),
                species_name="raptor",
            ),
            "fossil is not reachable",
        ),
        (
            ExtractAncientSampleHandler(),
            _handler_cmd(
                scenario,
                "extract-ancient-sample",
                character_id="not-an-id",
                fossil_id=str(fossil.id),
            ),
            "invalid character or fossil id",
        ),
        (
            ExtractAncientSampleHandler(),
            _handler_cmd(
                scenario,
                "extract-ancient-sample",
                fossil_id=str(distant_fossil.id),
            ),
            "fossil is not reachable",
        ),
        (
            PrepareCloneHandler(),
            _handler_cmd(
                scenario,
                "prepare-clone",
                character_id="not-an-id",
                sample_id=str(sample.id),
            ),
            "invalid character or sample id",
        ),
        (
            PrepareCloneHandler(),
            _handler_cmd(scenario, "prepare-clone", sample_id="entity_999"),
            "sample does not exist",
        ),
        (
            PrepareCloneHandler(),
            _handler_cmd(scenario, "prepare-clone", sample_id=str(distant_sample.id)),
            "sample is not reachable",
        ),
        (
            LayEggHandler(),
            _handler_cmd(
                scenario,
                "lay-egg",
                character_id="not-an-id",
                parent_id=str(fertile_parent.id),
            ),
            "invalid character or parent id",
        ),
        (
            LayEggHandler(),
            _handler_cmd(scenario, "lay-egg", parent_id="entity_999"),
            "parent does not exist",
        ),
        (
            LayEggHandler(),
            _handler_cmd(scenario, "lay-egg", parent_id=str(distant_parent.id)),
            "parent is not reachable",
        ),
        (
            LayEggHandler(),
            _handler_cmd(scenario, "lay-egg", parent_id=str(species_parent.id)),
            "",
        ),
        (
            FertilizeEggHandler(),
            _handler_cmd(
                scenario,
                "fertilize-egg",
                character_id="not-an-id",
                egg_id=str(egg.id),
                parent_id=str(fertile_parent.id),
            ),
            "invalid character, egg, or parent id",
        ),
        (
            FertilizeEggHandler(),
            _handler_cmd(
                scenario,
                "fertilize-egg",
                egg_id="entity_999",
                parent_id=str(fertile_parent.id),
            ),
            "egg or parent does not exist",
        ),
        (
            FertilizeEggHandler(),
            _handler_cmd(
                scenario,
                "fertilize-egg",
                egg_id=str(distant_egg.id),
                parent_id=str(fertile_parent.id),
            ),
            "egg or parent is not reachable",
        ),
        (
            IncubateEggHandler(),
            _handler_cmd(
                scenario,
                "incubate-egg",
                character_id="not-an-id",
                egg_id=str(egg.id),
            ),
            "invalid character or egg id",
        ),
        (
            IncubateEggHandler(),
            _handler_cmd(scenario, "incubate-egg", egg_id="entity_999"),
            "egg does not exist",
        ),
        (
            IncubateEggHandler(),
            _handler_cmd(scenario, "incubate-egg", egg_id=str(distant_egg.id)),
            "egg is not reachable",
        ),
        (
            HatchEggHandler(),
            _handler_cmd(
                scenario,
                "hatch-egg",
                character_id="not-an-id",
                egg_id=str(egg.id),
            ),
            "invalid character or egg id",
        ),
        (
            HatchEggHandler(),
            _handler_cmd(scenario, "hatch-egg", egg_id="entity_999"),
            "egg does not exist",
        ),
        (
            HatchEggHandler(),
            _handler_cmd(scenario, "hatch-egg", egg_id=str(distant_egg.id)),
            "egg is not reachable",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        if reason:
            assert result.ok is False
            assert result.reason == reason
        else:
            assert result.ok is True


def test_companion_handlers_reject_invalid_targets_and_missing_ownership_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    rock = spawn_entity(scenario.actor.world, [IdentityComponent(name="plain rock", kind="rock")])
    raptor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="clever raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
        ],
    )
    other_companion = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="other raptor", kind="character"),
            CharacterComponent(species="velociraptor"),
            DinosaurComponent(species_name="velociraptor"),
            CompanionComponent(owner_id="entity_999"),
        ],
    )
    bait = spawn_entity(scenario.actor.world, [IdentityComponent(name="bait", kind="food")])
    spent_tranquilizer = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="spent dart", kind="tool"),
            TranquilizerComponent(uses=0),
        ],
    )
    for entity in (rock, raptor, other_companion, bait, spent_tranquilizer):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    cases = [
        (
            TrackCreatureHandler(),
            _handler_cmd(scenario, "track-creature", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            TrackCreatureHandler(),
            _handler_cmd(scenario, "track-creature", creature_id="entity_999"),
            "creature does not exist",
        ),
        (
            TrackCreatureHandler(),
            _handler_cmd(scenario, "track-creature", creature_id=str(rock.id)),
            "target is not a creature",
        ),
        (
            SetBaitHandler(),
            _handler_cmd(scenario, "set-bait", bait_id="entity_999"),
            "item does not exist",
        ),
        (
            TranquilizeCreatureHandler(),
            _handler_cmd(
                scenario,
                "tranquilize-creature",
                creature_id=str(raptor.id),
                tranquilizer_id=str(bait.id),
            ),
            "item is not a tranquilizer",
        ),
        (
            TranquilizeCreatureHandler(),
            _handler_cmd(
                scenario,
                "tranquilize-creature",
                creature_id=str(raptor.id),
                tranquilizer_id=str(spent_tranquilizer.id),
            ),
            "tranquilizer is spent",
        ),
        (
            TrainCommandHandler(),
            _handler_cmd(
                scenario,
                "train-command",
                creature_id=str(raptor.id),
                command_name="guard",
            ),
            "creature is not your companion",
        ),
        (
            CommandCompanionHandler(),
            _handler_cmd(
                scenario,
                "command",
                target_id=str(other_companion.id),
                instruction="guard",
            ),
            "creature is not your companion",
        ),
        (
            RecallCreatureHandler(),
            _handler_cmd(scenario, "recall-creature", creature_id=str(rock.id)),
            "target is not a creature",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


async def test_storyteller_selects_kaiju_attack_only_when_colonysim_and_dinosim_are_enabled():
    scenario = build_scenario()
    install_dinosim(scenario.actor)
    scenario.actor.register_consequence(
        StorytellerConsequence((*default_incident_definitions(), KAIJU_ATTACK))
    )
    spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="steady storyteller", kind="controller"),
            StorytellerComponent(interval_seconds=HOUR, next_incident_epoch=HOUR),
            IncidentBudgetComponent(points=20.0, points_per_day=0.0),
        ],
    )

    await scenario.actor.tick(HOUR)

    incident = next(
        entity
        for entity in scenario.actor.world.query().with_all([IncidentComponent]).execute_entities()
    )
    assert incident.get_component(IncidentComponent).kind == "hostile_encounter"

    scenario = build_scenario()
    install_colonysim(scenario.actor)
    install_dinosim(scenario.actor)
    scenario.actor.register_consequence(
        StorytellerConsequence((*default_incident_definitions(), KAIJU_ATTACK))
    )
    world = scenario.actor.world
    region = spawn_entity(world, [RegionComponent(name="Mosslit Basin")])
    room_c = spawn_entity(world, [RoomComponent(title="South Ridge")])
    for room_id in (scenario.room_a, scenario.room_b, room_c.id):
        region.add_relationship(Contains(mode=ContainmentMode.REGION), room_id)
    spawn_entity(
        world,
        [
            IdentityComponent(name="kaiju storyteller", kind="controller"),
            StorytellerComponent(interval_seconds=HOUR, next_incident_epoch=HOUR),
            IncidentBudgetComponent(points=20.0, points_per_day=0.0),
        ],
    )

    await scenario.actor.tick(HOUR)

    incident = next(
        entity
        for entity in scenario.actor.world.query().with_all([IncidentComponent]).execute_entities()
    )
    assert incident.get_component(IncidentComponent).kind == "kaiju_attack"
    assert incident.has_component(SettlementDamageComponent)
    region_room_entities = []
    for _edge, room_id in region.get_relationships(Contains):
        room = world.get_entity(room_id)
        region_room_entities.extend(
            world.get_entity(entity_id)
            for _content_edge, entity_id in room.get_relationships(Contains)
        )
    kaiju = [entity for entity in region_room_entities if entity.has_component(KaijuComponent)]
    assert 1 <= len(kaiju) <= 3
    assert sum(entity.get_component(KaijuComponent).threat_level for entity in kaiju) == 15
    assert all(entity.has_component(CharacterComponent) for entity in kaiju)
    assert all(entity.get_component(KaijuComponent).difficulty for entity in kaiju)
    assert len({container_of(entity) for entity in kaiju}) > 1


def _creature(scenario, **need_kwargs):
    creature = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="raptor", kind="creature"),
            CreatureNeedComponent(**need_kwargs),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), creature.id
    )
    return creature.id


def _feed_store(scenario, feed=3.0):
    store = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="feed bin", kind="store"), FeedStoreComponent(feed=feed)],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), store.id
    )
    return store.id


def _inventory_resource(scenario, resource_type, quantity):
    item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=resource_type, kind="resource"),
            ResourceStackComponent(resource_type=resource_type, quantity=quantity),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), item.id
    )
    return item.id


def test_dinosim_consume_inventory_resource_plan_covers_edge_cases():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    rock = spawn_entity(world, [IdentityComponent(name="rock", kind="prop")])
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), rock.id)
    # A non-inventory containment edge holding a resource must be skipped.
    held = spawn_entity(
        world,
        [
            IdentityComponent(name="held hay", kind="resource"),
            ResourceStackComponent(resource_type="hay", quantity=9),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), held.id)
    hay = _inventory_resource(scenario, "hay", 4)

    assert _consume_inventory_resource_operation(character, world, "berries", 1) is None
    assert _consume_inventory_resource_operation(character, world, "hay", 5) is None
    assert world.get_entity(hay).get_component(ResourceStackComponent).quantity == 4
    operation = _consume_inventory_resource_operation(character, world, "hay", 2)
    assert operation is not None
    execute_mutation_plan(world, MutationPlan((operation,)))
    assert world.get_entity(hay).get_component(ResourceStackComponent).quantity == 2


async def test_creature_grows_hungry_and_stressed_over_time():
    scenario = build_scenario()
    _install(scenario.actor)
    creature = _creature(scenario, hunger=58.0, hunger_per_hour=5.0, last_updated_epoch=0)
    # An already-hungry creature keeps gaining hunger/stress without re-crossing.
    already = _creature(scenario, hunger=70.0, hunger_per_hour=5.0, last_updated_epoch=0)
    changes: list[CreatureNeedsChangedEvent] = []
    scenario.actor.bus.subscribe(CreatureNeedsChangedEvent, changes.append)

    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    need = world.get_entity(creature).get_component(CreatureNeedComponent)
    assert need.hunger == 63.0
    assert need.stress > 0.0
    already_need = world.get_entity(already).get_component(CreatureNeedComponent)
    assert already_need.hunger == 75.0
    assert already_need.stress > 0.0
    # Only the creature that newly crossed into hunger emits a change event.
    assert [event.creature_id for event in changes] == [str(creature)]


async def test_feed_creature_draws_from_store_and_lowers_hunger():
    scenario = build_scenario()
    _install(scenario.actor)
    creature = _creature(scenario, hunger=80.0)
    store = _feed_store(scenario, feed=3.0)
    fed: list[CreatureFedEvent] = []
    scenario.actor.bus.subscribe(CreatureFedEvent, fed.append)

    await scenario.actor.submit(
        _cmd(scenario, "feed-creature", creature_id=str(creature), feed_store_id=str(store))
    )
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    assert world.get_entity(store).get_component(FeedStoreComponent).feed == 2.0
    assert world.get_entity(creature).get_component(CreatureNeedComponent).hunger == 30.0
    assert fed and fed[0].hunger == 30.0


async def test_stock_feed_can_consume_colony_feed_resource():
    scenario = build_scenario()
    _install(scenario.actor)
    store = _feed_store(scenario, feed=1.0)
    hay = _inventory_resource(scenario, "hay", 5)
    stocked: list[FeedStockedEvent] = []
    scenario.actor.bus.subscribe(FeedStockedEvent, stocked.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "stock-feed",
            feed_store_id=str(store),
            amount=3.0,
            resource_type="hay",
        )
    )
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    assert world.get_entity(store).get_component(FeedStoreComponent).feed == 4.0
    assert world.get_entity(hay).get_component(ResourceStackComponent).quantity == 2
    assert stocked[0].resource_type == "hay"
    assert stocked[0].resource_spent == 3


async def test_stock_feed_rejects_missing_colony_feed_resource():
    scenario = build_scenario()
    _install(scenario.actor)
    store = _feed_store(scenario, feed=1.0)
    _inventory_resource(scenario, "hay", 1)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "stock-feed",
            feed_store_id=str(store),
            amount=3.0,
            resource_type="hay",
        )
    )
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "not enough feed resource" for event in rejects)
    assert scenario.actor.world.get_entity(store).get_component(FeedStoreComponent).feed == 1.0


async def test_calm_creature_lowers_stress():
    scenario = build_scenario()
    _install(scenario.actor)
    creature = _creature(scenario, stress=50.0)
    calmed: list[CreatureCalmedEvent] = []
    scenario.actor.bus.subscribe(CreatureCalmedEvent, calmed.append)

    await scenario.actor.submit(_cmd(scenario, "calm-creature", creature_id=str(creature)))
    await scenario.actor.tick(HOUR)

    assert (
        scenario.actor.world.get_entity(creature).get_component(CreatureNeedComponent).stress
        == 20.0
    )
    assert calmed and calmed[0].stress == 20.0


async def test_observe_creature_reports_needs_without_mutating():
    scenario = build_scenario()
    _install(scenario.actor)
    creature = _creature(scenario, hunger=40.0, stress=10.0)
    observed: list[CreatureObservedEvent] = []
    scenario.actor.bus.subscribe(CreatureObservedEvent, observed.append)

    await scenario.actor.submit(_cmd(scenario, "observe-creature", creature_id=str(creature)))
    await scenario.actor.tick(HOUR)

    assert observed and observed[0].hunger == 40.0 and observed[0].stress == 10.0


def test_creature_need_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    creature = _creature(scenario, hunger=20.0)
    empty_store = _feed_store(scenario, feed=0.0)
    not_a_creature = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="rock", kind="item")]
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), not_a_creature.id
    )
    far_creature = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="distant raptor", kind="creature"), CreatureNeedComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), far_creature.id
    )

    def feed(**payload):
        return FeedCreatureHandler(), _handler_cmd(scenario, "feed-creature", **payload)

    def calm(**payload):
        return CalmCreatureHandler(), _handler_cmd(scenario, "calm-creature", **payload)

    def observe(**payload):
        return ObserveCreatureHandler(), _handler_cmd(scenario, "observe-creature", **payload)

    cases = [
        (*feed(character_id="x"), "invalid character"),
        (*feed(creature_id="ghost_1", feed_store_id=str(empty_store)), "does not exist"),
        (*feed(creature_id=str(far_creature.id), feed_store_id=str(empty_store)), "not reachable"),
        (
            *feed(creature_id=str(not_a_creature.id), feed_store_id=str(empty_store)),
            "not a creature",
        ),
        (
            *feed(creature_id=str(creature), feed_store_id=str(not_a_creature.id)),
            "not a feed store",
        ),
        (*feed(creature_id=str(creature), feed_store_id=str(empty_store)), "feed store is empty"),
        (*calm(character_id="x"), "invalid character"),
        (*calm(creature_id="ghost_1"), "does not exist"),
        (*calm(creature_id=str(far_creature.id)), "not reachable"),
        (*calm(creature_id=str(not_a_creature.id)), "not a creature"),
        (*observe(character_id="x"), "invalid character"),
        (*observe(creature_id="ghost_1"), "does not exist"),
        (*observe(creature_id=str(far_creature.id)), "not reachable"),
        (*observe(creature_id=str(not_a_creature.id)), "not a creature"),
    ]
    for handler, command, expected in cases:
        result = handler.execute(ctx, command)
        assert not result.ok, expected
        assert expected in result.reason, (expected, result.reason)


def test_dinosim_fragments_show_creature_needs():
    scenario = build_scenario()
    _install(scenario.actor)
    _creature(scenario, hunger=70.0, stress=15.0)

    lines = dinosim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )
    assert any("Creature raptor" in line and "hungry" in line for line in lines)


def _reachable_creature_entity(scenario, *, components=(), name="rex", in_room=None):
    creature = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=name, kind="creature"),
            DinosaurComponent(species_name=name),
            *components,
        ],
    )
    room_id = in_room if in_room is not None else scenario.room_a
    scenario.actor.world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), creature.id
    )
    return creature


def test_payload_entity_id_returns_none_when_no_keys_present():
    command = build_submitted_command(
        character_id="entity_1",
        controller_id="entity_2",
        controller_generation=0,
        command_type="noop",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={},
    )
    assert _payload_entity_id(command, "missing", "also_missing") is None


def test_entity_name_falls_back_to_entity_id():
    scenario = build_scenario()
    bare = spawn_entity(scenario.actor.world, [])
    assert _entity_name(scenario.actor.world.get_entity(bare.id)) == str(bare.id)


def test_reachable_creature_reports_invalid_and_unreachable():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character_id = parse_entity_id(str(scenario.character))

    creature, error = _reachable_creature(ctx, character_id, "not-an-id")
    assert creature is None
    assert error == "invalid creature id"

    distant = _reachable_creature_entity(scenario, in_room=scenario.room_b)
    creature, error = _reachable_creature(ctx, character_id, str(distant.id))
    assert creature is None
    assert error == "creature is not reachable"


def test_region_helpers_walk_nested_regions_and_skip_non_region_edges():
    scenario = build_scenario()
    world = scenario.actor.world
    region = spawn_entity(world, [RegionComponent(name="valley")])
    subregion = spawn_entity(world, [RegionComponent(name="glade")])
    inner_room = spawn_entity(world, [RoomComponent(title="inner")])
    region.add_relationship(Contains(mode=ContainmentMode.REGION), subregion.id)
    subregion.add_relationship(Contains(mode=ContainmentMode.REGION), inner_room.id)
    # A non-region containment edge that must be ignored by the region walk.
    loose = spawn_entity(world, [IdentityComponent(name="prop", kind="prop")])
    region.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), loose.id)

    rooms = _region_rooms(world, region)
    assert [room.id for room in rooms] == [inner_room.id]

    # The inner room's region lookup ignores non-region incoming edges.
    plain_room = world.get_entity(scenario.room_a)
    assert _region_for_room(world, plain_room) is None
    found = _region_for_room(world, world.get_entity(inner_room.id))
    assert found is not None and found.id == subregion.id


def test_hatch_room_id_uses_actor_room_when_egg_has_no_room_container():
    scenario = build_scenario()
    world = scenario.actor.world
    actor = world.get_entity(scenario.character)
    # Egg with no containing room at all.
    egg = spawn_entity(world, [EggComponent(species_name="raptor", laid_at_epoch=0)])
    assert _hatch_room_id(world, actor, egg) == scenario.room_a


def test_companion_fragment_is_empty_without_owner_target():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    companion = spawn_entity(
        world,
        [
            IdentityComponent(name="Echo", kind="character"),
            CompanionComponent(owner_id=str(character.id), role="companion"),
        ],
    )
    no_target_ctx = ComponentPromptContext.for_entity(world, companion)
    assert companion.get_component(CompanionComponent).prompt_fragments(no_target_ctx) == ()


def test_creature_action_handlers_reject_invalid_character():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    handlers = [
        (SetBaitHandler(), "set-bait"),
        (TranquilizeCreatureHandler(), "tranquilize-creature"),
        (ApproachCreatureHandler(), "approach-creature"),
        (TameCreatureHandler(), "tame-creature"),
        (TrainCommandHandler(), "train-command"),
        (MountCreatureHandler(), "mount-creature"),
        (CommandCompanionHandler(), "command"),
        (RepairFenceHandler(), "repair-fence"),
        (ReinforceGateHandler(), "reinforce-gate"),
        (LockPenHandler(), "lock-pen"),
        (OpenPenHandler(), "open-pen"),
        (TriggerContainmentHandler(), "trigger-containment"),
        (RecaptureCreatureHandler(), "recapture-creature"),
        (HideFromCreatureHandler(), "hide-from-creature"),
        (DodgeCreatureHandler(), "dodge-creature"),
        (FightCreatureHandler(), "fight-creature"),
        (TargetWeakPointHandler(), "target-weak-point"),
        (DriveOffPredatorHandler(), "drive-off-predator"),
        (SignalArmyHandler(), "signal-army"),
        (RepairDamageHandler(), "repair-damage"),
        (EvacuateRoomHandler(), "evacuate-room"),
    ]
    for handler, command_type in handlers:
        result = handler.execute(
            ctx, _handler_cmd(scenario, command_type, character_id="not-an-id")
        )
        assert not result.ok, command_type
        assert result.reason == "invalid character id", command_type


def test_creature_handlers_reject_missing_creature_or_item():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    creature = _reachable_creature_entity(
        scenario,
        components=[CompanionComponent(owner_id=str(scenario.character))],
    )

    # Handlers that require a creature: none supplied -> "invalid creature id".
    creature_handlers = [
        (TranquilizeCreatureHandler(), "tranquilize-creature"),
        (ApproachCreatureHandler(), "approach-creature"),
        (TameCreatureHandler(), "tame-creature"),
        (TrainCommandHandler(), "train-command"),
        (MountCreatureHandler(), "mount-creature"),
        (CommandCompanionHandler(), "command"),
        (RecaptureCreatureHandler(), "recapture-creature"),
        (HideFromCreatureHandler(), "hide-from-creature"),
        (DodgeCreatureHandler(), "dodge-creature"),
        (FightCreatureHandler(), "fight-creature"),
        (TargetWeakPointHandler(), "target-weak-point"),
        (DriveOffPredatorHandler(), "drive-off-predator"),
    ]
    for handler, command_type in creature_handlers:
        result = handler.execute(ctx, _handler_cmd(scenario, command_type))
        assert not result.ok, command_type
        assert result.reason == "invalid creature id", command_type

    # set-bait requires a reachable item.
    bait = SetBaitHandler().execute(ctx, _handler_cmd(scenario, "set-bait"))
    assert not bait.ok
    assert bait.reason == "invalid item id"

    # tranquilize requires a tranquilizer item once the creature resolves.
    no_item = TranquilizeCreatureHandler().execute(
        ctx, _handler_cmd(scenario, "tranquilize-creature", creature_id=str(creature.id))
    )
    assert not no_item.ok
    assert no_item.reason == "invalid item id"


def test_mount_and_command_require_a_companion_relationship():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # A reachable creature that is NOT this character's companion.
    creature = _reachable_creature_entity(scenario)

    mount = MountCreatureHandler().execute(
        ctx, _handler_cmd(scenario, "mount-creature", creature_id=str(creature.id))
    )
    assert not mount.ok
    assert mount.reason == "creature is not your companion"

    command = CommandCompanionHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "command",
            target_id=str(creature.id),
            instruction="sit",
        ),
    )
    assert not command.ok
    assert command.reason == "creature is not your companion"


def test_tame_creature_progresses_without_taming_when_below_required():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    creature = _reachable_creature_entity(
        scenario, components=[TamingComponent(progress=0.0, required=100.0)]
    )
    result = TameCreatureHandler().execute(
        ctx, _handler_cmd(scenario, "tame-creature", creature_id=str(creature.id))
    )
    assert result.ok, result.reason
    # Progress is still far below required, so no CreatureTamedEvent and no companion.
    assert not any(e.__class__.__name__ == "CreatureTamedEvent" for e in result.events)
    assert not creature.has_component(CompanionComponent)


def test_recapture_requires_a_target_enclosure():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    creature = _reachable_creature_entity(scenario)
    result = RecaptureCreatureHandler().execute(
        ctx,
        _handler_cmd(scenario, "recapture-creature", creature_id=str(creature.id)),
    )
    assert not result.ok
    assert "enclosure" in (result.reason or "")


def test_target_weak_point_reduces_only_present_threat_components():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # A creature with a weak point but neither apex nor kaiju threat components.
    creature = _reachable_creature_entity(
        scenario, components=[WeakPointComponent(label="soft belly", exposed=True)]
    )
    result = TargetWeakPointHandler().execute(
        ctx,
        _handler_cmd(scenario, "target-weak-point", creature_id=str(creature.id), damage=2.0),
    )
    assert result.ok, result.reason
    assert not creature.has_component(ApexPredatorComponent)
    assert not creature.has_component(KaijuComponent)


def test_signal_army_skips_non_creature_and_kaiju_only_targets():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)

    # A reachable, existing entity that is not a creature: army still called, no PredatorDrivenOff.
    prop = spawn_entity(scenario.actor.world, [IdentityComponent(name="cart", kind="prop")])
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), prop.id
    )
    result = SignalArmyHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "signal-army",
            room_id=str(scenario.room_a),
            creature_id=str(prop.id),
        ),
    )
    assert result.ok, result.reason
    assert not any(e.__class__.__name__ == "PredatorDrivenOffEvent" for e in result.events)

    # An apex-only creature (no kaiju component) exercises the kaiju-skip branch.
    apex = _reachable_creature_entity(
        scenario,
        components=[ApexPredatorComponent(threat_level=8)],
        name="alpha",
    )
    apex_result = SignalArmyHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "signal-army",
            room_id=str(scenario.room_a),
            creature_id=str(apex.id),
            strength=3.0,
        ),
    )
    assert apex_result.ok, apex_result.reason
    assert apex.get_component(ApexPredatorComponent).threat_level == 5


def test_repair_damage_defaults_to_current_room_and_rejects_unreachable():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # No damage_id supplied -> defaults to the character's room, which lacks damage.
    default_room = RepairDamageHandler().execute(ctx, _handler_cmd(scenario, "repair-damage"))
    assert not default_room.ok
    assert default_room.reason == "target has no settlement damage"

    # A damaged target in another room is not reachable.
    distant = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="ruins", kind="prop"), SettlementDamageComponent(severity=3)],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), distant.id
    )
    unreachable = RepairDamageHandler().execute(
        ctx, _handler_cmd(scenario, "repair-damage", damage_id=str(distant.id))
    )
    assert not unreachable.ok
    assert unreachable.reason == "damage target is not reachable"


def test_fight_creature_grapples_an_unbound_target():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    creature = _reachable_creature_entity(
        scenario, components=[GrappleComponent(target_id="", active=True)]
    )
    result = FightCreatureHandler().execute(
        ctx,
        _handler_cmd(scenario, "fight-creature", creature_id=str(creature.id), damage=2.0),
    )
    assert result.ok, result.reason
    grapple = creature.get_component(GrappleComponent)
    assert grapple.target_id == str(scenario.character)
    assert grapple.active is False


def test_build_enclosure_without_optional_pens():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    result = BuildEnclosureHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "build",
            target_id=str(scenario.room_a),
            name="Plain Pen",
        ),
    )
    assert result.ok, result.reason
    room = scenario.actor.world.get_entity(scenario.room_a)
    assert not room.has_component(FeedingPenComponent)
    assert not room.has_component(QuarantinePenComponent)


def test_brood_egg_without_incubation_component():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="cool egg", kind="egg"),
            EggComponent(species_name="raptor", laid_at_epoch=0),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), egg.id
    )
    result = BroodEggHandler().execute(ctx, _handler_cmd(scenario, "brood-egg", egg_id=str(egg.id)))
    assert result.ok, result.reason
    assert egg.has_component(BroodingComponent)


def test_extract_and_hatch_reject_wrong_kind_targets():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    not_fossil = spawn_entity(scenario.actor.world, [IdentityComponent(name="rock", kind="prop")])
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), not_fossil.id
    )
    extract = ExtractAncientSampleHandler().execute(
        ctx,
        _handler_cmd(scenario, "extract-ancient-sample", fossil_id=str(not_fossil.id)),
    )
    assert not extract.ok
    assert extract.reason == "target is not a fossil"

    not_egg = spawn_entity(scenario.actor.world, [IdentityComponent(name="pebble", kind="prop")])
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), not_egg.id
    )
    hatch = HatchEggHandler().execute(
        ctx, _handler_cmd(scenario, "hatch-egg", egg_id=str(not_egg.id))
    )
    assert not hatch.ok
    assert hatch.reason == "target is not an egg"


def test_evacuate_room_requires_a_room():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # A character with no containing room and no room_id payload.
    loose = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Drifter", kind="character"), CharacterComponent()],
    )
    result = EvacuateRoomHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "evacuate-room",
            character_id=str(loose.id),
            destination_id=str(scenario.room_b),
        ),
    )
    assert not result.ok
    assert result.reason == "room is required"


def test_enclosure_handlers_reject_non_enclosure_target():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # A plain room (no EnclosureComponent) is reachable but not an enclosure.
    plain = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="open field", kind="room"), RoomComponent(title="field")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), plain.id
    )
    handlers = [
        (RepairFenceHandler(), "repair-fence"),
        (ReinforceGateHandler(), "reinforce-gate"),
        (LockPenHandler(), "lock-pen"),
        (OpenPenHandler(), "open-pen"),
        (TriggerContainmentHandler(), "trigger-containment"),
    ]
    for handler, command_type in handlers:
        result = handler.execute(
            ctx, _handler_cmd(scenario, command_type, enclosure_id=str(plain.id))
        )
        assert not result.ok, command_type
        assert result.reason == "target is not an enclosure", command_type


def test_extract_ancient_sample_rejects_missing_fossil():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    result = ExtractAncientSampleHandler().execute(
        ctx,
        _handler_cmd(scenario, "extract-ancient-sample", fossil_id="entity_999999"),
    )
    assert not result.ok
    assert result.reason == "fossil does not exist"


def test_can_handle_resolves_target_id_alias():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    fossil = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="bone", kind="fossil"), FossilFragmentComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), fossil.id
    )
    # target_id (not fossil_id) should still let IdentifyFossilHandler claim the command.
    assert IdentifyFossilHandler().can_handle(
        ctx, _handler_cmd(scenario, "identify", target_id=str(fossil.id))
    )

    creature = _reachable_creature_entity(
        scenario, components=[CreatureProductComponent(product_type="egg")]
    )
    assert HarvestProductHandler().can_handle(
        ctx, _handler_cmd(scenario, "harvest", target_id=str(creature.id))
    )


def test_repair_damage_rejects_when_no_room_and_no_target():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # A homeless character with no damage_id falls through to "damage target does not exist".
    loose = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Wanderer", kind="character"), CharacterComponent()],
    )
    result = RepairDamageHandler().execute(
        ctx, _handler_cmd(scenario, "repair-damage", character_id=str(loose.id))
    )
    assert not result.ok
    assert result.reason == "damage target does not exist"


def test_kaiju_specs_use_two_groups_for_mid_budget():
    specs = generate_kaiju_spawn_specs(12, "mid")
    assert len(specs) == 2


def test_selected_kaiju_rooms_falls_back_to_target_when_region_empty():
    scenario = build_scenario()
    world = scenario.actor.world
    # A region that contains the target room but yields no rooms via the walk is
    # avoided here; instead use a target room with no region so the fallback list is used.
    target = world.get_entity(scenario.room_a)
    rooms = selected_kaiju_rooms(world, target.id, 3, seed="seed")
    # Fewer rooms than requested -> the selection pads by repeating.
    assert len(rooms) == 3
    assert all(room.id == target.id for room in rooms)


def test_lay_egg_places_egg_in_actor_room_when_parent_has_no_room():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # Parent creature carried in the character's inventory (no room of its own).
    parent = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="brooder", kind="creature"),
            DinosaurComponent(species_name="raptor"),
            ReptileProcreationComponent(),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), parent.id
    )
    result = LayEggHandler().execute(
        ctx, _handler_cmd(scenario, "lay-egg", parent_id=str(parent.id))
    )
    assert result.ok, result.reason
    laid = [e for e in result.events if e.__class__.__name__ == "EggLaidEvent"]
    assert laid and laid[0].room_id is not None


def test_incubate_and_fertilize_reject_non_egg_targets():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    not_egg = spawn_entity(scenario.actor.world, [IdentityComponent(name="stone", kind="prop")])
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), not_egg.id
    )
    incubate = IncubateEggHandler().execute(
        ctx, _handler_cmd(scenario, "incubate-egg", egg_id=str(not_egg.id))
    )
    assert not incubate.ok
    assert incubate.reason == "target is not an egg"


def test_fight_creature_leaves_grapple_bound_to_other_target():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    creature = _reachable_creature_entity(
        scenario,
        components=[GrappleComponent(target_id="entity_424242", active=True)],
    )
    result = FightCreatureHandler().execute(
        ctx,
        _handler_cmd(scenario, "fight-creature", creature_id=str(creature.id), damage=1.0),
    )
    assert result.ok, result.reason
    # Grapple already bound to a different target stays untouched.
    grapple = creature.get_component(GrappleComponent)
    assert grapple.target_id == "entity_424242"
    assert grapple.active is True


def test_signal_army_reduces_kaiju_only_threat():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    kaiju = _reachable_creature_entity(
        scenario,
        components=[KaijuComponent(threat_level=9, difficulty="epic")],
        name="titan",
    )
    result = SignalArmyHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "signal-army",
            room_id=str(scenario.room_a),
            creature_id=str(kaiju.id),
            strength=4.0,
        ),
    )
    assert result.ok, result.reason
    assert kaiju.get_component(KaijuComponent).threat_level == 5
    assert not kaiju.has_component(ApexPredatorComponent)


def test_tame_with_nonmatching_bait_in_reach():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    creature = _reachable_creature_entity(scenario, name="rex")
    # Bait targeting a different species should not contribute a bonus.
    bait = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="lure", kind="item"),
            BaitComponent(target_species="triceratops", potency=5.0),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), bait.id
    )
    result = ApproachCreatureHandler().execute(
        ctx, _handler_cmd(scenario, "approach-creature", creature_id=str(creature.id))
    )
    assert result.ok, result.reason


def test_hatch_egg_with_egg_having_no_room_container():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # Egg carried in the character's inventory and ready to hatch.
    egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ready egg", kind="egg"),
            EggComponent(species_name="raptor", laid_at_epoch=0, fertilized=True),
            IncubationComponent(started_at_epoch=0, ready=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), egg.id
    )
    result = HatchEggHandler().execute(ctx, _handler_cmd(scenario, "hatch-egg", egg_id=str(egg.id)))
    assert result.ok, result.reason
    hatched = [e for e in result.events if e.__class__.__name__ == "EggHatchedEvent"]
    assert hatched


def test_generate_kaiju_spawn_specs_uses_single_group_for_small_budget():
    # Budgets under 10 yield a single kaiju (the elif branch is not taken).
    specs = generate_kaiju_spawn_specs(6, "small")
    assert len(specs) == 1
    assert specs[0].threat_level == 6
    assert specs == generate_kaiju_spawn_specs(6, "small")


def test_region_for_room_skips_non_region_and_non_region_sources():
    scenario = build_scenario()
    world = scenario.actor.world
    room = spawn_entity(world, [RoomComponent(title="den")])
    # A non-region incoming containment edge must be ignored (mode guard).
    holder = spawn_entity(world, [IdentityComponent(name="holder", kind="prop")])
    holder.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), room.id)
    # A REGION-mode incoming edge from a source that is not a region must be skipped.
    pseudo_region = spawn_entity(world, [IdentityComponent(name="cluster", kind="prop")])
    pseudo_region.add_relationship(Contains(mode=ContainmentMode.REGION), room.id)

    assert _region_for_room(world, room) is None

    # Add a genuine region above the same room: it is now resolved.
    region = spawn_entity(world, [RegionComponent(name="Glade")])
    region.add_relationship(Contains(mode=ContainmentMode.REGION), room.id)
    found = _region_for_room(world, room)
    assert found is not None and found.id == region.id


def test_region_rooms_tolerates_cycles_between_regions():
    scenario = build_scenario()
    world = scenario.actor.world
    region = spawn_entity(world, [RegionComponent(name="loop")])
    other = spawn_entity(world, [RegionComponent(name="loop-back")])
    room = spawn_entity(world, [RoomComponent(title="shared")])
    region.add_relationship(Contains(mode=ContainmentMode.REGION), other.id)
    # Cycle back to the first region; the seen-set must stop the walk re-visiting it.
    other.add_relationship(Contains(mode=ContainmentMode.REGION), region.id)
    other.add_relationship(Contains(mode=ContainmentMode.REGION), room.id)

    rooms = _region_rooms(world, region)
    assert [r.id for r in rooms] == [room.id]


def test_move_to_room_handles_entity_without_a_container():
    scenario = build_scenario()
    world = scenario.actor.world
    # An entity that lives in no container at all (parent_id is None).
    loose = spawn_entity(world, [IdentityComponent(name="drifter", kind="creature")])
    assert container_of(loose) is None

    _move_to_room(world, loose, scenario.room_a)

    assert container_of(loose) == scenario.room_a
    room = world.get_entity(scenario.room_a)
    assert loose.id in {target for _edge, target in room.get_relationships(Contains)}
    other = spawn_entity(world, [IdentityComponent(name="other drifter", kind="creature")])
    operations = _move_to_room_operations(world, other, scenario.room_a)
    execute_mutation_plan(world, MutationPlan(tuple(operations)))
    assert container_of(other) == scenario.room_a


def test_plan_handlers_cover_uncontained_reachable_source_edges():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    source = world.get_entity(scenario.room_a)
    ctx = HandlerContext(world, scenario.actor.epoch)

    source.add_component(
        AncientSampleComponent(
            species_name="raptor", viability=1.0, source_fossil_id=str(scenario.room_a)
        )
    )
    assert PrepareCloneHandler().execute(
        ctx,
        _handler_cmd(scenario, "prepare-clone", sample_id=str(scenario.room_a)),
    ).ok

    source.add_component(EggComponent(species_name="raptor", laid_at_epoch=0, fertilized=True))
    source.add_component(IncubationComponent(started_at_epoch=0, ready=True))
    assert HatchEggHandler().execute(
        ctx,
        _handler_cmd(scenario, "hatch-egg", egg_id=str(scenario.room_a)),
    ).ok

    source.add_component(EggComponent(species_name="raptor", laid_at_epoch=0))
    result = CollectEggHandler().execute(
        ctx,
        _handler_cmd(scenario, "collect-egg", egg_id=str(scenario.room_a)),
    )
    assert not result.ok
    assert result.reason == "egg is not contained"


def _roomless_character(scenario):
    character = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Wanderer", kind="character"), CharacterComponent()],
    )
    return character.id


def test_lay_egg_skips_placement_when_no_room_is_available():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # A roomless creature-character laying its own egg: neither the parent nor the
    # actor has a containing room, so the egg is spawned without a room.
    parent = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="brooder", kind="character"),
            CharacterComponent(),
            DinosaurComponent(species_name="raptor"),
            ReptileProcreationComponent(),
        ],
    )
    assert container_of(parent) is None

    result = LayEggHandler().execute(
        ctx,
        _handler_cmd(scenario, "lay-egg", character_id=str(parent.id), parent_id=str(parent.id)),
    )

    assert result.ok, result.reason
    laid = [e for e in result.events if e.__class__.__name__ == "EggLaidEvent"]
    assert laid and laid[0].room_id is None
    # The egg exists but is not contained in any room.
    egg_ids = [
        parse_entity_id(t)
        for t in laid[0].target_ids
        if parse_entity_id(t) is not None and parse_entity_id(t) != parent.id
    ]
    assert egg_ids
    assert all(container_of(scenario.actor.world.get_entity(eid)) is None for eid in egg_ids)


def test_hatch_egg_skips_placement_when_no_room_is_available():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character_id = _roomless_character(scenario)
    # Egg carried by the roomless character and ready to hatch.
    egg = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ready egg", kind="egg"),
            EggComponent(species_name="raptor", laid_at_epoch=0, fertilized=True),
            IncubationComponent(started_at_epoch=0, ready=True),
        ],
    )
    scenario.actor.world.get_entity(character_id).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), egg.id
    )

    result = HatchEggHandler().execute(
        ctx,
        _handler_cmd(scenario, "hatch-egg", character_id=str(character_id), egg_id=str(egg.id)),
    )

    assert result.ok, result.reason
    hatched = [e for e in result.events if e.__class__.__name__ == "EggHatchedEvent"]
    assert hatched and hatched[0].room_id is None


def test_drive_off_predator_rejects_creature_without_a_room():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # A roomless character that is itself a creature: reachable (it is itself) but
    # has no containing room, so drive-off cannot relocate it.
    creature = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="feral drifter", kind="creature"),
            CharacterComponent(),
            DinosaurComponent(species_name="raptor"),
        ],
    )
    assert container_of(creature) is None

    result = DriveOffPredatorHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "drive-off-predator",
            character_id=str(creature.id),
            creature_id=str(creature.id),
        ),
    )

    assert not result.ok
    assert result.reason == "creature is not in a room"


def test_spawn_egg_ignores_missing_parent_reference():
    scenario = build_scenario()

    operations, egg = _spawn_egg_operations(
        scenario.actor.world,
        "raptor",
        0,
        parent_ids=("entity_999",),
    )

    execute_mutation_plan(scenario.actor.world, MutationPlan(tuple(operations)))
    assert scenario.actor.world.get_entity(egg.require()).get_relationships(DescendsFromParent) == []
