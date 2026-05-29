"""End-to-end MVP test: a generated world driven by the game loop and a scripted agent."""

from __future__ import annotations

from bunnyland.core import WorldActor, container_of
from bunnyland.engine import GameLoop
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent, ToolCall
from bunnyland.plugins import apply_plugins, bunnyland_plugins
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.worldgen import StubWorldBuilder, instantiate


async def test_game_loop_drives_an_llm_character_through_a_move():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    result = await instantiate(actor, StubWorldBuilder().propose("seed"))

    builder = PromptBuilder(actor.world)
    agent = ScriptedAgent([ToolCall("move", {"direction": "north"})])
    dispatch = ControllerDispatch(actor, builder, agent)
    loop = GameLoop(actor, dispatch, tick_seconds=1.0, time_scale=3600.0)

    # tick 1 lets the agent submit; tick 2 executes the queued move.
    ticks = await loop.run(max_ticks=2)
    assert ticks == 2

    hazel = actor.world.get_entity(result.characters["hazel"])
    assert container_of(hazel) == result.rooms["tunnel"]


async def test_game_loop_stops_when_asked():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    await instantiate(actor, StubWorldBuilder().propose("seed"))

    builder = PromptBuilder(actor.world)
    loop = GameLoop(actor, None)  # dispatch set below so the agent can stop the loop

    class StoppingAgent:
        def decide(self, prompt, context, *, character_id):
            loop.stop()
            return None

    loop.dispatch = ControllerDispatch(actor, builder, StoppingAgent())

    # No max_ticks: the agent stops the loop during the first dispatch.
    assert await loop.run() == 1
