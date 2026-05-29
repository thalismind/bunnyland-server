"""Tests for the LLM tool surface, scripted agent, and controller dispatch."""

from __future__ import annotations

import sys
import types

from conftest import build_scenario

from bunnyland.core import CommandCost, Lane
from bunnyland.llm_agents import (
    ControllerDispatch,
    ScriptedAgent,
    ToolCall,
    command_from_tool_call,
    tool_names,
    tool_schemas,
)
from bunnyland.llm_agents.agent import OllamaAgent
from bunnyland.prompts.builder import PromptBuilder


def test_tool_schemas_cover_every_verb():
    names = {s["function"]["name"] for s in tool_schemas()}
    assert names == set(tool_names())
    assert {"move", "say", "take", "drop", "take_note", "remember", "wait"} <= names


def test_command_from_tool_call_renames_drop_to_put():
    call = ToolCall(name="drop", arguments={"item_id": "item_1"})
    command = command_from_tool_call(
        call, character_id="char_1", controller_id="ctrl_1", controller_generation=0
    )
    assert command.command_type == "put"
    assert command.lane is Lane.WORLD
    assert command.cost == CommandCost(action=1)
    assert command.payload == {"item_id": "item_1"}


def test_command_from_tool_call_drops_unknown_arguments():
    call = ToolCall(name="move", arguments={"direction": "north", "bogus": "x"})
    command = command_from_tool_call(
        call, character_id="char_1", controller_id="ctrl_1", controller_generation=0
    )
    assert command.payload == {"direction": "north"}


def test_scripted_agent_replays_then_waits():
    agent = ScriptedAgent([ToolCall("wait", {})])
    first = agent.decide("prompt", None, character_id="char_1")
    assert first is not None and first.name == "wait"
    assert agent.decide("prompt", None, character_id="char_1") is None


async def test_dispatch_submits_a_command_for_an_llm_character():
    scenario = build_scenario()
    builder = PromptBuilder(scenario.actor.world)
    agent = ScriptedAgent([ToolCall("move", {"direction": "north"})])
    dispatch = ControllerDispatch(scenario.actor, builder, agent)

    decisions = await dispatch.run_once()

    assert len(decisions) == 1
    assert decisions[0].tool == "move"
    # The command is submitted (inbox), not yet executed.
    assert not scenario.actor._inbox.empty()


class _FakeOllamaClient:
    """Records the messages sent on each chat call and replies with a fixed tool call."""

    def __init__(self, *args, **kwargs):
        self.calls: list[list[dict]] = []

    def chat(self, *, model, messages, tools):
        del model, tools
        self.calls.append([dict(m) for m in messages])  # snapshot
        return {"message": {"role": "assistant", "content": "ok",
                            "tool_calls": [{"function": {"name": "wait", "arguments": {}}}]}}


def test_ollama_agent_resends_prior_turns_as_context(monkeypatch):
    fake_module = types.ModuleType("ollama")
    fake_module.Client = _FakeOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaAgent(model="llama3")
    agent.decide("turn one", None, character_id="char_1")
    agent.decide("turn two", None, character_id="char_1")

    client = agent._client
    # Second chat call carries the full history: turn one (user + assistant) + turn two.
    second = client.calls[1]
    assert second[0] == {"role": "user", "content": "turn one"}
    assert second[1]["role"] == "assistant"
    assert second[2] == {"role": "user", "content": "turn two"}


def test_ollama_agent_keeps_history_per_character(monkeypatch):
    fake_module = types.ModuleType("ollama")
    fake_module.Client = _FakeOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaAgent(model="llama3")
    agent.decide("hazel turn", None, character_id="hazel")
    agent.decide("juniper turn", None, character_id="juniper")

    # Juniper's first call must not contain Hazel's history.
    juniper_call = agent._client.calls[1]
    assert juniper_call == [{"role": "user", "content": "juniper turn"}]


async def test_dispatch_records_wait_when_agent_passes():
    scenario = build_scenario()
    builder = PromptBuilder(scenario.actor.world)
    dispatch = ControllerDispatch(scenario.actor, builder, ScriptedAgent([]))

    decisions = await dispatch.run_once()

    assert len(decisions) == 1
    assert decisions[0].tool is None
    assert scenario.actor._inbox.empty()
