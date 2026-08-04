"""Tests for sleep / wake / wait and the asleep/downed action gates."""

from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import build_scenario, execute_handler

from bunnyland.core import (
    AffectComponent,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    DeadComponent,
    DownedComponent,
    HasThought,
    HealthComponent,
    IdentityComponent,
    Lane,
    MutationPlan,
    RestHandler,
    RestingComponent,
    SayHandler,
    SleepHandler,
    SleepingComponent,
    SuspendedComponent,
    ThoughtComponent,
    WaitHandler,
    WakeHandler,
    build_submitted_command,
    execute_mutation_plan,
    replace_component,
    spawn_entity,
)
from bunnyland.core.events import (
    CharacterAttackedEvent,
    CharacterWokeEvent,
    CommandExecutedEvent,
    CommandRejectedEvent,
    RecoveryEndReason,
    RestEndedEvent,
    RestStartedEvent,
    SleepStartedEvent,
    SpeechSaidEvent,
    event_base,
)
from bunnyland.core.handlers.base import HandlerContext
from bunnyland.core.recovery import install_recovery, recovery_fragments
from bunnyland.server.serialization import _sheet_status

HOUR = 3600.0


def lifecycle_scenario():
    scenario = build_scenario()
    for handler in (RestHandler(), SleepHandler(), WakeHandler(), WaitHandler(), SayHandler()):
        scenario.actor.register_handler(handler)
    install_recovery(scenario.actor)
    return scenario


def cmd(scenario, command_type, *, cost=None, lane=Lane.WORLD, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=cost if cost is not None else CommandCost(action=1),
        lane=lane,
        payload=payload,
    )


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


def handler_context(scenario):
    return HandlerContext(scenario.actor.world, scenario.actor.epoch)


async def test_sleep_then_wake():
    scenario = lifecycle_scenario()
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.submit(cmd(scenario, "sleep"))
    await scenario.actor.tick(HOUR)
    assert char.has_component(SleepingComponent)

    await scenario.actor.submit(cmd(scenario, "wake", cost=CommandCost()))
    await scenario.actor.tick(HOUR)
    assert not char.has_component(SleepingComponent)


async def test_rest_starts_and_successful_wait_interrupts_it():
    scenario = lifecycle_scenario()
    started = collect(scenario.actor, RestStartedEvent)
    ended = collect(scenario.actor, RestEndedEvent)
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.submit(cmd(scenario, "rest", cost=CommandCost()))
    await scenario.actor.tick(0)

    rest = char.get_component(RestingComponent)
    assert rest.session_id == started[0].session_id
    assert rest.until_epoch is None

    await scenario.actor.submit(cmd(scenario, "wait", cost=CommandCost()))
    await scenario.actor.tick(0)

    assert not char.has_component(RestingComponent)
    assert [event.reason for event in ended] == ["action"]


async def test_rejected_command_does_not_interrupt_rest():
    scenario = lifecycle_scenario()
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.submit(cmd(scenario, "rest", cost=CommandCost()))
    await scenario.actor.tick(0)
    await scenario.actor.submit(cmd(scenario, "wake", cost=CommandCost()))
    await scenario.actor.tick(0)

    assert char.has_component(RestingComponent)


async def test_timed_rest_completes_and_timed_sleep_wakes():
    rest_scenario = lifecycle_scenario()
    rest_char = rest_scenario.actor.world.get_entity(rest_scenario.character)
    rest_ended = collect(rest_scenario.actor, RestEndedEvent)
    await rest_scenario.actor.submit(
        cmd(rest_scenario, "rest", cost=CommandCost(), duration_seconds=HOUR)
    )
    await rest_scenario.actor.tick(0)
    assert rest_char.get_component(RestingComponent).until_epoch == HOUR
    await rest_scenario.actor.tick(HOUR)
    assert not rest_char.has_component(RestingComponent)
    assert [event.reason for event in rest_ended] == ["duration"]

    sleep_scenario = lifecycle_scenario()
    sleep_char = sleep_scenario.actor.world.get_entity(sleep_scenario.character)
    woke = collect(sleep_scenario.actor, CharacterWokeEvent)
    await sleep_scenario.actor.submit(
        cmd(sleep_scenario, "sleep", cost=CommandCost(), duration_seconds=HOUR)
    )
    await sleep_scenario.actor.tick(0)
    assert sleep_char.get_component(SleepingComponent).until_epoch == HOUR
    await sleep_scenario.actor.tick(HOUR)
    assert not sleep_char.has_component(SleepingComponent)
    assert [event.reason for event in woke] == ["duration"]


