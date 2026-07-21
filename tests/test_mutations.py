"""Transactional mutation-plan contracts."""

from dataclasses import dataclass, replace

import pytest
from conftest import build_scenario
from relics import DuplicateComponentError, Edge

from bunnyland.core import (
    ActionPointsComponent,
    AddComponent,
    AddEdge,
    AddEntity,
    ContainmentMode,
    Contains,
    ControlledBy,
    DeleteEntity,
    EntityReference,
    IdentityComponent,
    MutationError,
    MutationPlan,
    RemoveComponent,
    RemoveEdge,
    SetComponent,
    SetComponentFactory,
    SleepingComponent,
    WorldClockComponent,
    WorldInfoComponent,
    execute_mutation_plan,
    replace_single_edge_operations,
    spawn_entity,
    validate_core_invariants,
)
from bunnyland.core.handlers.base import planned


@dataclass(frozen=True)
class SampleLink(Edge):
    value: int = 0


def test_replace_single_edge_operations_adds_replaces_and_removes(scenario):
    world = scenario.actor.world
    source = world.get_entity(scenario.character)

    execute_mutation_plan(
        world,
        MutationPlan(replace_single_edge_operations(source, scenario.room_a, SampleLink(value=1))),
    )
    assert source.get_relationships(SampleLink) == [(SampleLink(value=1), scenario.room_a)]

    execute_mutation_plan(
        world,
        MutationPlan(replace_single_edge_operations(source, scenario.room_b, SampleLink(value=2))),
    )
    assert source.get_relationships(SampleLink) == [(SampleLink(value=2), scenario.room_b)]

    execute_mutation_plan(
        world,
        MutationPlan(replace_single_edge_operations(source, None, SampleLink())),
    )
    assert source.get_relationships(SampleLink) == []


def test_plan_preflights_every_operation_before_mutating(scenario):
    character = scenario.actor.world.get_entity(scenario.character)
    identity = character.get_component(IdentityComponent)
    plan = MutationPlan(
        operations=(
            SetComponent(scenario.character, replace(identity, name="changed")),
            RemoveComponent(scenario.character, str),  # type: ignore[arg-type]
        )
    )

    with pytest.raises(MutationError, match="does not have component str"):
        execute_mutation_plan(scenario.actor.world, plan)
    assert character.get_component(IdentityComponent).name == identity.name


def test_mutation_plan_validates_only_its_write_set(scenario):
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    unrelated = spawn_entity(world, [IdentityComponent("unrelated", "item")])
    points = character.get_component(ActionPointsComponent)
    character.remove_component(ActionPointsComponent)
    character.add_component(replace(points, current=-1))

    execute_mutation_plan(
        world,
        MutationPlan((SetComponent(unrelated.id, IdentityComponent("updated", "item")),)),
    )

    assert unrelated.get_component(IdentityComponent).name == "updated"
    with pytest.raises(MutationError, match="out-of-bounds ActionPointsComponent"):
        validate_core_invariants(world)


def test_remove_edge_apply_rejects_an_unresolved_reference(scenario):
    with pytest.raises(MutationError, match="target reference has not been created"):
        RemoveEdge(scenario.room_a, EntityReference(), Contains).apply(scenario.actor.world)


def test_failed_invariant_rolls_back_components_and_edges(scenario):
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    points = character.get_component(ActionPointsComponent)
    plan = MutationPlan(
        operations=(
            AddEdge(
                scenario.room_b,
                scenario.character,
                Contains(mode=ContainmentMode.ROOM_CONTENT),
            ),
            SetComponent(scenario.character, replace(points, current=-1)),
        )
    )

    with pytest.raises(MutationError, match="more than one physical location"):
        execute_mutation_plan(world, plan)
    assert character.get_component(ActionPointsComponent) == points
    assert not world.get_entity(scenario.room_b).has_relationship(Contains, scenario.character)


def test_successful_plan_returns_typed_summary_and_inverse_operations_work(scenario):
    world = scenario.actor.world
    item = spawn_entity(world, [IdentityComponent(name="parcel", kind="item")])
    room = world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), item.id)
    plan = MutationPlan(
        operations=(
            RemoveEdge(scenario.room_a, item.id, Contains),
            AddEdge(
                scenario.character,
                item.id,
                Contains(mode=ContainmentMode.INVENTORY),
            ),
            AddEntity((IdentityComponent(name="receipt", kind="paper"),)),
        )
    )

    summary = execute_mutation_plan(world, plan)

    assert [entry["op"] for entry in summary] == ["remove_edge", "add_edge", "add_entity"]
    assert world.get_entity(scenario.character).has_relationship(Contains, item.id)


