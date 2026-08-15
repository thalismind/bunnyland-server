"""Opt-in Ollama Cloud smoke coverage for independent multiplayer player agents."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from pydantic import JsonValue

from bunnyland.llm_agents import OllamaAgent, ToolCall
from bunnyland.playtest import DEFAULT_PLAYER_SYSTEM_PROMPT
from bunnyland.prompts.builder import PromptContext

pytestmark = pytest.mark.live_llm


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _enabled() -> tuple[str, str]:
    if os.environ.get("BUNNYLAND_LIVE_LLM") != "1":
        pytest.skip("set BUNNYLAND_LIVE_LLM=1 to run live LLM tests")
    api_key = os.environ.get("OLLAMA_CLOUD_API_KEY")
    if not api_key:
        pytest.skip("set OLLAMA_CLOUD_API_KEY to run live Ollama Cloud tests")
    return api_key, os.environ.get("BUNNYLAND_LIVE_OLLAMA_MODEL", "deepseek-v4-flash")


@pytest.mark.asyncio
async def test_live_ollama_cloud_accepts_medium_thinking_for_a_tool_call():
    api_key, model = _enabled()
    responses: list[dict[str, JsonValue]] = []
    agent = OllamaAgent(
        model=model,
        host="https://ollama.com",
        api_key=api_key,
        think="medium",
        max_retries=0,
        response_observer=responses.append,
        log_thinking=True,
    )
    context = PromptContext(
        name="player",
        kind="player",
        status="active",
        action=(5, 5),
        focus=(3, 3),
        location_title="Apple Crossing",
        room_summary="Apple Crossing",
        commands=("Wait",),
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "wait",
                "description": "Wait for one turn.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    try:
        decision = await agent.decide(
            "Call the wait tool.",
            context,
            character_id="medium-thinking-player",
            tools=tools,
        )
    finally:
        await agent.close()

    assert isinstance(decision, ToolCall)
    assert decision.name == "wait"
    assert responses
    assert responses[0]["eval_count"]


@pytest.mark.asyncio
async def test_live_ollama_cloud_player_agents_keep_independent_histories():
    api_key, model = _enabled()
    context = PromptContext(
        name="player",
        kind="player",
        status="active",
        action=(5, 5),
        focus=(3, 3),
        location_title="Apple Crossing",
        room_summary="Apple Crossing",
        commands=("Wait",),
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "wait",
                "description": "Wait for one turn.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    requests: list[list[dict[str, JsonValue]]] = [[], []]
    responses: list[list[dict[str, JsonValue]]] = [[], []]
    agents = [
        OllamaAgent(
            model=model,
            host="https://ollama.com",
            api_key=api_key,
            system_prompt=f"{DEFAULT_PLAYER_SYSTEM_PROMPT} Your test identity is player {index}.",
            max_output_tokens=256,
            request_observer=requests[index].append,
            response_observer=responses[index].append,
            log_thinking=True,
        )
        for index in range(2)
    ]
    try:
        decisions = await asyncio.gather(
            *(
                agent.decide(
                    f"Live multiplayer smoke for player {index}: call wait.",
                    context,
                    character_id=f"player-{index}",
                    tools=tools,
                )
                for index, agent in enumerate(agents)
            )
        )
        assert all(
            isinstance(decision, ToolCall) and decision.name == "wait"
            for decision in decisions
        ), [
            decision.reason if not isinstance(decision, ToolCall) else decision.name
            for decision in decisions
        ]
        assert set(agents[0]._history) == {"player-0"}
        assert set(agents[1]._history) == {"player-1"}
        for index in range(2):
            assert requests[index][0]["provider"] == "ollama"
            messages = requests[index][0]["messages"]
            assert messages[-1]["content"].startswith(
                f"Live multiplayer smoke for player {index}"
            )
            assert responses[index][0]["message"]["tool_calls"][0]["function"][
                "name"
            ] == "wait"
    finally:
        for agent in agents:
            await agent.close()