async def test_sleep_replaces_rest_and_wake_is_explicit():
    scenario = lifecycle_scenario()
    char = scenario.actor.world.get_entity(scenario.character)
    rest_ended = collect(scenario.actor, RestEndedEvent)
    sleep_started = collect(scenario.actor, SleepStartedEvent)
    woke = collect(scenario.actor, CharacterWokeEvent)

    await scenario.actor.submit(cmd(scenario, "rest", cost=CommandCost()))
    await scenario.actor.tick(0)
    await scenario.actor.submit(cmd(scenario, "sleep", cost=CommandCost()))
    await scenario.actor.tick(0)

    assert not char.has_component(RestingComponent)
    assert char.has_component(SleepingComponent)
    assert [event.reason for event in rest_ended] == ["action"]
    assert len(sleep_started) == 1

    await scenario.actor.submit(cmd(scenario, "wake", cost=CommandCost()))
    await scenario.actor.tick(0)
    assert [event.reason for event in woke] == ["explicit"]


@pytest.mark.parametrize(
    "duration",
    [0, -1, float("inf"), float("-inf"), float("nan"), True, "forever"],
)
@pytest.mark.parametrize(
    "handler,command_type",
    [(RestHandler(), "rest"), (SleepHandler(), "sleep")],
)
def test_recovery_handlers_reject_invalid_durations(handler, command_type, duration):
    scenario = lifecycle_scenario()
    result = execute_handler(
        handler,
        handler_context(scenario),
        cmd(
            scenario,
            command_type,
            cost=CommandCost(),
            duration_seconds=duration,
        ),
    )

    assert result.reason == "duration must be a positive finite number"


def test_rest_rejects_sleeping_character_with_existing_gate_reason():
    scenario = lifecycle_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(SleepingComponent())

    result = execute_handler(
        RestHandler(), handler_context(scenario), cmd(scenario, "rest", cost=CommandCost())
    )

    assert result.reason == "character is asleep"


@pytest.mark.parametrize(
    "blocking_component",
    [
        DownedComponent(downed_at_epoch=0, cause="test"),
        DeadComponent(died_at_epoch=0, cause="test"),
        SuspendedComponent(reason="test"),
    ],
)
async def test_downed_dead_or_suspended_character_ends_rest(blocking_component):
    scenario = lifecycle_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    ended = collect(scenario.actor, RestEndedEvent)
    await scenario.actor.submit(cmd(scenario, "rest", cost=CommandCost()))
    await scenario.actor.tick(0)

    character.add_component(blocking_component)
    await scenario.actor.tick(0)

    assert not character.has_component(RestingComponent)
    assert [event.reason for event in ended] == ["danger"]


async def test_damage_ends_rest_and_wakes_sleeping_characters():
    for command_type, component_type, event_type in (
        ("rest", RestingComponent, RestEndedEvent),
        ("sleep", SleepingComponent, CharacterWokeEvent),
    ):
        scenario = lifecycle_scenario()
        character = scenario.actor.world.get_entity(scenario.character)
        character.add_component(HealthComponent())
        ended = collect(scenario.actor, event_type)
        await scenario.actor.submit(cmd(scenario, command_type, cost=CommandCost()))
        await scenario.actor.tick(0)

        health = character.get_component(HealthComponent)
        replace_component(character, replace(health, current=health.current - 1))
        await scenario.actor.tick(0)

        assert not character.has_component(component_type)
        assert [event.reason for event in ended] == ["danger"]


async def test_recovery_keeps_one_bounded_rested_thought_per_session():
    scenario = lifecycle_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(AffectComponent())
    await scenario.actor.submit(cmd(scenario, "rest", cost=CommandCost()))
    await scenario.actor.tick(0)
    await scenario.actor.tick(HOUR)

    relationships = character.get_relationships(HasThought)
    assert len(relationships) == 1
    _edge, thought_id = relationships[0]
    thought = scenario.actor.world.get_entity(thought_id).get_component(ThoughtComponent)
    assert thought.label == "rested"
    assert thought.affect_delta.stress == pytest.approx(-4)
    assert thought.expires_at_epoch is None

    await scenario.actor.tick(HOUR)
    assert character.get_relationships(HasThought)[0][1] == thought_id
    thought = scenario.actor.world.get_entity(thought_id).get_component(ThoughtComponent)
    assert thought.affect_delta.stress == pytest.approx(-8)

    await scenario.actor.submit(cmd(scenario, "wait", cost=CommandCost()))
    await scenario.actor.tick(0)
    thought = scenario.actor.world.get_entity(thought_id).get_component(ThoughtComponent)
    assert thought.expires_at_epoch == scenario.actor.epoch + 2 * HOUR