def test_mutation_preflight_rejects_missing_entities_duplicates_and_edges(scenario):
    identity = IdentityComponent(name="duplicate", kind="item")
    with pytest.raises(MutationError, match="duplicate component"):
        execute_mutation_plan(
            scenario.actor.world,
            MutationPlan((AddEntity((identity, identity)),)),
        )
    with pytest.raises(MutationError, match="does not exist"):
        execute_mutation_plan(
            scenario.actor.world,
            MutationPlan((SetComponent("entity_999999", identity),)),
        )
    with pytest.raises(MutationError, match="does not have Contains edge"):
        execute_mutation_plan(
            scenario.actor.world,
            MutationPlan((RemoveEdge(scenario.room_b, scenario.character, Contains),)),
        )


def test_rollback_removes_new_components_entities_and_restores_removed_components(scenario):
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    identity = character.get_component(IdentityComponent)
    before_ids = {entity.id for entity in world.query().execute_entities()}

    def fail(_world):
        raise MutationError("plan assertion failed")

    plan = MutationPlan(
        operations=(
            AddEntity((IdentityComponent(name="temporary", kind="item"),)),
            SetComponent(scenario.room_a, IdentityComponent(name="room label", kind="room")),
            RemoveComponent(scenario.character, IdentityComponent),
        ),
        invariants=(fail,),
    )
    with pytest.raises(MutationError, match="plan assertion failed"):
        execute_mutation_plan(world, plan)

    assert {entity.id for entity in world.query().execute_entities()} == before_ids
    assert character.get_component(IdentityComponent) == identity
    assert not world.get_entity(scenario.room_a).has_component(IdentityComponent)

    set_summary = execute_mutation_plan(
        world,
        MutationPlan((SetComponent(scenario.room_a, IdentityComponent(name="room", kind="room")),)),
    )
    remove_summary = execute_mutation_plan(
        world, MutationPlan((RemoveComponent(scenario.room_a, IdentityComponent),))
    )
    assert set_summary[0]["op"] == "set_component"
    assert remove_summary[0]["op"] == "remove_component"


def test_core_invariants_reject_clock_controller_and_meter_violations(scenario):
    world = scenario.actor.world
    clock = next(world.query().with_all([WorldClockComponent]).execute_entities())
    world.remove(clock.id)
    with pytest.raises(MutationError, match="exactly one world clock"):
        validate_core_invariants(world)

    missing_info_scenario = build_scenario()
    missing_info_scenario.actor._clock_entity.remove_component(WorldInfoComponent)
    with pytest.raises(MutationError, match="exactly one world info"):
        validate_core_invariants(missing_info_scenario.actor.world)

    misplaced_info_scenario = build_scenario()
    misplaced_info_scenario.actor._clock_entity.remove_component(WorldInfoComponent)
    spawn_entity(misplaced_info_scenario.actor.world, [WorldInfoComponent()])
    with pytest.raises(MutationError, match="stored on the world clock"):
        validate_core_invariants(misplaced_info_scenario.actor.world)

    duplicate_info_scenario = build_scenario()
    spawn_entity(duplicate_info_scenario.actor.world, [WorldInfoComponent()])
    with pytest.raises(MutationError, match="exactly one world info"):
        validate_core_invariants(duplicate_info_scenario.actor.world)

    # Each violation uses a fresh scenario because the invariant checker is fail-fast.
    controller_scenario = build_scenario()
    other = spawn_entity(controller_scenario.actor.world)
    character = controller_scenario.actor.world.get_entity(controller_scenario.character)
    character.add_relationship(ControlledBy(), other.id)
    with pytest.raises(MutationError, match="more than one active controller"):
        validate_core_invariants(controller_scenario.actor.world)

    meter_scenario = build_scenario()
    meter_character = meter_scenario.actor.world.get_entity(meter_scenario.character)
    points = meter_character.get_component(ActionPointsComponent)
    meter_character.remove_component(ActionPointsComponent)
    meter_character.add_component(replace(points, current=points.maximum + 1))
    with pytest.raises(MutationError, match="out-of-bounds ActionPointsComponent"):
        validate_core_invariants(meter_scenario.actor.world)


def test_planned_handler_result_carries_plan():
    plan = MutationPlan()
    result = planned(plan)
    assert result.ok is True
    assert result.plan is plan


def test_entity_references_resolve_and_reset_when_post_apply_work_fails(scenario):
    world = scenario.actor.world
    reference = EntityReference()
    before_ids = {entity.id for entity in world.query().execute_entities()}
    plan = MutationPlan(
        (
            AddEntity(
                (IdentityComponent(name="referenced", kind="item"),),
                reference=reference,
            ),
            AddEdge(reference, scenario.room_a, ControlledBy()),
        )
    )

    def fail():
        assert reference.require() is not None
        raise MutationError("after apply failed")

    with pytest.raises(MutationError, match="after apply failed"):
        execute_mutation_plan(world, plan, after_apply=fail)
    assert reference.entity_id is None
    assert {entity.id for entity in world.query().execute_entities()} == before_ids

    with pytest.raises(MutationError, match="has not been created"):
        reference.require()
    assert str(reference) == "$new"


