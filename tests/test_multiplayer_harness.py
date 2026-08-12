"""Deterministic tests for the live multiplayer LLM harness."""

from __future__ import annotations

import asyncio
import json
import stat

import pytest
from pydantic import JsonValue, ValidationError

from bunnyland.llm_agents import InvalidAgentResponse, ToolCall
from bunnyland.playtest.multiplayer import (
    AdminTraceRecord,
    MultiplayerHarness,
    MultiplayerHarnessConfig,
    MultiplayerHarnessError,
    NdjsonAdminTraceWriter,
    PlayerSpec,
    _command_payload,
    _json_arguments,
    _player_prompt,
    _tool_schema,
    load_multiplayer_config,
)
from bunnyland.server.models import (
    CharacterSummaryView,
    ClientActionArgumentView,
    ClientActionView,
    ClientEntityView,
    ClientExitView,
    ClientPointsView,
    ClientRoomView,
    ClientTargetView,
    CommandCostRequest,
)
from bunnyland.tui.backend import ControlClaim, SubmitResult

SYSTEM_PROMPT = "Use one structured tool and stay grounded in visible world state."


class _RecordingAgent:
    def __init__(
        self,
        decisions: tuple[ToolCall | InvalidAgentResponse | None, ...],
        request_observer=None,
        response_observer=None,
    ) -> None:
        self.decisions = decisions
        self.request_observer = request_observer
        self.response_observer = response_observer
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def decide(
        self,
        prompt,
        context,
        *,
        character_id,
        model=None,
        provider=None,
        tools=None,
    ):
        if self.request_observer is not None:
            self.request_observer(
                {
                    "provider": str(provider),
                    "model": str(model),
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": tools or [],
                }
            )
        if self.response_observer is not None:
            self.response_observer({"message": {"role": "assistant", "content": ""}})
        self.calls.append(
            {
                "prompt": prompt,
                "context": context,
                "character_id": character_id,
                "model": model,
                "provider": provider,
                "tools": tools,
            }
        )
        return self.decisions[min(len(self.calls) - 1, len(self.decisions) - 1)]

    async def close(self) -> None:
        self.closed = True


class _Backend:
    def __init__(self, name: str, *, accepted: bool = True) -> None:
        self.character = CharacterSummaryView(character_id=f"id-{name}", name=name)
        self.accepted = accepted
        self.started = False
        self.closed = False
        self.released = False
        self.submissions: list[dict[str, JsonValue]] = []
        self.projection_calls = 0

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def fetch_character_list(self):
        return [self.character]

    async def claim(self, player_id, world):
        del world
        assert player_id == self.character.character_id
        return ControlClaim("controller", 1, "claim", "secret")

    async def release_claim(self, player_id, control):
        assert player_id == self.character.character_id
        assert control.claim_id == "claim"
        self.released = True
        return True

    async def fetch_character_projection(self, character_id):
        assert character_id == self.character.character_id
        self.projection_calls += 1
        return _projection(character_id, self.character.name, self.projection_calls)

    async def submit(self, command):
        self.submissions.append(command)
        return SubmitResult(self.accepted, "queued" if self.accepted else "blocked")


def _projection(character_id: str, name: str, world_epoch: int) -> dict[str, JsonValue]:
    return {
        "world_epoch": world_epoch,
        "character_id": character_id,
        "character_name": name,
        "can_perceive": True,
        "room": {
            "id": "room-1",
            "title": "Shared Green",
            "description": "A busy common room.",
            "entities": [
                {"id": "friend-1", "name": "Neighbor", "kind": "character", "is_character": True},
                {"id": "item-1", "name": "red apple", "kind": "item"},
            ],
            "exits": [{"id": "room-2", "direction": "north", "label": "north: Orchard"}],
        },
        "inventory": [],
        "points": {"action": 5, "action_max": 5, "focus": 3, "focus_max": 3},
        "current_goal": "Explore together.",
        "suggested_actions": ["Go north."],
        "target_groups": {
            "exits": [{"id": "room-2", "label": "north: Orchard", "kind": "exit"}],
            "reachableItems": [{"id": "item-1", "label": "red apple", "kind": "item"}],
        },
        "actions": [
            {
                "command_type": "move",
                "tool_name": "move",
                "title": "Move",
                "description": "Move through a visible exit.",
                "lane": "world",
                "cost": {"action": 1, "focus": 0},
                "arguments": [
                    {"key": "direction", "kind": "string"},
                    {"key": "exit_id", "kind": "entity", "target_group": "exits"},
                ],
            }
        ],
    }


