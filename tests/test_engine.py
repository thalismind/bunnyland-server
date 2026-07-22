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
    result = await instantiate(actor, await StubWorldBuilder().propose("seed"))

    builder = PromptBuilder(actor.world)
    agent = ScriptedAgent([ToolCall("move", {"direction": "north"})])
    dispatch = ControllerDispatch(actor, builder, agent)
    loop = GameLoop(actor, dispatch, tick_seconds=1.0, time_scale=3600.0)

    assert loop.running is False

    # tick 1 lets the agent submit; tick 2 executes the queued move.
    ticks = await loop.run(max_ticks=2)
    assert ticks == 2
    assert loop.running is False

    hazel = actor.world.get_entity(result.characters["hazel"])
    assert container_of(hazel) == result.rooms["tunnel"]


async def test_game_loop_keeps_ticking_while_a_decision_is_pending():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    await instantiate(actor, await StubWorldBuilder().propose("seed"))
    builder = PromptBuilder(actor.world)

    class SlowAgent:
        def __init__(self) -> None:
            self.gate = asyncio.Event()
            self.prompts = 0

        async def decide(
            self, prompt, context, *, character_id, model=None, provider=None, tools=None
        ):
            del prompt, context, character_id, model, provider, tools
            self.prompts += 1

            await self.gate.wait()
            return None

    agent = SlowAgent()
    loop = GameLoop(
        actor, ControllerDispatch(actor, builder, agent), tick_seconds=0.001, time_scale=1000.0
    )
    task = asyncio.create_task(loop.run())
    try:
        for _ in range(500):
            if actor.epoch >= 3:
                break
            await asyncio.sleep(0.002)
        # The world advanced several ticks even though the agent's prompt never returned, and
        # the character with a pending decision was prompted exactly once (never re-prompted).
        assert actor.epoch >= 3
        assert agent.prompts == 1
    finally:
        loop.stop()
        agent.gate.set()
        await asyncio.wait_for(task, timeout=1.0)


async def test_game_loop_sends_only_latest_buffer_after_prior_action_commits():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    result = await instantiate(actor, await StubWorldBuilder().propose("seed"))

    class TwoTurnAgent:
        def __init__(self) -> None:
            self.first_gate = asyncio.Event()
            self.second_gate = asyncio.Event()
            self.contexts = []

        async def decide(
            self, prompt, context, *, character_id, model=None, provider=None, tools=None
        ):
            del prompt, character_id, model, provider, tools
            self.contexts.append(context)
            if len(self.contexts) == 1:
                await self.first_gate.wait()
                return ToolCall("move", {"direction": "north"})
            await self.second_gate.wait()
            return None

    agent = TwoTurnAgent()
    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), agent)
    loop = GameLoop(actor, dispatch, tick_seconds=0.001, time_scale=1000.0)
    task = asyncio.create_task(loop.run())
    try:
        for _ in range(500):
            if actor.epoch >= 3:
                break
            await asyncio.sleep(0.002)
        assert len(agent.contexts) == 1

        agent.first_gate.set()
        for _ in range(500):
            if len(agent.contexts) == 2:
                break
            await asyncio.sleep(0.002)

        assert len(agent.contexts) == 2
        assert agent.contexts[0].location_title == "Mosslit Burrow"
        assert agent.contexts[1].location_title == "North Tunnel"
        hazel = actor.world.get_entity(result.characters["hazel"])
        assert container_of(hazel) == result.rooms["tunnel"]
    finally:
        loop.stop()
        agent.first_gate.set()
        agent.second_gate.set()
        await asyncio.wait_for(task, timeout=1.0)


async def test_game_loop_stops_when_asked():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    await instantiate(actor, await StubWorldBuilder().propose("seed"))

    builder = PromptBuilder(actor.world)
    loop = GameLoop(actor, None)  # dispatch set below so the agent can stop the loop

    class StoppingAgent:
        async def decide(
            self, prompt, context, *, character_id, model=None, provider=None, tools=None
        ):
            del model, provider, tools
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


async def test_game_loop_autosave_fires_on_cadence_and_exposes_state():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    await instantiate(actor, await StubWorldBuilder().propose("seed"))
    builder = PromptBuilder(actor.world)
    dispatch = ControllerDispatch(actor, builder, ScriptedAgent([]))

    saved: list[int] = []
    loop = GameLoop(
        actor,
        dispatch,
        tick_seconds=1.0,
        autosave=saved.append,
        autosave_every=2,
    )

    # State getters before running.
    assert loop.paused is False
    assert loop.next_tick_at_unix is None

    ticks = await loop.run(max_ticks=4)

    assert ticks == 4
    # Autosave fired on ticks 2 and 4.
    assert saved == [2, 4]
    assert loop.next_tick_at_unix is None


def test_game_loop_pause_publishes_synchronously_without_a_running_loop():
    # Called outside any event loop, pause/resume fall back to asyncio.run and return None
    # rather than scheduling a task; the events still reach subscribers.
    actor = WorldActor()
    builder = PromptBuilder(actor.world)
    loop = GameLoop(actor, ControllerDispatch(actor, builder, ScriptedAgent([])))
    events = []
    actor.bus.subscribe(WorldPauseStatusChangedEvent, events.append)

    assert loop.pause() is None
    assert loop.resume() is None

    assert [(event.paused, event.state) for event in events] == [
        (True, "paused"),
        (False, "resumed"),
    ]


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