def test_component_factory_resolves_prior_reference_and_rolls_back(scenario):
    reference = EntityReference()
    character = scenario.actor.world.get_entity(scenario.character)
    identity = character.get_component(IdentityComponent)

    def fail(_world):
        raise MutationError("forced failure")

    with pytest.raises(MutationError, match="forced failure"):
        execute_mutation_plan(
            scenario.actor.world,
            MutationPlan(
                (
                    AddEntity(
                        (IdentityComponent(name="created", kind="item"),),
                        reference=reference,
                    ),
                    SetComponentFactory(
                        scenario.character,
                        IdentityComponent,
                        lambda: replace(identity, name=str(reference.require())),
                    ),
                ),
                invariants=(fail,),
            ),
        )

    assert reference.entity_id is None
    assert character.get_component(IdentityComponent) == identity


def test_component_factory_validates_type_and_removes_new_component_on_rollback(scenario):
    character = scenario.actor.world.get_entity(scenario.character)
    operation = SetComponentFactory(
        scenario.character,
        SleepingComponent,
        lambda: SleepingComponent(started_at_epoch=3),
    )

    def fail(_world):
        raise MutationError("forced failure")

    with pytest.raises(MutationError, match="forced failure"):
        execute_mutation_plan(
            scenario.actor.world,
            MutationPlan((operation,), invariants=(fail,)),
        )
    assert not character.has_component(SleepingComponent)
    assert operation.summary()["component"] == "SleepingComponent"

    wrong = SetComponentFactory(
        scenario.character,
        SleepingComponent,
        lambda: IdentityComponent(name="wrong", kind="item"),
    )
    with pytest.raises(MutationError, match="expected SleepingComponent"):
        execute_mutation_plan(scenario.actor.world, MutationPlan((wrong,)))


def test_add_edge_reference_target_and_overwrite_rollback(scenario):
    world = scenario.actor.world
    reference = EntityReference()
    summary, created_id = execute_mutation_plan(
        world,
        MutationPlan(
            (
                AddEntity(
                    (IdentityComponent(name="target", kind="item"),),
                    reference=reference,
                ),
                AddEdge(
                    scenario.room_a,
                    reference,
                    Contains(mode=ContainmentMode.ROOM_CONTENT),
                ),
            )
        ),
        after_apply=reference.require,
    )
    assert str(reference) == str(created_id)
    assert summary[-1]["target_id"] == str(created_id)

    character = world.get_entity(scenario.character)
    [original] = character.get_relationships(ControlledBy)

    def fail(_world):
        raise MutationError("restore overwritten edge")

    with pytest.raises(MutationError, match="restore overwritten edge"):
        execute_mutation_plan(
            world,
            MutationPlan(
                (
                    AddEdge(
                        scenario.character,
                        scenario.controller,
                        ControlledBy(generation=99),
                    ),
                ),
                invariants=(fail,),
            ),
        )
    assert character.get_relationships(ControlledBy) == [original]


def test_delete_is_deferred_until_post_apply_work_succeeds(scenario):
    world = scenario.actor.world
    item = spawn_entity(world, [IdentityComponent(name="parcel", kind="item")])
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), item.id
    )

    def fail():
        assert world.has_entity(item.id)
        raise MutationError("receipt construction failed")

    with pytest.raises(MutationError, match="receipt construction failed"):
        execute_mutation_plan(
            world,
            MutationPlan(
                (
                    SetComponent(item.id, IdentityComponent(name="changed", kind="item")),
                    DeleteEntity(item.id),
                )
            ),
            after_apply=fail,
        )

    restored = world.get_entity(item.id)
    assert restored.get_component(IdentityComponent).name == "parcel"
    assert world.get_entity(scenario.room_a).has_relationship(Contains, item.id)


def test_delete_commits_after_validation_and_removes_relationships(scenario):
    world = scenario.actor.world
    item = spawn_entity(world, [IdentityComponent(name="parcel", kind="item")])
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), item.id
    )

    summary = execute_mutation_plan(world, MutationPlan((DeleteEntity(item.id),)))

    assert summary == ({"op": "delete_entity", "entity_id": str(item.id)},)
    assert not world.has_entity(item.id)
    assert not world.get_entity(scenario.room_a).has_relationship(Contains, item.id)


