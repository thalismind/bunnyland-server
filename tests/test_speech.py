"""Tests for say / tell with SpeechIntent."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    DeadComponent,
    IdentityComponent,
    Lane,
    SayHandler,
    SleepingComponent,
    SpeechIntent,
    SuspendedComponent,
    TellHandler,
    build_submitted_command,
    infer_intent,
    spawn_entity,
)
from bunnyland.core.events import SpeechSaidEvent, SpeechToldEvent
from bunnyland.core.handlers.base import HandlerContext

HOUR = 3600.0
SPEECH_COST = CommandCost(action=1, focus=1)


def speech_scenario():
    scenario = build_scenario()
    scenario.actor.register_handler(SayHandler())
    scenario.actor.register_handler(TellHandler())
    return scenario


def add_listener(scenario, room_id, *, name="Hazel"):
    listener = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind="character"), CharacterComponent(species="bunny")],
    )
    scenario.actor.world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), listener.id
    )
    return listener.id


def say(scenario, text, intent=None):
    payload = {"text": text}
    if intent is not None:
        payload["intent"] = intent.value if isinstance(intent, SpeechIntent) else intent
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="say",
        cost=SPEECH_COST,
        lane=Lane.WORLD,
        payload=payload,
    )


def tell(scenario, target_id, text, intent=None):
    payload = {"target_id": str(target_id), "text": text}
    if intent is not None:
        payload["intent"] = intent.value
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="tell",
        cost=SPEECH_COST,
        lane=Lane.WORLD,
        payload=payload,
    )


def audible_tell(scenario, target_id, text):
    payload = {"target_id": str(target_id), "text": text, "audible": True}
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="tell",
        cost=SPEECH_COST,
        lane=Lane.WORLD,
        payload=payload,
    )


def handler_context(scenario):
    return HandlerContext(scenario.actor.world, scenario.actor.epoch)


def execute_say(scenario, text, *, character_id=None, payload=None):
    command = say(scenario, text)
    if character_id is not None or payload is not None:
        command = build_submitted_command(
            character_id=character_id or str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="say",
            cost=SPEECH_COST,
            lane=Lane.WORLD,
            payload=payload if payload is not None else command.payload,
        )
    return SayHandler().execute(handler_context(scenario), command)


def execute_tell(scenario, target_id, text, *, character_id=None, payload=None):
    command = tell(scenario, target_id, text)
    if character_id is not None or payload is not None:
        command = build_submitted_command(
            character_id=character_id or str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="tell",
            cost=SPEECH_COST,
            lane=Lane.WORLD,
            payload=payload if payload is not None else command.payload,
        )
    return TellHandler().execute(handler_context(scenario), command)


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


# -- intent inference -------------------------------------------------------------------


def test_infer_intent_heuristics():
    assert infer_intent("") is SpeechIntent.NEUTRAL
    assert infer_intent("Is the water safe?") is SpeechIntent.QUESTION
    assert infer_intent("I'm so sorry, Hazel.") is SpeechIntent.APOLOGY
    assert infer_intent("Please pass the berries") is SpeechIntent.REQUEST
    assert infer_intent("Great job with the door.") is SpeechIntent.PRAISE
    assert infer_intent("I promise I will return.") is SpeechIntent.PROMISE
    assert infer_intent("The tunnel goes north.") is SpeechIntent.NEUTRAL


# -- say --------------------------------------------------------------------------------


async def test_say_is_heard_by_others_in_room():
    scenario = speech_scenario()
    listener = add_listener(scenario, scenario.room_a)
    said = collect(scenario.actor, SpeechSaidEvent)

    await scenario.actor.submit(say(scenario, "Hello, is anyone there?"))
    await scenario.actor.tick(HOUR)

    assert len(said) == 1
    event = said[0]
    assert str(listener) in event.target_ids
    assert str(scenario.character) not in event.target_ids  # not heard by self
    assert event.inferred_intent == SpeechIntent.QUESTION.value


async def test_say_spends_action_and_focus():
    scenario = speech_scenario()
    from bunnyland.core import ActionPointsComponent, FocusPointsComponent

    await scenario.actor.submit(say(scenario, "A plain statement."))
    await scenario.actor.tick(HOUR)

    char = scenario.actor.world.get_entity(scenario.character)
    # started at 5 action / 3 focus, capped by regen, minus 1 each
    assert char.get_component(ActionPointsComponent).current == 4.0
    assert char.get_component(FocusPointsComponent).current == 2.0


async def test_say_records_author_intent_separately_from_inferred():
    scenario = speech_scenario()
    add_listener(scenario, scenario.room_a)
    said = collect(scenario.actor, SpeechSaidEvent)

    # Plain text, but the author declares it an insult (absurd tone declaration).
    await scenario.actor.submit(
        say(scenario, "Your mother was a herring.", intent=SpeechIntent.INSULT)
    )
    await scenario.actor.tick(HOUR)

    event = said[0]
    assert event.author_intent == SpeechIntent.INSULT.value
    assert event.inferred_intent == SpeechIntent.NEUTRAL.value
    assert event.final_interpretation == SpeechIntent.INSULT.value  # author wins


async def test_suspended_listener_does_not_hear():
    scenario = speech_scenario()
    listener = add_listener(scenario, scenario.room_a)
    no_op = spawn_entity(scenario.actor.world)
    scenario.actor.suspend(listener, no_op.id)
    said = collect(scenario.actor, SpeechSaidEvent)

    await scenario.actor.submit(say(scenario, "Anyone awake?"))
    await scenario.actor.tick(HOUR)

    assert str(listener) not in said[0].target_ids


def test_say_rejects_invalid_empty_and_detached_speaker():
    scenario = speech_scenario()

    assert execute_say(scenario, "hello", character_id="not-an-id").reason == (
        "invalid character id"
    )
    assert execute_say(scenario, "hello", character_id="entity_999").reason == (
        "speaker does not exist"
    )
    assert execute_say(scenario, "   ").reason == "nothing to say"

    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )
    assert execute_say(scenario, "hello").reason == "speaker is not in a room"


def test_say_ignores_dead_sleeping_and_non_character_occupants_and_records_approach():
    scenario = speech_scenario()
    awake = add_listener(scenario, scenario.room_a, name="Awake")
    dead = add_listener(scenario, scenario.room_a, name="Dead")
    sleeping = add_listener(scenario, scenario.room_a, name="Sleeping")
    suspended = add_listener(scenario, scenario.room_a, name="Suspended")
    object_id = spawn_entity(scenario.actor.world, [IdentityComponent(name="rock", kind="item")])
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        object_id.id,
    )
    scenario.actor.world.get_entity(dead).add_component(
        DeadComponent(died_at_epoch=0, cause="test")
    )
    scenario.actor.world.get_entity(sleeping).add_component(SleepingComponent(started_at_epoch=0))
    scenario.actor.world.get_entity(suspended).add_component(SuspendedComponent(reason="test"))
    result = execute_say(
        scenario,
        "not actually an insult",
        payload={"text": "not actually an insult", "intent": "not-real", "approach": "polite"},
    )

    assert result.ok is True
    event = result.events[0]
    assert event.target_ids == (str(awake),)
    assert event.author_intent is None
    assert event.approach == "polite"


# -- tell -------------------------------------------------------------------------------


async def test_tell_is_directed_to_target():
    scenario = speech_scenario()
    listener = add_listener(scenario, scenario.room_a)
    told = collect(scenario.actor, SpeechToldEvent)

    await scenario.actor.submit(tell(scenario, listener, "Meet me by the basin."))
    await scenario.actor.tick(HOUR)

    assert len(told) == 1
    assert told[0].target_ids == (str(listener),)


async def test_tell_target_in_another_room_is_rejected():
    scenario = speech_scenario()
    listener = add_listener(scenario, scenario.room_b)  # different room
    told = collect(scenario.actor, SpeechToldEvent)

    await scenario.actor.submit(tell(scenario, listener, "Can you hear me?"))
    await scenario.actor.tick(HOUR)

    assert told == []


async def test_audible_tell_records_same_room_overhearers():
    scenario = speech_scenario()
    listener = add_listener(scenario, scenario.room_a)
    overhearer = add_listener(scenario, scenario.room_a, name="Clover")
    told = collect(scenario.actor, SpeechToldEvent)

    await scenario.actor.submit(audible_tell(scenario, listener, "The latch is loose."))
    await scenario.actor.tick(HOUR)

    assert told[0].target_ids == (str(listener),)
    assert told[0].overhearer_ids == (str(overhearer),)


def test_tell_rejects_invalid_empty_missing_absent_and_inactive_targets():
    scenario = speech_scenario()
    listener = add_listener(scenario, scenario.room_a)

    assert execute_tell(scenario, listener, "hello", character_id="not-an-id").reason == (
        "invalid speaker or target id"
    )
    assert execute_tell(scenario, listener, "hello", character_id="entity_999").reason == (
        "speaker does not exist"
    )
    assert execute_tell(
        scenario,
        listener,
        "hello",
        payload={"target_id": "not-an-id", "text": "hello"},
    ).reason == "invalid speaker or target id"
    assert execute_tell(scenario, listener, "   ").reason == "nothing to say"
    assert execute_tell(scenario, "entity_999", "hello").reason == "target does not exist"

    scenario.actor.world.get_entity(listener).add_component(SleepingComponent(started_at_epoch=0))
    assert execute_tell(scenario, listener, "hello").reason == "target cannot hear you"

    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )
    assert execute_tell(scenario, listener, "hello").reason == "target is not present"


def test_quiet_tell_has_no_overhearers_and_preserves_approach():
    scenario = speech_scenario()
    listener = add_listener(scenario, scenario.room_a)
    add_listener(scenario, scenario.room_a, name="Clover")

    result = execute_tell(
        scenario,
        listener,
        "Please listen.",
        payload={
            "target_id": str(listener),
            "text": "Please listen.",
            "intent": SpeechIntent.REQUEST,
            "approach": "polite",
        },
    )

    assert result.ok is True
    event = result.events[0]
    assert event.author_intent == SpeechIntent.REQUEST.value
    assert event.overhearer_ids == ()
    assert event.approach == "polite"
