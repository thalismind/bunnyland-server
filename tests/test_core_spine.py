"""End-to-end tests for the core command/tick spine."""

from __future__ import annotations

import random

import pytest
from conftest import build_scenario

from bunnyland.core import (
    ActionPointsComponent,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    ControlledBy,
    FocusPointsComponent,
    IdentityComponent,
    InitiativeComponent,
    Lane,
    OnInsufficientPoints,
    SuspendedComponent,
    WorldClockComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.claim_timeout import (
    CLAIM_FALLBACK_LLM,
    CLAIM_FALLBACK_SUSPEND,
    CLAIM_TIMEOUT_MAX_SECONDS,
    CLAIM_TIMEOUT_MIN_SECONDS,
    apply_claim_timeout_settings,
    normalize_claim_fallback,
    normalize_claim_timeout,
    record_claim_activity,
)
from bunnyland.core.controllers import (
    LLMControllerComponent,
    SuspendedControllerComponent,
    WebControllerComponent,
)
from bunnyland.core.events import CommandExecutedEvent, CommandRejectedEvent, ControllerChangedEvent
from bunnyland.core.systems import ClaimTimeoutSystem

HOUR = 3600.0


def move_command(scenario, *, generation=None, on_insufficient=OnInsufficientPoints.QUEUE):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation if generation is None else generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
        on_insufficient_points=on_insufficient,
    )


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


# -- regeneration -----------------------------------------------------------------------


async def test_action_focus_regenerate_over_time():
    scenario = build_scenario(action_current=0.0, focus_current=0.0)
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.tick(HOUR)  # +1 action, +0.5 focus
    assert char.get_component(ActionPointsComponent).current == pytest.approx(1.0)
    assert char.get_component(FocusPointsComponent).current == pytest.approx(0.5)


async def test_regen_caps_at_maximum():
    scenario = build_scenario(action_current=4.5, focus_current=2.9)
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.tick(10 * HOUR)
    assert char.get_component(ActionPointsComponent).current == pytest.approx(5.0)
    assert char.get_component(FocusPointsComponent).current == pytest.approx(3.0)


async def test_world_clock_advances():
    scenario = build_scenario()
    await scenario.actor.tick(HOUR)
    clock = scenario.actor._clock_entity.get_component(WorldClockComponent)
    assert clock.game_time_seconds == int(HOUR)
    assert clock.tick_index == 1
    assert scenario.actor.epoch == int(HOUR)


async def test_claim_timeout_suspends_inactive_web_controller():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)
    apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller="suspend",
        timeout_seconds=300,
        reset_activity=True,
    )
    changed = collect(scenario.actor, ControllerChangedEvent)
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(default_timeout_seconds=1800, now=lambda: 301)
    )

    await scenario.actor.tick(0)

    _edge, controller_id = character.get_relationships(ControlledBy)[0]
    controller = scenario.actor.world.get_entity(controller_id)
    assert character.has_component(SuspendedComponent)
    assert controller.has_component(SuspendedControllerComponent)
    assert changed[-1].controller_kind == "suspended"


async def test_claim_timeout_can_fall_back_to_llm():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)
    apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller="llm",
        llm_model="claim-model",
        llm_provider="openrouter",
        timeout_seconds=300,
        reset_activity=True,
    )
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(default_timeout_seconds=1800, now=lambda: 301)
    )

    await scenario.actor.tick(0)

    _edge, controller_id = character.get_relationships(ControlledBy)[0]
    controller = scenario.actor.world.get_entity(controller_id)
    llm = controller.get_component(LLMControllerComponent)
    assert not character.has_component(SuspendedComponent)
    assert llm.model == "claim-model"
    assert llm.provider == "openrouter"


async def test_claim_timeout_uses_player_timeout_before_server_default():
    scenario = build_scenario()
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    scenario.actor.assign_controller(scenario.character, web.id)
    apply_claim_timeout_settings(
        web,
        now_unix=0,
        fallback_controller="suspend",
        timeout_seconds=300,
        reset_activity=True,
    )
    scenario.actor.register_after_tick(
        ClaimTimeoutSystem(default_timeout_seconds=3600, now=lambda: 301)
    )

    await scenario.actor.tick(0)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_component(SuspendedComponent)