def _config(players: tuple[PlayerSpec, ...], **updates) -> MultiplayerHarnessConfig:
    values = {
        "server_url": "https://play.example/v1",
        "shared_provider": "ollama-cloud",
        "shared_model": "shared-model",
        "players": players,
        "turns": 2,
        "turn_interval_seconds": 0,
    }
    values.update(updates)
    return MultiplayerHarnessConfig(**values)


def test_config_requires_unique_players_and_explicit_system_prompts(tmp_path):
    player = PlayerSpec(name="one", character="Juniper", system_prompt=SYSTEM_PROMPT)
    with pytest.raises(ValidationError, match="player names must be unique"):
        _config((player, player))
    with pytest.raises(ValidationError, match="system_prompt"):
        PlayerSpec(name="missing", character="Juniper")
    with pytest.raises(ValidationError, match="password_env"):
        PlayerSpec(
            name="auth",
            character="Juniper",
            system_prompt=SYSTEM_PROMPT,
            username="player",
        )

    path = tmp_path / "players.yml"
    path.write_text(
        "server_url: https://play.example/v1\n"
        "shared_model: cloud-model\n"
        "players:\n"
        "  - name: one\n"
        "    character: Juniper\n"
        f"    system_prompt: {SYSTEM_PROMPT}\n",
        encoding="utf-8",
    )
    loaded = load_multiplayer_config(path)
    assert loaded.players[0].model is None
    assert loaded.shared_model == "cloud-model"

    path.write_text("players: [\n", encoding="utf-8")
    with pytest.raises(MultiplayerHarnessError, match="could not load"):
        load_multiplayer_config(path)
    path.write_text("server_url: ''\nplayers: []\n", encoding="utf-8")
    with pytest.raises(MultiplayerHarnessError, match="invalid multiplayer config"):
        load_multiplayer_config(path)