def test_recovery_prompt_fragments_are_concise_and_timed():
    scenario = lifecycle_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        RestingComponent(started_at_epoch=0, until_epoch=HOUR, session_id="rest-1")
    )
    assert recovery_fragments(scenario.actor.world, character) == (
        "I am resting until epoch 3600.",
    )
    replace_component(character, RestingComponent(session_id="rest-1"))
    assert recovery_fragments(scenario.actor.world, character) == ("I am resting.",)
    character.remove_component(RestingComponent)
    character.add_component(SleepingComponent(until_epoch=HOUR))
    assert recovery_fragments(scenario.actor.world, character) == (
        "I am asleep until epoch 3600.",
    )
    replace_component(character, SleepingComponent())
    assert recovery_fragments(scenario.actor.world, character) == ()
    character.remove_component(SleepingComponent)
    assert recovery_fragments(scenario.actor.world, character) == ()


def test_recovery_thought_helpers_ignore_unrelated_relationships_and_avoid_rewrites():
    import bunnyland.core.recovery as recovery

    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    character.add_component(AffectComponent())
    unrelated = spawn_entity(world, [IdentityComponent(name="memory", kind="note")])
    mismatch = spawn_entity(
        world,
        [
            ThoughtComponent(
                label="other",
                text="Other thought.",
                affect_delta=recovery.AffectDelta(),
                created_at_epoch=0,
                source_event_id="other-session",
            )
        ],
    )
    character.add_relationship(HasThought(), unrelated.id)
    character.add_relationship(HasThought(), mismatch.id)
    assert recovery._rested_thought(character, world, "session") is None

    rest = RestingComponent(started_at_epoch=0, session_id="session")
    character.add_component(rest)
    execute_mutation_plan(
        world,
        MutationPlan(recovery.end_rest_operations(world, character, rest, epoch=int(HOUR))),
    )
    thought_entity, thought = recovery._rested_thought(character, world, "session")
    recovery._update_active_thought(
        world,
        character,
        "session",
        started_at_epoch=0,
        end_epoch=HOUR,
        rate=recovery.REST_STRESS_RELIEF_PER_HOUR,
        cap=recovery.REST_STRESS_RELIEF_CAP,
        expires_at_epoch=int(3 * HOUR),
    )
    assert thought_entity.get_component(ThoughtComponent) == thought


def test_recovery_interruption_observers_ignore_zero_damage_and_actorless_end_events():
    import bunnyland.core.recovery as recovery

    interruptions = recovery.RecoveryInterruptions()
    interruptions._on_attack(
        CharacterAttackedEvent(
            **event_base(
                0,
                actor_id="entity_1",
                target_ids=("entity_2",),
                target_id="entity_2",
                damage=0,
            )
        )
    )
    interruptions._on_attack(
        CharacterAttackedEvent(
            **event_base(
                0,
                actor_id="entity_1",
                target_ids=("entity_2",),
                target_id="entity_2",
                damage=1,
            )
        )
    )
    assert interruptions.attacked_ids == {"entity_2"}
    interruptions.attacked_ids.clear()
    interruptions._on_recovery_ended(
        RestEndedEvent(
            **event_base(
                0,
                session_id="session",
                reason=RecoveryEndReason.DURATION,
            )
        )
    )
    assert interruptions.attacked_ids == set()


def test_character_sheet_surfaces_resting_status():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(RestingComponent(session_id="rest"))

    assert "resting" in _sheet_status(character)