def test_claim_timeout_normalizers_accept_aliases_and_reject_bad_values():
    assert normalize_claim_fallback(None) == CLAIM_FALLBACK_SUSPEND
    assert normalize_claim_fallback(" suspended ") == CLAIM_FALLBACK_SUSPEND
    assert normalize_claim_fallback("offline") == CLAIM_FALLBACK_SUSPEND
    assert normalize_claim_fallback("AI") == CLAIM_FALLBACK_LLM
    assert normalize_claim_fallback("agent") == CLAIM_FALLBACK_LLM
    assert normalize_claim_timeout(CLAIM_TIMEOUT_MIN_SECONDS) == CLAIM_TIMEOUT_MIN_SECONDS
    assert normalize_claim_timeout(CLAIM_TIMEOUT_MAX_SECONDS) == CLAIM_TIMEOUT_MAX_SECONDS

    with pytest.raises(ValueError, match="fallback_controller must be one of: llm, suspend"):
        normalize_claim_fallback("manual")

    with pytest.raises(
        ValueError,
        match=(
            "timeout_seconds must be between "
            f"{CLAIM_TIMEOUT_MIN_SECONDS} and {CLAIM_TIMEOUT_MAX_SECONDS}"
        ),
    ):
        normalize_claim_timeout(CLAIM_TIMEOUT_MIN_SECONDS - 1)


def test_claim_timeout_settings_preserve_existing_values_and_record_activity():
    scenario = build_scenario()
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    first = apply_claim_timeout_settings(
        web,
        now_unix=100,
        fallback_controller="ai",
        fallback_reason=" idle ",
        llm_profile_name=" guide ",
        llm_model=" model ",
        llm_provider=" provider ",
        timeout_seconds=CLAIM_TIMEOUT_MIN_SECONDS,
        reset_activity=True,
    )

    second = apply_claim_timeout_settings(
        web,
        now_unix=200,
        fallback_controller=None,
        fallback_reason=" ",
        llm_profile_name=" ",
        llm_model=" ",
        llm_provider=" ",
        timeout_seconds=None,
        reset_activity=False,
    )
    untracked = spawn_entity(scenario.actor.world)
    record_claim_activity(untracked, now_unix=500)
    record_claim_activity(web, now_unix=300)
    updated = web.get_component(type(first))

    assert first.fallback_controller == CLAIM_FALLBACK_LLM
    assert second.fallback_reason == "idle"
    assert second.llm_profile_name == "guide"
    assert second.llm_model == "model"
    assert second.llm_provider == "provider"
    assert second.timeout_seconds == CLAIM_TIMEOUT_MIN_SECONDS
    assert second.claimed_at_unix == 100
    assert updated.last_command_unix == 300


# -- movement ---------------------------------------------------------------------------


async def test_move_transfers_containment_and_spends_action():
    scenario = build_scenario()
    char = scenario.actor.world.get_entity(scenario.character)
    assert scenario.character_room() == scenario.room_a

    await scenario.actor.submit(move_command(scenario))
    await scenario.actor.tick(HOUR)

    assert scenario.character_room() == scenario.room_b
    # started at 5.0, regen capped at 5.0, spent 1 -> 4.0
    assert char.get_component(ActionPointsComponent).current == pytest.approx(4.0)


async def test_move_with_no_matching_exit_is_rejected():
    scenario = build_scenario()
    rejects = collect(scenario.actor, CommandRejectedEvent)

    cmd = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "west"},  # no such exit
    )
    await scenario.actor.submit(cmd)
    await scenario.actor.tick(HOUR)

    assert scenario.character_room() == scenario.room_a
    assert any(r.reason == "no matching exit" for r in rejects)
    # points are not spent on a rejected command
    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(ActionPointsComponent).current == pytest.approx(5.0)


# -- controller generation --------------------------------------------------------------


