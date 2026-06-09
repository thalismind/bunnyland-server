"""Tests for dino-sim fossil, egg, and kaiju incident mechanics."""

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
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.components import CharacterComponent
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.core.handlers import HandlerContext
from bunnyland.mechanics.colonysim import install_colonysim
from bunnyland.mechanics.dinosim import (
    AncientSampleComponent,
    ApexPredatorAppearedEvent,
    ApexPredatorComponent,
    ApproachCreatureHandler,
    ArmorPlateComponent,
    ArmyCalledEvent,
    ArmyResponseComponent,
    BaitComponent,
    BaitSetEvent,
    BuildEnclosureHandler,
    CallForHelpHandler,
    ChargeComponent,
    CommandCompanionHandler,
    CommandComponent,
    CommandTrainedEvent,
    CompanionCommandedEvent,
    CompanionComponent,
    ContainmentProtocolComponent,
    ContainmentTriggeredEvent,
    CreatureAttackComponent,
    CreatureAttackedEvent,
    CreatureChargedEvent,
    CreatureEscapedEvent,
    CreatureMountedEvent,
    CreatureRecalledEvent,
    CreatureRecapturedEvent,
    CreatureRoaredEvent,
    CreatureTamedEvent,
    CreatureTrackedEvent,
    CreatureTrampledEvent,
    CreatureTranquilizedEvent,
    DinosaurComponent,
    DodgeCreatureHandler,
    DriveOffPredatorHandler,
    EggComponent,
    EggHatchedEvent,
    EggLaidEvent,
    EnclosureBuiltEvent,
    EnclosureComponent,
    EvacuateRoomHandler,
    ExtractAncientSampleHandler,
    FeedingPenComponent,
    FenceComponent,
    FenceRepairedEvent,
    FertilityComponent,
    FertilizeEggHandler,
    FightCreatureHandler,
    FossilFragmentComponent,
    FossilIdentifiedEvent,
    GateComponent,
    GateReinforcedEvent,
    GrappleComponent,
    GuardBehaviorComponent,
    HatchEggHandler,
    HiddenFromCreatureEvent,
    HideFromCreatureHandler,
    IdentifyFossilHandler,
    IncubateEggHandler,
    IncubationComponent,
    KaijuArrivedEvent,
    KaijuComponent,
    LayEggHandler,
    LockPenHandler,
    MountComponent,
    MountCreatureHandler,
    OpenPenHandler,
    PackHuntComponent,
    PenLockedEvent,
    PenOpenedEvent,
    PredatorDrivenOffEvent,
    PrepareCloneHandler,
    QuarantinePenComponent,
    RecallComponent,
    RecallCreatureHandler,
    RecaptureCreatureHandler,
    ReinforceGateHandler,
    RepairDamageHandler,
    RepairFenceHandler,
    ReptileProcreationComponent,
    RoarComponent,
    RoomEvacuatedEvent,
    SetBaitHandler,
    SettlementDamageComponent,
    SettlementDamageRepairedEvent,
    SignalArmyHandler,
    SpeciesComponent,
    SpeciesIdentificationComponent,
    TameCreatureHandler,
    TamingProgressedEvent,
    TargetWeakPointHandler,
    TrackComponent,
    TrackCreatureHandler,
    TrainCommandHandler,
    TrainingComponent,
    TrampleComponent,
    TranquilizeCreatureHandler,
    TranquilizerComponent,
    TriggerContainmentHandler,
    WeakPointComponent,
    WeakPointHitEvent,
    _entity_room_id,
    _species_name,
    dinosim_fragments,
    install_dinosim,
)
from bunnyland.mechanics.lifesim import LifeStageComponent
from bunnyland.mechanics.storyteller import (
    IncidentBudgetComponent,
    IncidentComponent,
    StorytellerComponent,
    StorytellerConsequence,
)

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
            "identify-fossil",
            fossil_id=str(fossil.id),
            species_name="velociraptor",
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "extract-ancient-sample", fossil_id=str(fossil.id))
    )
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

    await scenario.actor.submit(
        _cmd(scenario, "prepare-clone", sample_id=str(samples[0].id))
    )
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
        "velociraptor" in line
        for line in dinosim_fragments(scenario.actor.world, character)
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
            "command-companion",
            creature_id=str(raptor.id),
            command_name="guard",
            target_id=str(scenario.room_a),
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
            "build-enclosure",
            room_id=str(scenario.room_a),
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
        _cmd(scenario, "identify-fossil", fossil_id="not-an-id", species_name="raptor")
    )
    await scenario.actor.submit(
        _cmd(scenario, "identify-fossil", fossil_id="entity_999", species_name="raptor")
    )
    await scenario.actor.submit(
        _cmd(scenario, "identify-fossil", fossil_id=str(non_fossil.id), species_name="raptor")
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
                "identify-fossil",
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
                "identify-fossil",
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
                "command-companion",
                creature_id=str(other_companion.id),
                command_name="guard",
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
    scenario.actor.register_consequence(StorytellerConsequence())
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
    scenario.actor.register_consequence(StorytellerConsequence())
    spawn_entity(
        scenario.actor.world,
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
    assert any(entity.has_component(KaijuComponent) for entity in _room_contents(scenario))
