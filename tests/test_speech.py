"""Tests for say / tell with SpeechIntent."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    SayHandler,
    SpeechIntent,
    TellHandler,
    build_submitted_command,
    infer_intent,
    spawn_entity,
)
from bunnyland.core.events import SpeechSaidEvent, SpeechToldEvent

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


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


# -- intent inference -------------------------------------------------------------------


def test_infer_intent_heuristics():
    assert infer_intent("Is the water safe?") is SpeechIntent.QUESTION
    assert infer_intent("I'm so sorry, Hazel.") is SpeechIntent.APOLOGY
    assert infer_intent("Please pass the berries") is SpeechIntent.REQUEST
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
