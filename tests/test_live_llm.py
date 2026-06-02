"""Optional live LLM integration tests.

These tests are intentionally skipped by default. Enable them with ``BUNNYLAND_LIVE_LLM=1``
and provider-specific connection environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bunnyland.llm_agents import OllamaAgent, OpenRouterAgent
from bunnyland.worldgen import OllamaWorldAgent, OpenRouterWorldAgent

OLLAMA_CLOUD_HOST = "https://ollama.com"


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE entries for live tests without overriding the shell."""

    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

pytestmark = pytest.mark.live_llm


def _live_enabled() -> None:
    if os.environ.get("BUNNYLAND_LIVE_LLM") != "1":
        pytest.skip("set BUNNYLAND_LIVE_LLM=1 to run live LLM tests")


def _ollama_connection() -> tuple[str | None, str | None]:
    _live_enabled()
    host = os.environ.get("OLLAMA_HOST")
    api_key = os.environ.get("OLLAMA_CLOUD_API_KEY")
    if not (host or api_key):
        pytest.skip("set OLLAMA_HOST or OLLAMA_CLOUD_API_KEY to run live Ollama tests")
    if api_key and not host:
        host = OLLAMA_CLOUD_HOST
    return host, api_key


def _openrouter_connection() -> tuple[str, str | None]:
    _live_enabled()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        pytest.skip("set OPENROUTER_API_KEY to run live OpenRouter tests")
    return api_key, os.environ.get("OPENROUTER_SERVER_URL")


@pytest.mark.asyncio
async def test_live_ollama_character_agent_can_call_wait_tool():
    host, api_key = _ollama_connection()
    model = os.environ.get("BUNNYLAND_LIVE_OLLAMA_MODEL", "deepseek-v4-flash")
    agent = OllamaAgent(model=model, host=host, api_key=api_key)

    call = await agent.decide(
        "Call exactly one tool: wait. Do not call any other tool.",
        None,
        character_id="live-ollama",
    )

    assert call is not None
    assert call.name == "wait"


def test_live_ollama_world_agent_can_propose_room():
    host, api_key = _ollama_connection()
    model = os.environ.get("BUNNYLAND_LIVE_OLLAMA_WORLD_MODEL", "deepseek-v4-pro")
    agent = OllamaWorldAgent(model=model, host=host, api_key=api_key)

    room = agent.propose_room("a tiny live-test moss room", behind=None, known_rooms={})

    assert room.title
    assert room.description


@pytest.mark.asyncio
async def test_live_openrouter_character_agent_can_call_wait_tool():
    api_key, server_url = _openrouter_connection()
    model = os.environ.get("BUNNYLAND_LIVE_OPENROUTER_MODEL", "openai/gpt-4.1-mini")
    agent = OpenRouterAgent(model=model, api_key=api_key, server_url=server_url)

    call = await agent.decide(
        "Call exactly one tool: wait. Do not call any other tool.",
        None,
        character_id="live-openrouter",
    )

    assert call is not None
    assert call.name == "wait"


def test_live_openrouter_world_agent_can_propose_room():
    api_key, server_url = _openrouter_connection()
    model = os.environ.get("BUNNYLAND_LIVE_OPENROUTER_WORLD_MODEL", "openai/gpt-4.1")
    agent = OpenRouterWorldAgent(model=model, api_key=api_key, server_url=server_url)

    room = agent.propose_room("a tiny live-test moss room", behind=None, known_rooms={})

    assert room.title
    assert room.description
