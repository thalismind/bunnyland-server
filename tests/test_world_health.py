"""Tests for the opt-in live world-health metric collector."""

from __future__ import annotations

from dataclasses import replace

from conftest import build_scenario
from relics import EntityId

from bunnyland import telemetry
from bunnyland.core import (
    CharacterComponent,
    ClaimedComponent,
    CommandCost,
    Contains,
    ControlledBy,
    ConversationComponent,
    LLMControllerComponent,
    OnInsufficientPoints,
    SuspendedControllerComponent,
    TransientControllerComponent,
    WorldActor,
    WorldClockComponent,
    build_submitted_command,
    replace_component,
    spawn_entity,
)
from bunnyland.plugins import PluginPlacement, apply_plugin
from bunnyland.plugins.ids import WORLD_HEALTH
from bunnyland.world_health.metrics import HEALTH_CHECKS, collect_world_health_issues
from bunnyland.world_health.plugin import bunnyland_plugins, plugin


def _counts(actor: WorldActor) -> dict[tuple[str, str], int]:
    return dict(collect_world_health_issues(actor))


def _command(
    actor: WorldActor,
    character_id: str,
    controller_id: str,
    *,
    command_id: str,
    submitted_at_epoch: int = 0,
    expires_at_epoch: int | None = None,
):
    return build_submitted_command(
        character_id=character_id,
        controller_id=controller_id,
        controller_generation=0,
        command_type="wait",
        payload={},
        cost=CommandCost(),
        on_insufficient_points=OnInsufficientPoints.QUEUE,
        submitted_at_epoch=submitted_at_epoch,
        expires_at_epoch=expires_at_epoch,
        command_id=command_id,
    )


def test_plugin_is_default_disabled_addon_and_registers_only_when_applied(monkeypatch):
    definition = plugin()
    assert bunnyland_plugins() == [definition]
    assert definition.id == WORLD_HEALTH
    assert definition.placement is PluginPlacement.ADDON
    assert definition.default_enabled is False
    assert definition.ecs.systems == ()
    assert definition.ecs.observers == ()

    actor = WorldActor()
    registrations = []
    monkeypatch.setattr(
        telemetry,
        "register_world_health_gauge",
        lambda registered_actor, collector: registrations.append(
            (registered_actor, collector)
        ),
    )
    assert registrations == []
    apply_plugin(definition, actor)
    assert registrations == [(actor, collect_world_health_issues)]


def test_healthy_world_emits_every_bounded_zero_series_and_allows_shared_controller():
    scenario = build_scenario()
    second_character = spawn_entity(scenario.actor.world, [CharacterComponent()])
    scenario.actor.assign_controller(second_character.id, scenario.controller)

    counts = _counts(scenario.actor)

    assert set(counts) == set(HEALTH_CHECKS)
    assert all(count == 0 for count in counts.values())


def test_relationship_checks_find_dangling_edges_and_index_disagreement():
    scenario = build_scenario()
    world = scenario.actor.world
    missing = EntityId(prefab="missing", sequence=1)
    edge = Contains()
    world._relationships.setdefault(scenario.room_a, {}).setdefault(Contains, {})[
        missing
    ] = edge
    world._incoming_relationships.setdefault(missing, {}).setdefault(Contains, {})[
        scenario.room_a
    ] = edge
    world._incoming_relationships.setdefault(scenario.room_a, {}).setdefault(Contains, {})[
        scenario.room_a
    ] = edge

    counts = _counts(scenario.actor)

    assert counts[("dangling_relationship", "error")] == 1
    assert counts[("relationship_index_mismatch", "error")] >= 1


