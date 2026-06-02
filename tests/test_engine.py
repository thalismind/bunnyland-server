"""End-to-end MVP test: a generated world driven by the game loop and a scripted agent."""

from __future__ import annotations

import asyncio

from bunnyland.core import WorldActor, WorldPauseStatusChangedEvent, container_of
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
        def decide(self, prompt, context, *, character_id, model=None, provider=None):
            del model, provider
            loop.stop()
            return None

    loop.dispatch = ControllerDispatch(actor, builder, StoppingAgent())

    # No max_ticks: the agent stops the loop during the first dispatch.
    assert await loop.run() == 1


async def test_game_loop_pause_blocks_ticks_until_resumed():
    actor = WorldActor()
    builder = PromptBuilder(actor.world)
    loop = GameLoop(
        actor,
        ControllerDispatch(actor, builder, ScriptedAgent([])),
        tick_seconds=0.01,
        paused=True,
    )

    task = asyncio.create_task(loop.run(max_ticks=1))
    await asyncio.sleep(0.03)
    assert actor.epoch == 0
    assert not task.done()

    loop.resume()
    assert await asyncio.wait_for(task, timeout=1.0) == 1
    assert actor.epoch > 0


async def test_game_loop_emits_pause_status_events_once_per_transition():
    actor = WorldActor()
    builder = PromptBuilder(actor.world)
    loop = GameLoop(actor, ControllerDispatch(actor, builder, ScriptedAgent([])))
    events = []
    actor.bus.subscribe(WorldPauseStatusChangedEvent, events.append)

    publish = loop.pause()
    if publish is not None:
        await publish
    assert loop.pause() is None

    publish = loop.resume()
    if publish is not None:
        await publish
    assert loop.resume() is None

    assert [(event.paused, event.state, event.message) for event in events] == [
        (True, "paused", "World paused."),
        (False, "resumed", "World resumed."),
    ]