def test_recovery_processing_scales_with_indexed_state_candidates(monkeypatch):
    import bunnyland.core.recovery as recovery

    scenario = build_scenario()
    world = scenario.actor.world
    resting_ids = {str(scenario.character)}
    world.get_entity(scenario.character).add_component(
        RestingComponent(session_id="rest-primary")
    )
    second_rest = spawn_entity(world, [RestingComponent(session_id="rest-second")])
    resting_ids.add(str(second_rest.id))
    sleep_one = spawn_entity(world, [SleepingComponent(started_at_epoch=1)])
    sleep_two = spawn_entity(world, [SleepingComponent(started_at_epoch=2)])
    sleeping_ids = {str(sleep_one.id), str(sleep_two.id)}
    for index in range(200):
        spawn_entity(world, [IdentityComponent(name=f"unrelated {index}", kind="item")])

    processed: list[str] = []
    original = recovery._update_active_thought

    def counted(world, character, session_id, **kwargs):
        processed.append(str(character.id))
        return original(world, character, session_id, **kwargs)

    monkeypatch.setattr(recovery, "_update_active_thought", counted)
    interruptions = recovery.RecoveryInterruptions()
    recovery.RestRecoveryConsequence(interruptions).process(world, 0)
    assert set(processed) == resting_ids

    processed.clear()
    recovery.SleepRecoveryConsequence(interruptions).process(world, 0)
    assert set(processed) == sleeping_ids


async def test_asleep_character_cannot_act_except_wake():
    scenario = lifecycle_scenario()
    rejects = collect(scenario.actor, CommandRejectedEvent)

    await scenario.actor.submit(cmd(scenario, "sleep"))
    await scenario.actor.tick(HOUR)

    # A say command while asleep is rejected...
    await scenario.actor.submit(
        cmd(scenario, "say", cost=CommandCost(action=1, focus=1), text="hi")
    )
    await scenario.actor.tick(HOUR)
    assert any(r.reason == "character is asleep" for r in rejects)

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.has_component(SleepingComponent)  # still asleep


async def test_sleeping_listener_does_not_hear_say():
    scenario = lifecycle_scenario()
    sleeper = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), sleeper.id
    )
    sleeper.add_component(SleepingComponent(started_at_epoch=0))
    said = collect(scenario.actor, SpeechSaidEvent)

    await scenario.actor.submit(
        cmd(scenario, "say", cost=CommandCost(action=1, focus=1), text="Anyone awake?")
    )
    await scenario.actor.tick(HOUR)

    assert str(sleeper.id) not in said[0].target_ids


async def test_wait_yields_turn_without_state_change():
    scenario = lifecycle_scenario()
    executed = collect(scenario.actor, CommandExecutedEvent)

    await scenario.actor.submit(cmd(scenario, "wait", cost=CommandCost()))
    await scenario.actor.tick(HOUR)

    assert len(executed) == 1
    char = scenario.actor.world.get_entity(scenario.character)
    assert not char.has_component(SleepingComponent)


def test_lifecycle_handlers_reject_invalid_character_ids():
    scenario = lifecycle_scenario()
    invalid = build_submitted_command(
        character_id="not-an-id",
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="sleep",
        cost=CommandCost(),
        lane=Lane.WORLD,
    )
    ctx = handler_context(scenario)

    assert execute_handler(SleepHandler(), ctx, invalid).reason == "invalid character id"
    assert execute_handler(RestHandler(), ctx, invalid).reason == "invalid character id"
    assert execute_handler(WakeHandler(), ctx, invalid).reason == "invalid character id"
    assert execute_handler(WaitHandler(), ctx, invalid).reason == "invalid character id"

    missing = build_submitted_command(
        character_id="entity_999",
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="sleep",
        cost=CommandCost(),
        lane=Lane.WORLD,
    )
    assert execute_handler(SleepHandler(), ctx, missing).reason == "character does not exist"
    assert execute_handler(RestHandler(), ctx, missing).reason == "character does not exist"
    assert execute_handler(WakeHandler(), ctx, missing).reason == "character does not exist"
    assert execute_handler(WaitHandler(), ctx, missing).reason == "character does not exist"


def test_sleep_and_wake_reject_repeated_or_unmatched_state():
    scenario = lifecycle_scenario()
    sleep = cmd(scenario, "sleep")
    wake = cmd(scenario, "wake", cost=CommandCost())
    ctx = handler_context(scenario)

    assert execute_handler(WakeHandler(), ctx, wake).reason == "not asleep"

    rest = cmd(scenario, "rest", cost=CommandCost())
    assert execute_handler(RestHandler(), ctx, rest).ok is True
    assert execute_handler(RestHandler(), ctx, rest).reason == "already resting"
    scenario.actor.world.get_entity(scenario.character).remove_component(RestingComponent)

    assert execute_handler(SleepHandler(), ctx, sleep).ok is True
    assert execute_handler(SleepHandler(), ctx, sleep).reason == "already asleep"

    assert execute_handler(WakeHandler(), ctx, wake).ok is True
