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
    spawn_entity,
)
from bunnyland.core.components import CharacterComponent
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.colonysim import install_colonysim
from bunnyland.mechanics.dinosim import (
    AncientSampleComponent,
    DinosaurComponent,
    EggComponent,
    EggHatchedEvent,
    EggLaidEvent,
    ExtractAncientSampleHandler,
    FertilityComponent,
    FertilizeEggHandler,
    FossilFragmentComponent,
    FossilIdentifiedEvent,
    HatchEggHandler,
    IdentifyFossilHandler,
    IncubateEggHandler,
    IncubationComponent,
    KaijuComponent,
    LayEggHandler,
    PrepareCloneHandler,
    ReptileProcreationComponent,
    SettlementDamageComponent,
    SpeciesIdentificationComponent,
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