def test_default_factories_resolve_provider_and_player_credentials(monkeypatch):
    created: list[tuple[str, dict[str, object]]] = []

    class _FakeProviderAgent:
        def __init__(self, **kwargs):
            created.append((self.__class__.__name__, kwargs))

    class FakeOllama(_FakeProviderAgent):
        pass

    class FakeOpenRouter(_FakeProviderAgent):
        pass

    monkeypatch.setattr("bunnyland.playtest.multiplayer.OllamaAgent", FakeOllama)
    monkeypatch.setattr("bunnyland.playtest.multiplayer.OpenRouterAgent", FakeOpenRouter)
    player = PlayerSpec(
        name="one",
        character="Juniper",
        system_prompt=SYSTEM_PROMPT,
        access_token_env="PLAYER_TOKEN",
    )
    config = _config((player,), shared_provider="ollama-local", ollama_host="http://ollama")
    harness = MultiplayerHarness(config)
    backend = harness._build_backend(player, "client-id")
    assert backend.client_id == "client-id"
    assert backend._access_token == ""

    local = harness._build_agent(player, "ollama-local", "local-model", config)
    assert isinstance(local, FakeOllama)
    assert created[-1][1]["host"] == "http://ollama"
    monkeypatch.delenv("OLLAMA_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(MultiplayerHarnessError, match="OLLAMA_CLOUD_API_KEY"):
        harness._build_agent(player, "ollama-cloud", "cloud-model", config)
    with pytest.raises(MultiplayerHarnessError, match="OPENROUTER_API_KEY"):
        harness._build_agent(player, "openrouter", "router-model", config)

    monkeypatch.setenv("PLAYER_TOKEN", "player-token")
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "ollama-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    backend = harness._build_backend(player, "client-id")
    assert backend._access_token == "player-token"
    cloud = harness._build_agent(player, "ollama-cloud", "cloud-model", config)
    router = harness._build_agent(player, "openrouter", "router-model", config)
    assert isinstance(cloud, FakeOllama)
    assert created[-2][1]["api_key"] == "ollama-key"
    assert isinstance(router, FakeOpenRouter)
    assert created[-1][1]["api_key"] == "router-key"


async def test_harness_runs_arbitrary_players_concurrently_with_isolated_state():
    specs = (
        PlayerSpec(name="one", character="Juniper", system_prompt="prompt one"),
        PlayerSpec(
            name="two",
            character="Pippa",
            provider="openrouter",
            model="player-model",
            system_prompt="prompt two",
        ),
    )
    backends: dict[str, _Backend] = {}
    agents: dict[str, _RecordingAgent] = {}
    active = 0
    peak = 0

    class _ConcurrentBackend(_Backend):
        async def start(self) -> None:
            nonlocal active, peak
            await super().start()
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)

        async def close(self) -> None:
            nonlocal active
            active -= 1
            await super().close()

    def backend_factory(player, client_id):
        assert client_id.startswith("llm-playtest-")
        backend = _ConcurrentBackend(player.character)
        backends[player.name] = backend
        return backend

    def agent_factory(
        player, provider, model, config, request_observer, response_observer
    ):
        del provider, model, config
        agent = _RecordingAgent(
            (ToolCall("move", {"exit_id": "room-2"}),),
            request_observer,
            response_observer,
        )
        agents[player.name] = agent
        return agent

    result = await MultiplayerHarness(
        _config(specs),
        agent_factory=agent_factory,
        backend_factory=backend_factory,
        completion_probe=lambda projection: projection.world_epoch >= 2,
    ).run()

    assert peak == 2
    assert [player.status for player in result.players] == ["completed", "completed"]
    assert result.players[0].model == "shared-model"
    assert result.players[1].model == "player-model"
    assert agents["one"] is not agents["two"]
    assert agents["one"].calls[0]["character_id"] == "id-Juniper"
    assert agents["two"].calls[0]["character_id"] == "id-Pippa"
    assert "Turn 1: move was accepted" not in agents["one"].calls[0]["prompt"]
    assert backends["one"].submissions[0]["payload"] == {
        "exit_id": "room-2",
        "direction": "north",
    }
    assert all(backend.released and backend.closed for backend in backends.values())
    assert all(agent.closed for agent in agents.values())


async def test_harness_records_invalid_responses_refusals_and_turn_limit(tmp_path):
    spec = PlayerSpec(name="one", character="Juniper", system_prompt=SYSTEM_PROMPT)
    backend = _Backend("Juniper", accepted=False)
    agent = _RecordingAgent(
        (
            InvalidAgentResponse("invalid", "retry"),
            ToolCall("move", {"direction": "north"}),
        )
    )
    harness = MultiplayerHarness(
        _config((spec,)),
        agent_factory=lambda *_args: agent,
        backend_factory=lambda *_args: backend,
    )

    result = await harness.run()

    assert result.players[0].status == "turn_limit"
    assert result.players[0].turns[0].reason == "invalid"
    assert result.players[0].turns[1].reason == "blocked"
    output = result.write_json(tmp_path / "result.json")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run_id"] == result.run_id
    assert payload["players"][0]["status"] == "turn_limit"
    assert payload["players"][0]["turns"][0]["system_prompt"] == SYSTEM_PROMPT
    assert "controlling Juniper" in payload["players"][0]["turns"][0]["prompt"]
    assert result.completed_players == 0
    assert "secret" not in output.read_text(encoding="utf-8")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


