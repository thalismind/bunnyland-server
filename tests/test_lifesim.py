"""Tests for life-sim romance, pregnancy, and family mechanics (spec 20.5-20.6)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    ControlledBy,
    IdentityComponent,
    Lane,
    LLMControllerComponent,
    SuspendedComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import (
    AdoptionCompletedEvent,
    BirthDueEvent,
    BirthResolvedEvent,
    CommandRejectedEvent,
    PartnershipStartedEvent,
)
from bunnyland.mechanics.lifesim import (
    AdoptChildHandler,
    AspirationComponent,
    BirthDueComponent,
    ChooseAspirationHandler,
    CompleteMilestoneHandler,
    LifeStageComponent,
    MilestoneCompletedEvent,
    ParentOf,
    PartnerOf,
    PregnancyComponent,
    ReproductiveComponent,
    ResolveBirthHandler,
    StartPartnershipHandler,
    StartPregnancyHandler,
    install_lifesim,
    lifesim_fragments,
)
from bunnyland.mechanics.policy import (
    BoundaryTag,
    CharacterBoundaryComponent,
    install_policy,
)

HOUR = 3600.0
LIFE_TAGS = frozenset({BoundaryTag.ROMANCE, BoundaryTag.ADULT, BoundaryTag.PREGNANCY})


def _install(actor):
    install_policy(actor, enabled=LIFE_TAGS)
    install_lifesim(actor)
    actor.register_handler(StartPartnershipHandler())
    actor.register_handler(StartPregnancyHandler())
    actor.register_handler(ResolveBirthHandler())
    actor.register_handler(AdoptChildHandler())
    actor.register_handler(ChooseAspirationHandler())
    actor.register_handler(CompleteMilestoneHandler())


def _co_parent(scenario, *, boundary=None):
    components = [
        IdentityComponent(name="Hazel", kind="character"),
        CharacterComponent(species="bunny"),
        ReproductiveComponent(can_cause_pregnancy=True, species_group="bunny"),
    ]
    if boundary is not None:
        components.append(boundary)
    entity = spawn_entity(scenario.actor.world, components)
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


def _child(scenario, *, name="Clover"):
    entity = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=name, kind="character"),
            CharacterComponent(species="bunny"),
            LifeStageComponent(stage="child"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


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


async def test_aspiration_milestone_completion_can_reward_inventory_item():
    scenario = build_scenario()
    _install(scenario.actor)
    completed: list[MilestoneCompletedEvent] = []
    scenario.actor.bus.subscribe(MilestoneCompletedEvent, completed.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "choose-aspiration",
            name="Cozy Homemaker",
            milestones=("meet a friend",),
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "complete-milestone",
            milestone="meet a friend",
            reward_name="woven keepsake",
        )
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    aspiration = character.get_component(AspirationComponent)
    assert aspiration.name == "Cozy Homemaker"
    assert aspiration.completed == ("meet a friend",)
    reward_id = completed[0].reward_item_id
    assert reward_id is not None
    inventory_ids = {str(target_id) for _edge, target_id in character.get_relationships(Contains)}
    assert reward_id in inventory_ids


async def test_start_partnership_creates_bidirectional_edges():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _co_parent(scenario)
    started: list[PartnershipStartedEvent] = []
    scenario.actor.bus.subscribe(PartnershipStartedEvent, started.append)

    await scenario.actor.submit(_cmd(scenario, "start-partnership", target_id=str(target)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    partner = scenario.actor.world.get_entity(target)
    assert character.has_relationship(PartnerOf, target)
    assert partner.has_relationship(PartnerOf, scenario.character)
    assert started[0].partner_id == str(target)


async def test_start_pregnancy_requires_policy_consent():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        ReproductiveComponent(can_be_pregnant=True, species_group="bunny")
    )
    target = _co_parent(
        scenario,
        boundary=CharacterBoundaryComponent(denied=frozenset({BoundaryTag.PREGNANCY})),
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "start-pregnancy", co_parent_id=str(target), due_in_seconds=HOUR)
    )
    await scenario.actor.tick(HOUR)

    assert not character.has_component(PregnancyComponent)
    assert any("consented" in r.reason for r in rejects)


async def test_pregnancy_becomes_due_while_suspended_but_birth_waits_for_resume():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        ReproductiveComponent(can_be_pregnant=True, species_group="bunny")
    )
    target = _co_parent(scenario)
    due: list[BirthDueEvent] = []
    scenario.actor.bus.subscribe(BirthDueEvent, due.append)

    await scenario.actor.submit(
        _cmd(scenario, "start-pregnancy", co_parent_id=str(target), due_in_seconds=HOUR)
    )
    await scenario.actor.tick(0.0)
    assert character.has_component(PregnancyComponent)

    suspended_controller = spawn_entity(scenario.actor.world)
    scenario.actor.suspend(scenario.character, suspended_controller.id)
    await scenario.actor.tick(HOUR * 2)

    assert character.has_component(SuspendedComponent)
    assert character.has_component(BirthDueComponent)
    assert len(due) == 1
    children = [
        target_id for _edge, target_id in character.get_relationships(ParentOf)
    ]
    assert children == []


async def test_relationship_pregnancy_and_birth_create_llm_controlled_child():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        ReproductiveComponent(can_be_pregnant=True, species_group="bunny")
    )
    target = _co_parent(scenario)
    resolved: list[BirthResolvedEvent] = []
    scenario.actor.bus.subscribe(BirthResolvedEvent, resolved.append)

    await scenario.actor.submit(
        _cmd(scenario, "start-partnership", target_id=str(target))
    )
    await scenario.actor.tick(HOUR)
    assert character.has_relationship(PartnerOf, target)

    await scenario.actor.submit(
        _cmd(scenario, "start-pregnancy", co_parent_id=str(target), due_in_seconds=HOUR)
    )
    await scenario.actor.tick(0.0)
    await scenario.actor.tick(HOUR * 2)
    await scenario.actor.submit(_cmd(scenario, "resolve-birth", child_name="Clover"))
    await scenario.actor.tick(HOUR)

    assert not character.has_component(PregnancyComponent)
    assert not character.has_component(BirthDueComponent)
    child_id = resolved[0].child_id
    child = scenario.actor.world.get_entity(
        next(target_id for _edge, target_id in character.get_relationships(ParentOf))
    )
    assert str(child.id) == child_id
    assert child.get_component(IdentityComponent).name == "Clover"
    assert child.get_component(LifeStageComponent).stage == "child"
    assert scenario.actor.world.get_entity(target).has_relationship(ParentOf, child.id)
    controllers = [
        target_id
        for _edge, target_id in child.get_relationships(ControlledBy)
    ]
    assert len(controllers) == 1
    controller = scenario.actor.world.get_entity(controllers[0])
    assert controller.has_component(LLMControllerComponent)


async def test_adopt_child_creates_parent_edge():
    scenario = build_scenario()
    _install(scenario.actor)
    child = _child(scenario)
    adopted: list[AdoptionCompletedEvent] = []
    scenario.actor.bus.subscribe(AdoptionCompletedEvent, adopted.append)

    await scenario.actor.submit(_cmd(scenario, "adopt-child", child_id=str(child)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(ParentOf, child)
    assert adopted[0].child_id == str(child)
    assert adopted[0].parent_id == str(scenario.character)


async def test_adopt_child_rejects_non_child_target():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _co_parent(scenario)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "adopt-child", child_id=str(target)))
    await scenario.actor.tick(HOUR)

    assert any(r.reason == "target is not a child" for r in rejects)


def test_lifesim_fragments_describe_partner_and_pregnancy():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    partner = _co_parent(scenario)
    child = _child(scenario)
    character.add_relationship(PartnerOf(since_epoch=0), partner)
    character.add_relationship(ParentOf(), child)
    character.add_component(
        PregnancyComponent(started_at_epoch=0, due_at_epoch=10, co_parent_ids=(str(partner),))
    )

    fragments = lifesim_fragments(scenario.actor.world, character)

    assert any("partners with Hazel" in line for line in fragments)
    assert any("pregnant" in line for line in fragments)
    assert any("Your children: Clover" in line for line in fragments)


def test_lifesim_fragments_describe_parents():
    scenario = build_scenario()
    child = _child(scenario)
    parent = scenario.actor.world.get_entity(scenario.character)
    parent.add_relationship(ParentOf(), child)

    fragments = lifesim_fragments(scenario.actor.world, scenario.actor.world.get_entity(child))

    assert any("Your parents: Juniper" in line for line in fragments)