def test_controller_checks_report_each_invalid_cardinality_and_lifecycle_state():
    scenario = build_scenario()
    world = scenario.actor.world

    no_controller_character = spawn_entity(world, [CharacterComponent()])
    second_controller = spawn_entity(
        world, [SuspendedControllerComponent(), TransientControllerComponent()]
    )
    world.get_entity(scenario.character).add_relationship(ControlledBy(), second_controller.id)
    world.get_entity(scenario.room_a).add_relationship(ControlledBy(), scenario.controller)

    invalid_target = spawn_entity(world)
    invalid_target_character = spawn_entity(world, [CharacterComponent()])
    invalid_target_character.add_relationship(ControlledBy(), invalid_target.id)

    spawn_entity(
        world,
        [
            LLMControllerComponent(profile_name="multi", model="test"),
            SuspendedControllerComponent(),
        ],
    )
    spawn_entity(world, [TransientControllerComponent()])
    spawn_entity(
        world,
        [
            LLMControllerComponent(profile_name="detached", model="test"),
            TransientControllerComponent(),
        ],
    )
    spawn_entity(world, [LLMControllerComponent(profile_name="durable", model="test")])
    spawn_entity(
        world,
        [
            LLMControllerComponent(profile_name="claimed-detached", model="test"),
            ClaimedComponent(
                claim_id="detached",
                client_kind="web",
                client_id="client",
                character_id=str(no_controller_character.id),
            ),
        ],
    )
    claimed_controller = spawn_entity(
        world,
        [
            LLMControllerComponent(profile_name="claimed", model="test"),
            ClaimedComponent(
                claim_id="mismatch",
                client_kind="web",
                client_id="client",
                character_id=str(no_controller_character.id),
            ),
        ],
    )
    claimed_character = spawn_entity(world, [CharacterComponent()])
    scenario.actor.assign_controller(claimed_character.id, claimed_controller.id)

    counts = _counts(scenario.actor)

    expected_positive = {
        "controller_source_not_character",
        "character_without_controller",
        "character_has_multiple_controllers",
        "invalid_controller_target",
        "multiple_controller_components",
        "transient_marker_without_controller",
        "detached_transient_controller",
        "detached_controller",
        "invalid_claim_controller_cardinality",
        "claim_character_mismatch",
    }
    assert expected_positive <= {
        check for (check, _severity), count in counts.items() if count > 0
    }


def test_queue_checks_use_character_scoped_ids_and_validate_targets_and_epochs():
    scenario = build_scenario()
    actor = scenario.actor
    clock = next(
        actor.world.query().with_all([WorldClockComponent]).execute_entities()
    )
    replace_component(
        clock,
        replace(clock.get_component(WorldClockComponent), game_time_seconds=10),
    )
    duplicate = _command(
        actor,
        str(scenario.character),
        str(scenario.controller),
        command_id="duplicate",
    )
    actor.submit_nowait(duplicate)
    actor.queues.enqueue(duplicate)

    other_character = spawn_entity(actor.world, [CharacterComponent()])
    actor.assign_controller(other_character.id, scenario.controller)
    actor.submit_nowait(
        _command(
            actor,
            str(other_character.id),
            str(scenario.controller),
            command_id="duplicate",
        )
    )
    actor.submit_nowait(
        _command(
            actor,
            "invalid",
            str(scenario.controller),
            command_id="invalid-target",
            submitted_at_epoch=11,
        )
    )
    actor.submit_nowait(
        _command(
            actor,
            "missing_123",
            str(scenario.controller),
            command_id="missing-target",
        )
    )
    actor.submit_nowait(
        _command(
            actor,
            str(scenario.room_a),
            str(scenario.controller),
            command_id="room-target",
            expires_at_epoch=9,
        )
    )

    counts = _counts(actor)

    assert counts[("duplicate_command_id", "error")] == 1
    assert counts[("queued_command_missing_character", "error")] == 2
    assert counts[("queued_command_target_not_character", "error")] == 1
    assert counts[("queued_command_from_future", "error")] == 1
    assert counts[("expired_queued_command", "warning")] == 1


def test_claim_matching_one_character_is_valid():
    scenario = build_scenario()
    controller = scenario.actor.world.get_entity(scenario.controller)
    controller.add_component(
        ClaimedComponent(
            claim_id="valid",
            client_kind="web",
            client_id="client",
            character_id=str(scenario.character),
        )
    )

    counts = _counts(scenario.actor)

    assert counts[("invalid_claim_controller_cardinality", "error")] == 0
    assert counts[("claim_character_mismatch", "error")] == 0


def test_conversation_check_reports_only_positive_expired_epochs():
    scenario = build_scenario()
    spawn_entity(scenario.actor.world, [ConversationComponent(expires_at_epoch=0)])
    spawn_entity(scenario.actor.world, [ConversationComponent(expires_at_epoch=9)])
    clock = next(
        scenario.actor.world.query().with_all([WorldClockComponent]).execute_entities()
    )
    replace_component(
        clock,
        replace(clock.get_component(WorldClockComponent), game_time_seconds=10),
    )

    counts = _counts(scenario.actor)

    assert counts[("expired_conversation", "warning")] == 1
