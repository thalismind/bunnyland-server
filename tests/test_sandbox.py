"""Sandbox plugin, generation matrix, and After Dark access tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import execute_handler

from bunnyland.core import (
    CharacterComponent,
    GenerationIntentComponent,
    HandlerContext,
    IdentityComponent,
    MoveHandler,
    RoomComponent,
    SuspendedComponent,
    WorldActor,
    build_submitted_command,
    container_of,
    replace_component,
    spawn_entity,
)
from bunnyland.core.edges import ContainmentMode, Contains
from bunnyland.foundation.policy.mechanics import (
    BoundaryTag,
    CharacterBoundaryComponent,
    WorldPolicyComponent,
)
from bunnyland.plugins import apply_plugins, bunnyland_plugins, resolve_order, select
from bunnyland.plugins.ids import CORE_VERBS, POLICY, TOONSIM, WORLDGEN
from bunnyland.sandbox.generation import _enabled_regions, sandbox_generator
from bunnyland.sandbox.mechanics import (
    AFTER_DARK_SCOPE,
    AcceptAfterDarkWarningHandler,
    AfterDarkEntranceComponent,
    AfterDarkExitComponent,
    AfterDarkPassage,
    EnterAfterDarkHandler,
    LeaveAfterDarkHandler,
    WithdrawAfterDarkConsentHandler,
)
from bunnyland.sandbox.plugin import SANDBOX_PLUGIN_ID
from bunnyland.sandbox.plugin import bunnyland_plugins as sandbox_plugins
from bunnyland.sandbox.plugin import plugin as sandbox_plugin
from bunnyland.sandbox.regions import REGIONS
from bunnyland.worldgen import GenOptions, collect_generators

BASE_PLUGIN_IDS = (CORE_VERBS, WORLDGEN, POLICY, SANDBOX_PLUGIN_ID)


def _command(character_id, command_type: str, payload: dict[str, object] | None = None):
    return build_submitted_command(
        character_id=str(character_id),
        controller_id="controller_1",
        controller_generation=1,
        command_type=command_type,
        payload=payload,
    )


async def _generate(enabled_ids: tuple[str, ...] | None):
    discovered = list(bunnyland_plugins())
    plugins = select(discovered, enabled_ids)
    actor = WorldActor()
    apply_plugins(plugins, actor)
    generator = collect_generators(plugins)["bunnyland-sandbox"]
    result = await generator.generate(actor, "sandbox-test", GenOptions())
    return actor, result


def _semantic_summary(actor: WorldActor) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    rows = []
    for entity in actor.world.query().execute_entities():
        name = ""
        if entity.has_component(IdentityComponent):
            name = entity.get_component(IdentityComponent).name
        elif entity.has_component(RoomComponent):
            name = entity.get_component(RoomComponent).title
        wants = ()
        if entity.has_component(GenerationIntentComponent):
            wants = entity.get_component(GenerationIntentComponent).wants
        if name:
            rows.append((type(entity).__name__, name, wants))
    return tuple(sorted(rows))


def test_sandbox_plugin_uses_existing_contribution_surfaces() -> None:
    definition = sandbox_plugin()

    assert definition.id == SANDBOX_PLUGIN_ID
    assert definition.default_enabled is True
    assert definition.dependencies.requires == BASE_PLUGIN_IDS[:-1]
    assert [generator.name for generator in definition.content.world_generators] == [
        "bunnyland-sandbox"
    ]
    assert definition.runtime.http == ()
    assert definition.runtime.mcp == ()
    assert resolve_order(
        select(list(bunnyland_plugins()), BASE_PLUGIN_IDS)
    )[-1].id == SANDBOX_PLUGIN_ID
    assert [candidate.id for candidate in sandbox_plugins()] == [SANDBOX_PLUGIN_ID]

    actor_without_plugins = WorldActor()
    actor_without_plugins.plugins = None
    assert _enabled_regions(actor_without_plugins) == ()


@pytest.mark.asyncio
async def test_generator_builds_commons_without_simpack_regions() -> None:
    actor, result = await _generate(BASE_PLUGIN_IDS)

    assert set(result.rooms) == {
        "arrival",
        "commons",
        "after_dark_foyer",
        "after_dark_lounge",
    }
    assert not ({region.room.key for region in REGIONS} & set(result.rooms))
    assert actor.world_info.title == "Bunnyland Crossroads Sandbox"
    assert actor.world_info.content_flags == frozenset({AFTER_DARK_SCOPE})

    suspended = list(
        actor.world.query()
        .with_all([CharacterComponent, SuspendedComponent])
        .execute_entities()
    )
    assert sorted(entity.get_component(IdentityComponent).name for entity in suspended) == [
        "New Arrival 1",
        "New Arrival 2",
        "New Arrival 3",
        "New Arrival 4",
    ]


@pytest.mark.asyncio
async def test_generator_includes_only_loaded_simpack_regions() -> None:
    enabled = (*BASE_PLUGIN_IDS, TOONSIM)
    first_actor, first = await _generate(enabled)
    second_actor, second = await _generate(enabled)

    assert "toon_stage" in first.rooms
    assert set(first.rooms) == set(second.rooms)
    assert "garden_plot" not in first.rooms
    assert "bunnyland.gardensim" not in first_actor.world_info.description
    assert _semantic_summary(first_actor) == _semantic_summary(second_actor)

    toon_type = first_actor.plugins.components["ToonRoomComponent"][1]
    assert first_actor.world.get_entity(first.rooms["toon_stage"]).has_component(toon_type)
    generated_entities = (
        first_actor.world.query()
        .with_all([GenerationIntentComponent])
        .execute_entities()
    )
    for entity in generated_entities:
        generation = entity.get_component(GenerationIntentComponent)
        assert generation.unmet_capabilities == ()
        assert not any(want.startswith("bunnyland.gardensim.") for want in generation.wants)


@pytest.mark.asyncio
async def test_generator_enriches_every_loaded_bundled_simpack_region() -> None:
    actor, result = await _generate(None)
    expected_components = {
        "colony_yard": "StockpileComponent",
        "garden_plot": "SoilComponent",
        "life_sofa": "HomeObjectComponent",
        "barbarian_ring": "DangerZoneComponent",
        "dagger_crossing": "DungeonComponent",
        "dino_paddock": "EnclosureComponent",
        "dragon_barrows": "PointOfInterestComponent",
        "neon_terminal": "HackableComponent",
        "nuke_yard": "ScavengeSiteComponent",
        "toon_stage": "ToonRoomComponent",
        "void_deck": "ShipComponent",
    }

    assert {region.room.key for region in REGIONS}.issubset(result.rooms)
    for key, component_name in expected_components.items():
        entity_id = result.rooms.get(key) or result.objects[key]
        component_type = actor.plugins.components[component_name][1]
        assert actor.world.get_entity(entity_id).has_component(component_type), key

    for entity in actor.world.query().with_all([GenerationIntentComponent]).execute_entities():
        assert entity.get_component(GenerationIntentComponent).unmet_capabilities == ()
    for entity in actor.world.query().execute_entities():
        for _edge_name, (_owner, edge_type) in actor.plugins.edges.items():
            assert all(
                actor.world.has_entity(target_id)
                for _edge, target_id in entity.get_relationships(edge_type)
            )


async def _after_dark_world():
    actor, result = await _generate(BASE_PLUGIN_IDS)
    character_id = result.characters["new_arrival_1"]
    context = HandlerContext(actor.world, actor.epoch, actor)
    move = execute_handler(
        MoveHandler(),
        context,
        _command(character_id, "move", {"direction": "east"}),
    )
    assert move.ok is True
    assert container_of(actor.world.get_entity(character_id)) == result.rooms["commons"]
    return actor, result, character_id, context


@pytest.mark.asyncio
async def test_after_dark_accept_enter_withdraw_leave_and_reaccept() -> None:
    actor, result, character_id, context = await _after_dark_world()

    accepted = execute_handler(
        AcceptAfterDarkWarningHandler(),
        context,
        _command(character_id, "accept-after-dark-warning", {"acknowledged": True}),
    )
    assert accepted.ok is True
    boundary = actor.world.get_entity(character_id).get_component(CharacterBoundaryComponent)
    assert AFTER_DARK_SCOPE in boundary.allowed

    entered = execute_handler(
        EnterAfterDarkHandler(),
        context,
        _command(
            character_id,
            "enter-after-dark",
            {"entrance_id": str(result.objects["after_dark_entrance"])},
        ),
    )
    assert entered.ok is True
    assert container_of(actor.world.get_entity(character_id)) == result.rooms["after_dark_foyer"]

    withdrawn = execute_handler(
        WithdrawAfterDarkConsentHandler(),
        context,
        _command(character_id, "withdraw-after-dark-consent"),
    )
    assert withdrawn.ok is True
    boundary = actor.world.get_entity(character_id).get_component(CharacterBoundaryComponent)
    assert AFTER_DARK_SCOPE not in boundary.allowed
    assert AFTER_DARK_SCOPE in boundary.denied

    left = execute_handler(
        LeaveAfterDarkHandler(),
        context,
        _command(
            character_id,
            "leave-after-dark",
            {"exit_id": str(result.objects["after_dark_exit"])},
        ),
    )
    assert left.ok is True
    assert container_of(actor.world.get_entity(character_id)) == result.rooms["commons"]

    reaccepted = execute_handler(
        AcceptAfterDarkWarningHandler(),
        context,
        _command(character_id, "accept-after-dark-warning", {"acknowledged": True}),
    )
    assert reaccepted.ok is True
    boundary = actor.world.get_entity(character_id).get_component(CharacterBoundaryComponent)
    assert AFTER_DARK_SCOPE in boundary.allowed
    assert AFTER_DARK_SCOPE not in boundary.denied


@pytest.mark.asyncio
async def test_after_dark_acceptance_runs_through_normal_command_pipeline() -> None:
    actor, result = await _generate(BASE_PLUGIN_IDS)
    character_id = result.characters["new_arrival_1"]
    character = actor.world.get_entity(character_id)
    character.remove_component(SuspendedComponent)
    controller = spawn_entity(actor.world)
    generation = actor.assign_controller(character_id, controller.id)
    command = build_submitted_command(
        character_id=str(character_id),
        controller_id=str(controller.id),
        controller_generation=generation,
        command_type="accept-after-dark-warning",
        payload={"acknowledged": True},
    )

    assert (await actor.submit(command)).accepted is True
    await actor.tick(0)

    receipt = actor.receipt_for(str(character_id), command.command_id)
    assert receipt is not None
    assert receipt.status.value == "committed"
    boundary = character.get_component(CharacterBoundaryComponent)
    assert AFTER_DARK_SCOPE in boundary.allowed


@pytest.mark.asyncio
async def test_after_dark_rejections_are_specific() -> None:
    actor, result, character_id, context = await _after_dark_world()
    accept = AcceptAfterDarkWarningHandler()
    enter = EnterAfterDarkHandler()

    assert accept.execute(
        context,
        _command(character_id, "accept-after-dark-warning", {"acknowledged": False}),
    ).reason == "you must acknowledge the After Dark content warning"
    assert enter.execute(
        context,
        _command(
            character_id,
            "enter-after-dark",
            {"entrance_id": str(result.objects["after_dark_entrance"])},
        ),
    ).reason == "accept the After Dark warning before entering"

    execute_handler(
        accept,
        context,
        _command(character_id, "accept-after-dark-warning", {"acknowledged": True}),
    )
    assert accept.execute(
        context,
        _command(character_id, "accept-after-dark-warning", {"acknowledged": True}),
    ).reason == "the After Dark warning is already accepted"
    assert WithdrawAfterDarkConsentHandler().execute(
        context,
        _command(result.characters["new_arrival_2"], "withdraw-after-dark-consent"),
    ).reason == "After Dark consent is not active"
    cases = (
        ({"entrance_id": "not-an-id"}, "invalid entrance id"),
        ({"entrance_id": "blank_999999"}, "entrance id does not exist"),
        (
            {"entrance_id": str(result.objects["after_dark_exit"])},
            "entrance id is not reachable",
        ),
        (
            {"entrance_id": str(result.objects["commons_map"])},
            "entrance id is the wrong kind",
        ),
    )
    for payload, reason in cases:
        assert enter.execute(
            context,
            _command(character_id, "enter-after-dark", payload),
        ).reason == reason

    disconnected = spawn_entity(actor.world, [AfterDarkEntranceComponent()])
    actor.world.get_entity(result.rooms["commons"]).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), disconnected.id
    )
    assert enter.execute(
        context,
        _command(
            character_id,
            "enter-after-dark",
            {"entrance_id": str(disconnected.id)},
        ),
    ).reason == "After Dark passage is not connected"

    ambiguous = spawn_entity(actor.world, [AfterDarkEntranceComponent()])
    commons = actor.world.get_entity(result.rooms["commons"])
    commons.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), ambiguous.id)
    ambiguous.add_relationship(AfterDarkPassage(), result.rooms["after_dark_foyer"])
    ambiguous.add_relationship(AfterDarkPassage(), result.rooms["after_dark_lounge"])
    assert enter.execute(
        context,
        _command(character_id, "enter-after-dark", {"entrance_id": str(ambiguous.id)}),
    ).reason == "After Dark passage is ambiguous"

    wrong_destination = spawn_entity(actor.world, [AfterDarkEntranceComponent()])
    commons.add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_destination.id
    )
    wrong_destination.add_relationship(
        AfterDarkPassage(), result.objects["commons_map"]
    )
    assert enter.execute(
        context,
        _command(
            character_id,
            "enter-after-dark",
            {"entrance_id": str(wrong_destination.id)},
        ),
    ).reason == "After Dark destination is not a room"


def test_after_dark_handlers_reject_missing_characters_and_uncontained_travelers() -> None:
    actor = WorldActor()
    context = HandlerContext(actor.world, actor.epoch, actor)
    missing = _command("blank_999999", "accept-after-dark-warning", {"acknowledged": True})

    assert AcceptAfterDarkWarningHandler().execute(context, missing).reason == (
        "character does not exist"
    )
    assert WithdrawAfterDarkConsentHandler().execute(context, missing).reason == (
        "character does not exist"
    )
    assert EnterAfterDarkHandler().execute(context, missing).reason == "character does not exist"
    assert LeaveAfterDarkHandler().execute(context, missing).reason == "character does not exist"

    traveler = spawn_entity(actor.world, [CharacterComponent()])
    marker = spawn_entity(actor.world, [AfterDarkExitComponent()])
    destination = spawn_entity(actor.world, [RoomComponent(title="Destination")])
    traveler.add_relationship(Contains(mode=ContainmentMode.INVENTORY), marker.id)
    marker.add_relationship(AfterDarkPassage(), destination.id)

    result = LeaveAfterDarkHandler().execute(
        context,
        _command(traveler.id, "leave-after-dark", {"exit_id": str(marker.id)}),
    )
    assert result.reason == "character is not in a room"


@pytest.mark.asyncio
async def test_after_dark_parent_denial_and_world_disablement_win() -> None:
    actor, result, character_id, context = await _after_dark_world()
    character = actor.world.get_entity(character_id)
    character.add_component(CharacterBoundaryComponent(denied=frozenset({BoundaryTag.ADULT})))
    denied = AcceptAfterDarkWarningHandler().execute(
        context,
        _command(character_id, "accept-after-dark-warning", {"acknowledged": True}),
    )
    assert denied.reason == "adult access is denied for this character"

    replace_component(
        character,
        CharacterBoundaryComponent(allowed=frozenset({AFTER_DARK_SCOPE})),
    )
    policy_entity = next(
        actor.world.query().with_all([WorldPolicyComponent]).execute_entities()
    )
    policy = policy_entity.get_component(WorldPolicyComponent)
    replace_component(
        policy_entity,
        replace(policy, disabled=policy.disabled | {AFTER_DARK_SCOPE}),
    )
    blocked = EnterAfterDarkHandler().execute(
        context,
        _command(
            character_id,
            "enter-after-dark",
            {"entrance_id": str(result.objects["after_dark_entrance"])},
        ),
    )
    assert blocked.reason == "adult:after_dark is disabled in this world"


def test_sandbox_generator_function_is_the_registered_contract() -> None:
    definition = sandbox_plugin()

    assert definition.content.world_generators[0].generate is sandbox_generator
    assert definition.content.world_generators[0].uses_seed is True