async def test_admin_trace_attributes_exact_provider_exchange_and_flushes_ndjson(tmp_path):
    spec = PlayerSpec(name="operator-visible", character="Juniper", system_prompt=SYSTEM_PROMPT)
    records: list[AdminTraceRecord] = []
    writer = NdjsonAdminTraceWriter(tmp_path / "admin.trace.ndjson")

    def trace_sink(record):
        records.append(record)
        writer(record)

    def agent_factory(
        player, provider, model, config, request_observer, response_observer
    ):
        del player, provider, model, config
        return _RecordingAgent(
            (ToolCall("move", {"direction": "north"}),),
            request_observer,
            response_observer,
        )

    result = await MultiplayerHarness(
        _config((spec,), turns=1),
        agent_factory=agent_factory,
        backend_factory=lambda *_args: _Backend("Juniper"),
        admin_trace_sink=trace_sink,
    ).run()

    assert len(records) == 1
    record = records[0]
    assert record.sensitive is True
    assert record.run_id == result.run_id
    assert record.player_name == "operator-visible"
    assert record.character_id == "id-Juniper"
    assert record.character_name == "Juniper"
    assert record.turn.system_prompt == SYSTEM_PROMPT
    assert record.turn.provider_requests[0]["messages"][0]["content"].startswith(
        "You are player operator-visible"
    )
    assert record.turn.provider_responses == (
        {"message": {"role": "assistant", "content": ""}},
    )
    lines = (tmp_path / "admin.trace.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert stat.S_IMODE((tmp_path / "admin.trace.ndjson").stat().st_mode) == 0o600
    persisted = json.loads(lines[0])
    assert persisted["character_name"] == "Juniper"
    assert persisted["turn"]["tool"] == "move"


async def test_harness_records_hold_unknown_tool_and_final_completion():
    spec = PlayerSpec(name="one", character="Juniper", system_prompt=SYSTEM_PROMPT)
    backend = _Backend("Juniper")
    agent = _RecordingAgent((None, ToolCall("missing", {})))
    result = await MultiplayerHarness(
        _config((spec,)),
        agent_factory=lambda *_args: agent,
        backend_factory=lambda *_args: backend,
        completion_probe=lambda projection: projection.world_epoch >= 3,
    ).run()

    player = result.players[0]
    assert player.status == "completed"
    assert [turn.reason for turn in player.turns] == [
        "agent held",
        "tool is not currently available",
    ]
    assert backend.submissions == []


async def test_harness_reports_timeout_missing_character_and_projection():
    spec = PlayerSpec(name="one", character="Juniper", system_prompt=SYSTEM_PROMPT)

    class _SlowBackend(_Backend):
        async def start(self):
            await asyncio.sleep(1)

    slow = _SlowBackend("Juniper")
    timeout = await MultiplayerHarness(
        _config((spec,), timeout_seconds=0.001),
        agent_factory=lambda *_args: _RecordingAgent((None,)),
        backend_factory=lambda *_args: slow,
    ).run()
    assert timeout.players[0].status == "timeout"

    missing = _Backend("Other")
    unavailable = await MultiplayerHarness(
        _config((spec,)),
        agent_factory=lambda *_args: _RecordingAgent((None,)),
        backend_factory=lambda *_args: missing,
    ).run()
    assert unavailable.players[0].status == "failed"
    assert "not uniquely available" in unavailable.players[0].error

    class _MissingProjectionBackend(_Backend):
        async def fetch_character_projection(self, character_id):
            del character_id
            return None

    no_projection = _MissingProjectionBackend("Juniper")
    lost = await MultiplayerHarness(
        _config((spec,)),
        agent_factory=lambda *_args: _RecordingAgent((None,)),
        backend_factory=lambda *_args: no_projection,
    ).run()
    assert lost.players[0].status == "failed"
    assert "no longer exists" in lost.players[0].error


async def test_harness_ignores_cleanup_errors():
    class _CleanupBackend(_Backend):
        async def release_claim(self, player_id, control):
            del player_id, control
            raise OSError("release failed")

        async def close(self):
            raise OSError("close failed")

    class _CleanupAgent(_RecordingAgent):
        async def close(self):
            raise OSError("agent close failed")

    spec = PlayerSpec(name="one", character="Juniper", system_prompt=SYSTEM_PROMPT)
    result = await MultiplayerHarness(
        _config((spec,), turns=1),
        agent_factory=lambda *_args: _CleanupAgent((None,)),
        backend_factory=lambda *_args: _CleanupBackend("Juniper"),
    ).run()
    assert result.players[0].status == "turn_limit"


async def test_harness_honors_turn_interval_and_agent_without_close(monkeypatch):
    class _HoldAgent:
        async def decide(self, *_args, **_kwargs):
            return None

    sleeps: list[float] = []

    async def record_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)
    spec = PlayerSpec(name="one", character="Juniper", system_prompt=SYSTEM_PROMPT)
    result = await MultiplayerHarness(
        _config((spec,), turns=1, turn_interval_seconds=0.25),
        agent_factory=lambda *_args: _HoldAgent(),
        backend_factory=lambda *_args: _Backend("Juniper"),
    ).run()

    assert result.players[0].status == "turn_limit"
    assert sleeps == [0.25]