async def test_stale_controller_generation_rejected():
    scenario = build_scenario()
    rejects = collect(scenario.actor, CommandRejectedEvent)

    stale = move_command(scenario, generation=scenario.generation)  # gen 0
    # A new controller takes over, bumping generation to 1 and flushing queues.
    new_controller = spawn_entity(scenario.actor.world)
    scenario.actor.assign_controller(scenario.character, new_controller.id)

    await scenario.actor.submit(stale)
    await scenario.actor.tick(HOUR)

    assert scenario.character_room() == scenario.room_a
    assert any(r.reason == "stale controller generation" for r in rejects)


# -- insufficient points: deny vs queue -------------------------------------------------


async def test_insufficient_points_deny_is_rejected_immediately():
    scenario = build_scenario(action_current=0.0)
    rejects = collect(scenario.actor, CommandRejectedEvent)

    await scenario.actor.submit(
        move_command(scenario, on_insufficient=OnInsufficientPoints.DENY)
    )
    await scenario.actor.tick(0.0)  # no regen

    assert scenario.character_room() == scenario.room_a
    assert any(r.reason == "insufficient points" for r in rejects)


async def test_insufficient_points_queue_waits_then_executes():
    scenario = build_scenario(action_current=0.0)
    executed = collect(scenario.actor, CommandExecutedEvent)

    await scenario.actor.submit(
        move_command(scenario, on_insufficient=OnInsufficientPoints.QUEUE)
    )
    # First tick: tiny regen, still cannot afford 1 action -> stays queued.
    await scenario.actor.tick(0.1)
    assert scenario.character_room() == scenario.room_a
    assert executed == []

    # Enough time passes to regen >= 1 action -> command runs.
    await scenario.actor.tick(HOUR)
    assert scenario.character_room() == scenario.room_b
    assert len(executed) == 1


# -- suspended characters ---------------------------------------------------------------


async def test_suspended_character_regenerates_but_cannot_act():
    scenario = build_scenario(action_current=2.0)
    no_op_controller = spawn_entity(scenario.actor.world)
    scenario.actor.suspend(scenario.character, no_op_controller.id, reason="offline")

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.has_component(SuspendedComponent)
    assert no_op_controller.has_component(SuspendedControllerComponent)

    rejects = collect(scenario.actor, CommandRejectedEvent)
    # Command built under the suspended controller's generation.
    generation = scenario.actor.current_generation(scenario.character, no_op_controller.id)
    cmd = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(no_op_controller.id),
        controller_generation=generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
    )
    await scenario.actor.submit(cmd)
    await scenario.actor.tick(HOUR)

    # Still regenerated (capped at 5), but did not move or spend.
    assert scenario.character_room() == scenario.room_a
    assert char.get_component(ActionPointsComponent).current == pytest.approx(3.0)
    assert any(r.reason == "character is suspended" for r in rejects)


# -- initiative -------------------------------------------------------------------------


async def test_initiative_orders_execution_high_score_first():
    # Two independent characters; the higher-initiative one should execute first.
    scenario = build_scenario(initiative=1.0)
    actor = scenario.actor

    # Second character in room_a with higher initiative and its own controller.
    other = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(species="bunny"),
            ActionPointsComponent(current=5.0, maximum=5.0, regen_per_hour=1.0),
            InitiativeComponent(score=9.0),
        ],
    )
    actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), other.id
    )
    other_controller = spawn_entity(actor.world)
    other_gen = actor.assign_controller(other.id, other_controller.id)

    order = []
    actor.bus.subscribe(CommandExecutedEvent, lambda e: order.append(e.actor_id))

    await actor.submit(move_command(scenario))  # initiative 1.0
    await actor.submit(
        build_submitted_command(
            character_id=str(other.id),
            controller_id=str(other_controller.id),
            controller_generation=other_gen,
            command_type="move",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload={"direction": "north"},
        )
    )
    await actor.tick(HOUR)

    assert order == [str(other.id), str(scenario.character)]


def test_initiative_tiebreak_is_randomized():
    # Pure unit check of the ordering helper with tied scores and seeded RNG.
    scenario = build_scenario()
    actor = scenario.actor
    actor._rng = random.Random(0)
    ids = ["entity_1", "entity_2", "entity_3"]
    # No entities exist for these ids -> all score 0.0, so order is purely random jitter.
    ordering = actor._initiative_order(ids)
    assert sorted(ordering) == sorted(ids)