def test_delete_rejects_unsafe_terminal_plans(scenario):
    world = scenario.actor.world
    item = spawn_entity(world, [IdentityComponent(name="parcel", kind="item")])
    clock = next(world.query().with_all([WorldClockComponent]).execute_entities())

    with pytest.raises(MutationError, match="custom invariants"):
        execute_mutation_plan(
            world,
            MutationPlan((DeleteEntity(item.id),), invariants=(lambda _world: None,)),
        )
    with pytest.raises(MutationError, match="more than once"):
        execute_mutation_plan(
            world,
            MutationPlan((DeleteEntity(item.id), DeleteEntity(item.id))),
        )
    with pytest.raises(MutationError, match="world clock cannot be deleted"):
        execute_mutation_plan(world, MutationPlan((DeleteEntity(clock.id),)))

    reference = EntityReference()
    with pytest.raises(MutationError, match="reference has not been created"):
        execute_mutation_plan(world, MutationPlan((DeleteEntity(reference),)))
    assert world.has_entity(item.id)
    assert world.has_entity(clock.id)


def test_plan_can_create_modify_and_delete_a_referenced_entity(scenario):
    world = scenario.actor.world
    reference = EntityReference()

    summary = execute_mutation_plan(
        world,
        MutationPlan(
            (
                AddEntity(reference=reference),
                AddComponent(reference, IdentityComponent(name="temporary", kind="item")),
                AddEdge(
                    scenario.room_a,
                    reference,
                    Contains(mode=ContainmentMode.ROOM_CONTENT),
                ),
                RemoveEdge(scenario.room_a, reference, Contains),
                DeleteEntity(reference),
            )
        ),
    )

    assert [entry["op"] for entry in summary] == [
        "add_entity",
        "add_component",
        "add_edge",
        "remove_edge",
        "delete_entity",
    ]
    assert reference.entity_id is not None
    assert not world.has_entity(reference.require())


def test_preflight_accepts_state_supplied_by_an_earlier_operation(scenario):
    world = scenario.actor.world
    item = spawn_entity(world)

    summary = execute_mutation_plan(
        world,
        MutationPlan(
            (
                AddComponent(item.id, IdentityComponent(name="temporary", kind="item")),
                RemoveComponent(item.id, IdentityComponent),
                AddEdge(
                    scenario.room_a,
                    item.id,
                    Contains(mode=ContainmentMode.ROOM_CONTENT),
                ),
                RemoveEdge(scenario.room_a, item.id, Contains),
            )
        ),
    )

    assert [entry["op"] for entry in summary] == [
        "add_component",
        "remove_component",
        "add_edge",
        "remove_edge",
    ]
    assert not item.has_component(IdentityComponent)
    assert not world.get_entity(scenario.room_a).has_relationship(Contains, item.id)

    reference = EntityReference(item.id)
    execute_mutation_plan(
        world,
        MutationPlan(
            (
                AddComponent(reference, IdentityComponent(name="temporary", kind="item")),
                RemoveComponent(reference, IdentityComponent),
            )
        ),
    )


def test_add_component_rejects_existing_live_and_new_prefab_components(scenario):
    world = scenario.actor.world
    item = spawn_entity(world, [IdentityComponent(name="existing", kind="item")])

    with pytest.raises(MutationError, match="already has component IdentityComponent"):
        execute_mutation_plan(
            world,
            MutationPlan(
                (AddComponent(item.id, IdentityComponent(name="duplicate", kind="item")),)
            ),
        )

    world.register_prefab(
        "labeled-reference",
        {IdentityComponent: IdentityComponent(name="default", kind="item")},
    )
    reference = EntityReference()
    before_ids = {entity.id for entity in world.query().execute_entities()}
    with pytest.raises(MutationError, match="already has component IdentityComponent"):
        execute_mutation_plan(
            world,
            MutationPlan(
                (
                    AddEntity(reference=reference, prefab="labeled-reference"),
                    AddComponent(
                        reference,
                        IdentityComponent(name="duplicate", kind="item"),
                    ),
                )
            ),
        )
    assert reference.entity_id is None
    assert {entity.id for entity in world.query().execute_entities()} == before_ids


def test_prefab_entity_creation_rolls_back_when_component_addition_fails(scenario):
    world = scenario.actor.world
    world.register_prefab(
        "labeled",
        {IdentityComponent: IdentityComponent(name="default", kind="item")},
    )
    before_ids = {entity.id for entity in world.query().execute_entities()}

    with pytest.raises(DuplicateComponentError, match="already has component IdentityComponent"):
        execute_mutation_plan(
            world,
            MutationPlan(
                (
                    AddEntity(
                        (IdentityComponent(name="duplicate", kind="item"),),
                        prefab="labeled",
                    ),
                )
            ),
        )

    assert {entity.id for entity in world.query().execute_entities()} == before_ids