async def test_harness_reports_claim_failure_and_closes_resources():
    class _NoClaimBackend(_Backend):
        async def claim(self, player_id, world):
            del player_id, world
            return None

    spec = PlayerSpec(name="one", character="Juniper", system_prompt=SYSTEM_PROMPT)
    backend = _NoClaimBackend("Juniper")
    agent = _RecordingAgent((None,))
    result = await MultiplayerHarness(
        _config((spec,)),
        agent_factory=lambda *_args: agent,
        backend_factory=lambda *_args: backend,
    ).run()

    assert result.players[0].status == "failed"
    assert "could not claim" in result.players[0].error
    assert backend.closed is True
    assert agent.closed is True


def test_tool_schema_enumerates_visible_targets_and_directions():
    action = ClientActionView(
        command_type="move",
        tool_name="move",
        title="Move",
        cost=CommandCostRequest(action=1),
        arguments=[
            ClientActionArgumentView(key="direction"),
            ClientActionArgumentView(key="exit_id", kind="entity", target_group="exits"),
        ],
    )
    groups = {"exits": [ClientTargetView(id="room-2", label="north: Orchard", kind="exit")]}

    schema = _tool_schema(action, groups)
    properties = schema["function"]["parameters"]["properties"]

    assert properties["direction"]["enum"] == ["north"]
    assert properties["exit_id"]["enum"] == ["room-2"]
    assert _command_payload(ToolCall("move", {"exit_id": "room-2"}), action, groups) == {
        "exit_id": "room-2",
        "direction": "north",
    }

    required = ClientActionView(
        command_type="measure",
        tool_name="measure",
        title="Measure",
        arguments=[
            ClientActionArgumentView(key="amount", title="Amount", kind="number", required=True),
            ClientActionArgumentView(key="confirm", kind="boolean"),
        ],
    )
    required_schema = _tool_schema(required, {})["function"]["parameters"]
    assert required_schema["properties"]["amount"] == {
        "type": "number",
        "title": "Amount",
    }
    assert required_schema["properties"]["confirm"] == {"type": "boolean"}
    assert required_schema["required"] == ["amount"]

    with pytest.raises(MultiplayerHarnessError, match="invalid tool arguments"):
        _json_arguments({"bad": object()})

    no_exits = _tool_schema(action, {})["function"]["parameters"]["properties"]
    assert "enum" not in no_exits["direction"]
    assert _command_payload(
        ToolCall("move", {"exit_id": "missing"}), action, groups
    ) == {"exit_id": "missing"}
    assert _command_payload(ToolCall("move", {"direction": "north"}), action, groups) == {
        "direction": "north"
    }
    assert _command_payload(ToolCall("measure", {"amount": 2}), required, {}) == {
        "amount": 2
    }


def test_player_prompt_includes_isolated_harness_memory():
    spec = PlayerSpec(name="one", character="Juniper", system_prompt=SYSTEM_PROMPT)
    backend = _Backend("Juniper")
    agent = _RecordingAgent((None,))
    harness = MultiplayerHarness(
        _config((spec,)),
        agent_factory=lambda *_args: agent,
        backend_factory=lambda *_args: backend,
    )
    runtime = harness._runtime(spec)
    runtime.character_name = "Juniper"
    runtime.memory["recent_results"] = ["Turn 1: move was accepted.", 7]
    from bunnyland.server.models import CharacterProjectionResponse

    prompt, context = _player_prompt(
        runtime,
        CharacterProjectionResponse.model_validate(_projection("id-Juniper", "Juniper", 2)),
    )
    assert "Visible characters: Neighbor" in prompt
    assert "Visible objects: red apple" in prompt
    assert context.recent == ("Turn 1: move was accepted.",)


def test_projection_fixture_uses_player_contract_types():
    room = ClientRoomView(
        id="room-1",
        title="Shared Green",
        entities=[ClientEntityView(id="friend", name="Neighbor", is_character=True)],
        exits=[ClientExitView(id="room-2", direction="north", label="north: Orchard")],
    )
    points = ClientPointsView(action=5, action_max=5, focus=3, focus_max=3)

    assert room.entities[0].is_character is True
    assert points.action == 5
