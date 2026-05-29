"""End-to-end tests (spec 28).

These exercise the whole stack the way a running server does:

1. generate a world and verify the instantiated ECS matches what was requested
   ("fits the proposal") and what the agent is shown ("fits the prompt");
2. play several rounds with a scripted agent and verify each action is processed
   correctly across movement, inventory, needs, and speech.

The scripted agent keeps these deterministic; the same path runs live with an Ollama
agent (see the docs).
"""

from __future__ import annotations

from bunnyland.core import (
    CharacterComponent,
    ContainerComponent,
    ControlledBy,
    LLMControllerComponent,
    SuspendedComponent,
    WorldActor,
    container_of,
)
from bunnyland.core.components import RoomComponent, WritableComponent
from bunnyland.core.edges import ExitTo
from bunnyland.core.events import (
    ActorMovedEvent,
    CommandRejectedEvent,
    ItemTakenEvent,
    SpeechSaidEvent,
)
from bunnyland.engine import GameLoop
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent, ToolCall
from bunnyland.mechanics.consumables import DrinkableComponent, FoodComponent
from bunnyland.mechanics.needs import DrinkConsumedEvent, FoodEatenEvent
from bunnyland.plugins import apply_plugins, bunnyland_plugins
from bunnyland.prompts.builder import PromptBuilder, render_prompt
from bunnyland.worldgen import StubWorldBuilder, instantiate

KIND_COMPONENT = {
    "food": FoodComponent,
    "water": DrinkableComponent,
    "container": ContainerComponent,
    "paper": WritableComponent,
}


async def _new_world():
    """A fully wired actor (all builtin plugins) with the stub marsh world generated."""
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = StubWorldBuilder().propose("a quiet marsh")
    result = await instantiate(actor, proposal)
    return actor, proposal, result


# -- the world fits the proposal --------------------------------------------------------


async def test_generated_world_matches_its_proposal():
    actor, proposal, result = await _new_world()
    world = actor.world

    # Every proposed room exists, titled as requested.
    assert len(result.rooms) == len(proposal.rooms)
    titles = {
        world.get_entity(result.rooms[r.key]).get_component(RoomComponent).title
        for r in proposal.rooms
    }
    assert titles == {r.title for r in proposal.rooms}

    # Every exit connects the requested rooms in the requested direction.
    for exit_ in proposal.exits:
        source = world.get_entity(result.rooms[exit_.from_key])
        by_direction = {edge.direction: target for edge, target in source.get_relationships(ExitTo)}
        assert by_direction.get(exit_.direction) == result.rooms[exit_.to_key]

    # Each object sits in the right room and carries the component its kind implies.
    for obj in proposal.objects:
        entity = world.get_entity(result.objects[obj.key])
        assert container_of(entity) == result.rooms[obj.room_key]
        expected = KIND_COMPONENT.get(obj.kind)
        if expected is not None:
            assert entity.has_component(expected), f"{obj.key} should have {expected.__name__}"

    # Characters are placed and wired to the requested controller kind.
    for character in proposal.characters:
        entity = world.get_entity(result.characters[character.key])
        assert entity.has_component(CharacterComponent)
        assert container_of(entity) == result.rooms[character.room_key]
        if character.controller == "suspended":
            assert entity.has_component(SuspendedComponent)
        else:
            controllers = [
                world.get_entity(target)
                for _edge, target in entity.get_relationships(ControlledBy)
            ]
            assert any(c.has_component(LLMControllerComponent) for c in controllers)


async def test_agent_prompt_reflects_the_generated_world():
    actor, _proposal, result = await _new_world()
    prompt = render_prompt(PromptBuilder(actor.world).build(result.characters["hazel"]))

    assert "Mosslit Burrow" in prompt  # the room it is standing in
    assert "north" in prompt  # the exit to the tunnel
    assert "three berries" in prompt  # an item on the floor
    assert "a scrap of paper" in prompt
    assert "Juniper" in prompt  # the other character present
    assert "move north" in prompt  # an offered command


# -- playing the world processes actions ------------------------------------------------


async def test_scripted_playthrough_processes_actions_each_round():
    actor, _proposal, result = await _new_world()
    hazel = result.characters["hazel"]

    seen: dict[type, list] = {
        event_type: []
        for event_type in (
            FoodEatenEvent,
            DrinkConsumedEvent,
            ItemTakenEvent,
            SpeechSaidEvent,
            ActorMovedEvent,
            CommandRejectedEvent,
        )
    }
    for event_type, sink in seen.items():
        actor.bus.subscribe(event_type, sink.append)

    # One action per round, referring to things by name (dispatch resolves names to ids).
    agent = ScriptedAgent(
        [
            ToolCall("eat", {"item_id": "three berries"}),
            ToolCall("drink", {"source_id": "a stone basin of water"}),
            ToolCall("take", {"item_id": "a scrap of paper"}),
            ToolCall("say", {"text": "Hello, burrow.", "intent": "conversation"}),
            ToolCall("move", {"direction": "north"}),
        ]
    )
    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), agent)
    loop = GameLoop(actor, dispatch, tick_seconds=1.0, time_scale=3600.0)

    # 5 actions need 6 ticks: a tick submits round N, the next tick executes it.
    await loop.run(max_ticks=6)

    # Each action was accepted and produced its domain event; nothing was rejected.
    assert seen[CommandRejectedEvent] == []
    assert len(seen[FoodEatenEvent]) == 1
    assert len(seen[DrinkConsumedEvent]) == 1
    assert len(seen[ItemTakenEvent]) == 1
    assert len(seen[SpeechSaidEvent]) == 1
    assert len(seen[ActorMovedEvent]) == 1

    # Final state reflects the playthrough: paper carried, character moved north.
    world = actor.world
    assert container_of(world.get_entity(result.objects["paper"])) == hazel
    assert container_of(world.get_entity(hazel)) == result.rooms["tunnel"]


async def test_unreachable_target_is_not_processed_and_coaches_the_agent():
    # An action naming something that isn't there must not execute, and the agent should be
    # given a "did you mean..." hint on its next prompt (parity with the Discord bot).
    actor, _proposal, result = await _new_world()

    rejected: list = []
    moved: list = []
    actor.bus.subscribe(CommandRejectedEvent, rejected.append)
    actor.bus.subscribe(ActorMovedEvent, moved.append)

    # "paper" is not a prefix of any item, but it is near "a scrap of paper".
    agent = ScriptedAgent([ToolCall("take", {"item_id": "paper"})])
    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), agent)
    loop = GameLoop(actor, dispatch, tick_seconds=1.0, time_scale=3600.0)
    # One round: the agent names an item it can't resolve; nothing should be submitted.
    await loop.run(max_ticks=1)

    # The doomed command was never submitted, so there is no handler rejection either.
    assert rejected == []
    assert moved == []
    # A "did you mean..." hint is queued for the agent's next prompt.
    feedback = dispatch._feedback.get(str(result.characters["hazel"]))
    assert feedback and "did you mean" in feedback.lower()
    assert "a scrap of paper" in feedback
