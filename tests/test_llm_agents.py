"""Tests for the LLM tool surface, scripted agent, and controller dispatch."""

from __future__ import annotations

import sys
import types

import pytest
from conftest import build_scenario

from bunnyland.core import (
    ActionArgument,
    ActionDefinition,
    ActionPattern,
    CommandCost,
    ContainerComponent,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    PortableComponent,
    TakeHandler,
    container_of,
    spawn_entity,
)
from bunnyland.llm_agents import (
    ControllerDispatch,
    OpenRouterAgent,
    ProviderRouterAgent,
    ScriptedAgent,
    ToolCall,
    command_from_tool_call,
    did_you_mean,
    name_candidates,
    parse_natural_command,
    resolve_reference,
    resolve_reference_args,
    suggest_names,
    tool_names,
    tool_schemas,
)
from bunnyland.llm_agents.agent import (
    DEFAULT_MODEL,
    OllamaAgent,
    _call_provider_with_retries,
    normalize_model,
)
from bunnyland.prompts.builder import PromptBuilder


def _add_item(scenario, name, *, container=False):
    world = scenario.actor.world
    components = [IdentityComponent(name=name, kind="item"), PortableComponent(can_pick_up=True)]
    if container:
        components.append(ContainerComponent(open=True))
    entity = spawn_entity(world, components)
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


def test_tool_schemas_cover_every_verb():
    names = {s["function"]["name"] for s in tool_schemas()}
    assert names == set(tool_names())
    assert {
        "move",
        "say",
        "take",
        "adopt_child",
        "accept_quest",
        "buy_item",
        "charge_rent",
        "claim_home",
        "claim_ownership",
        "claim_room",
        "complete_objective",
        "create_spell",
        "cast_spell",
        "discover_location",
        "drop",
        "enchant_item",
        "fertilize",
        "harvest_crop",
        "join_household",
        "plant",
        "pickpocket",
        "join_faction",
        "leave_faction",
        "release_ownership",
        "open_business",
        "pay_bill",
        "sell_item",
        "take_note",
        "till",
        "water_crop",
        "remember",
        "forget",
        "reflect",
        "wait",
    } <= names


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


def test_custom_action_definition_drives_tool_schema_and_command_mapping():
    definition = ActionDefinition(
        command_type="wave",
        tool_name="wave",
        description="Wave to a reachable character.",
        arguments={
            "target_id": ActionArgument(
                description="The character to wave at.",
                kind="entity",
                required=True,
            )
        },
    )

    schema = next(
        item["function"]
        for item in tool_schemas((definition,))
        if item["function"]["name"] == "wave"
    )
    command = command_from_tool_call(
        ToolCall("wave", {"target_id": "char_1", "bogus": "ignored"}),
        character_id="char_2",
        controller_id="ctrl_1",
        controller_generation=0,
        definitions=(definition,),
    )

    assert schema["description"] == "Wave to a reachable character."
    assert schema["parameters"]["required"] == ["target_id"]
    assert command.command_type == "wave"
    assert command.payload == {"target_id": "char_1"}


def test_note_tools_accept_shared_collection_arguments():
    call = ToolCall(
        name="take_note",
        arguments={"text": "shared", "scope": "shared", "collection": "burrow-board"},
    )
    command = command_from_tool_call(
        call, character_id="char_1", controller_id="ctrl_1", controller_generation=0
    )
    assert command.payload == {
        "text": "shared",
        "scope": "shared",
        "collection": "burrow-board",
    }


def test_parse_natural_command_maps_common_phrases_to_tool_calls():
    assert parse_natural_command("go north") == ToolCall("move", {"direction": "north"})
    assert parse_natural_command("take the brass key") == ToolCall(
        "take", {"item_id": "the brass key"}
    )
    assert parse_natural_command('say "hello there"') == ToolCall("say", {"text": "hello there"})
    assert parse_natural_command("tell Hazel meet me outside") == ToolCall(
        "tell", {"target_id": "Hazel", "text": "meet me outside"}
    )
    assert parse_natural_command("pickpocket Hazel brass key") == ToolCall(
        "pickpocket", {"target_id": "Hazel", "item_id": "brass key"}
    )
    assert parse_natural_command("buy radish seeds from Marigold") == ToolCall(
        "buy_item", {"item_id": "radish seeds", "seller_id": "Marigold"}
    )
    assert parse_natural_command("sell radish x2 to Marigold") == ToolCall(
        "sell_item", {"item_id": "radish x2", "customer_id": "Marigold"}
    )
    assert parse_natural_command("open business Hazel's Farm Stand") == ToolCall(
        "open_business", {"name": "Hazel's Farm Stand"}
    )
    assert parse_natural_command("adopt Clover") == ToolCall("adopt_child", {"child_id": "Clover"})
    assert parse_natural_command("claim oak chest") == ToolCall(
        "claim_ownership", {"target_id": "oak chest"}
    )
    assert parse_natural_command("till garden bed") == ToolCall("till", {"soil_id": "garden bed"})
    assert parse_natural_command("plant turnip seeds in garden bed") == ToolCall(
        "plant", {"seed_id": "turnip seeds", "soil_id": "garden bed"}
    )
    assert parse_natural_command("water garden bed") == ToolCall(
        "water_crop", {"soil_id": "garden bed"}
    )
    assert parse_natural_command("harvest garden bed") == ToolCall(
        "harvest_crop", {"soil_id": "garden bed"}
    )
    assert parse_natural_command("discover old watchtower") == ToolCall(
        "discover_location", {"location_id": "old watchtower"}
    )
    assert parse_natural_command("accept quest lost ring") == ToolCall(
        "accept_quest", {"quest_id": "lost ring"}
    )
    assert parse_natural_command("complete objective find the ring") == ToolCall(
        "complete_objective", {"objective_id": "find the ring"}
    )
    assert parse_natural_command("join faction Moss Wardens") == ToolCall(
        "join_faction", {"faction_id": "Moss Wardens"}
    )
    assert parse_natural_command("join household moss-burrow") == ToolCall(
        "join_household", {"household_id": "moss-burrow", "name": "moss-burrow"}
    )
    assert parse_natural_command("leave faction Moss Wardens") == ToolCall(
        "leave_faction", {"faction_id": "Moss Wardens"}
    )
    assert parse_natural_command("claim home North Tunnel") == ToolCall(
        "claim_home", {"room_id": "North Tunnel"}
    )
    assert parse_natural_command("claim room North Tunnel") == ToolCall(
        "claim_room", {"room_id": "North Tunnel"}
    )
    assert parse_natural_command("release ownership oak chest") == ToolCall(
        "release_ownership", {"target_id": "oak chest"}
    )
    assert parse_natural_command("charge rent Hazel 12") == ToolCall(
        "charge_rent", {"tenant_id": "Hazel", "amount": "12"}
    )
    assert parse_natural_command("pay bill") == ToolCall("pay_bill", {})
    assert parse_natural_command("pay bill bill-123") == ToolCall(
        "pay_bill", {"bill_id": "bill-123"}
    )
    assert parse_natural_command("enchant moss charm with Mend Moss") == ToolCall(
        "enchant_item", {"item_id": "moss charm", "spell_id": "Mend Moss"}
    )
    assert parse_natural_command("cast moss charm on Juniper") == ToolCall(
        "cast_spell", {"spell_id": "moss charm", "target_id": "Juniper"}
    )
    assert parse_natural_command("take note the basin is cold") == ToolCall(
        "take_note", {"text": "the basin is cold"}
    )
    assert parse_natural_command("reflect on the basin") == ToolCall(
        "reflect", {"text": "on the basin"}
    )
    assert parse_natural_command("forget note-123") == ToolCall("forget", {"note_id": "note-123"})
    assert parse_natural_command("wait") == ToolCall("wait", {})


def test_parse_natural_command_returns_none_for_ambiguous_text():
    assert parse_natural_command("") is None
    assert parse_natural_command("maybe Hazel knows") is None


def test_parse_natural_command_uses_action_definition_patterns():
    definition = ActionDefinition(
        command_type="wave",
        tool_name="wave",
        arguments={"target_id": ActionArgument(kind="entity")},
        natural_patterns=(ActionPattern("wave to {target_id}"),),
    )

    assert parse_natural_command("wave to Hazel", (definition,)) == ToolCall(
        "wave", {"target_id": "Hazel"}
    )


def test_parse_natural_command_rejects_adjacent_pattern_slots():
    definition = ActionDefinition(
        command_type="give",
        tool_name="give",
        arguments={
            "item_id": ActionArgument(kind="entity"),
            "target_id": ActionArgument(kind="entity"),
        },
        natural_patterns=(ActionPattern("give {item_id} {target_id}"),),
    )

    assert parse_natural_command("give carrot Hazel", (definition,)) is None


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


async def test_dispatch_throttles_controller_by_act_every_ticks():
    from dataclasses import replace

    from bunnyland.core import replace_component
    from bunnyland.core.controllers import LLMControllerComponent

    scenario = build_scenario()
    builder = PromptBuilder(scenario.actor.world)
    controller = scenario.actor.world.get_entity(scenario.controller)
    replace_component(
        controller,
        replace(controller.get_component(LLMControllerComponent), act_every_ticks=2),
    )
    agent = ScriptedAgent([ToolCall("move", {"direction": "north"})])
    dispatch = ControllerDispatch(scenario.actor, builder, agent)

    # Tick 1 is skipped (1 % 2 != 0); tick 2 is the controller's turn.
    assert await dispatch.run_once() == []
    second = await dispatch.run_once()
    assert [decision.tool for decision in second] == ["move"]


class _FakeOllamaClient:
    """Records the messages sent on each chat call and replies with a fixed tool call."""

    def __init__(self, *args, **kwargs):
        self.calls: list[list[dict]] = []
        self.models: list[str] = []

    async def chat(self, *, model, messages, tools):
        del tools
        self.models.append(model)
        self.calls.append([dict(m) for m in messages])  # snapshot
        return {
            "message": {
                "role": "assistant",
                "content": "ok",
                "tool_calls": [{"function": {"name": "wait", "arguments": {}}}],
            }
        }


class _FakeProviderError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider failed with status code: {status_code}")
        self.status_code = status_code


class _FakeResponseProviderError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider response failed with status code: {status_code}")
        self.response = types.SimpleNamespace(status_code=status_code)


@pytest.mark.parametrize(
    "exc",
    [
        _FakeProviderError(429),
        _FakeProviderError(502),
        _FakeResponseProviderError(503),
        _FakeResponseProviderError(504),
        TimeoutError("provider timed out"),
        ConnectionError("provider connection reset"),
        OSError("provider network unreachable"),
    ],
)
async def test_provider_retry_helper_retries_intermittent_network_errors(exc):
    attempts = 0

    async def request():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise exc
        return "ok"

    result = await _call_provider_with_retries(
        "test-provider", request, max_retries=2, retry_delay_seconds=0
    )

    assert result == "ok"
    assert attempts == 2


@pytest.mark.parametrize(
    "exc",
    [
        _FakeProviderError(400),
        _FakeResponseProviderError(403),
        ValueError("malformed provider response"),
    ],
)
async def test_provider_retry_helper_does_not_retry_non_transient_errors(exc):
    attempts = 0

    async def request():
        nonlocal attempts
        attempts += 1
        raise exc

    with pytest.raises(type(exc)):
        await _call_provider_with_retries(
            "test-provider", request, max_retries=2, retry_delay_seconds=0
        )

    assert attempts == 1


def _fake_ollama_response():
    return {
        "message": {
            "role": "assistant",
            "content": "ok",
            "tool_calls": [{"function": {"name": "wait", "arguments": {}}}],
        }
    }


class _FlakyOllamaClient(_FakeOllamaClient):
    failures = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.remaining_failures = self.failures

    async def chat(self, *, model, messages, tools):
        self.models.append(model)
        self.calls.append([dict(m) for m in messages])
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise _FakeProviderError(502)
        return _fake_ollama_response()


async def test_ollama_agent_resends_prior_turns_as_context(monkeypatch):
    fake_module = types.ModuleType("ollama")
    fake_module.AsyncClient = _FakeOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaAgent(model="llama3")
    await agent.decide("turn one", None, character_id="char_1")
    await agent.decide("turn two", None, character_id="char_1")

    client = agent._client
    # Second chat call carries the full history: turn one (user + assistant) + turn two.
    second = client.calls[1]
    assert second[0] == {"role": "user", "content": "turn one"}
    assert second[1]["role"] == "assistant"
    assert second[2] == {"role": "user", "content": "turn two"}


async def test_ollama_agent_keeps_history_per_character(monkeypatch):
    fake_module = types.ModuleType("ollama")
    fake_module.AsyncClient = _FakeOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaAgent(model="llama3")
    await agent.decide("hazel turn", None, character_id="hazel")
    await agent.decide("juniper turn", None, character_id="juniper")

    # Juniper's first call must not contain Hazel's history.
    juniper_call = agent._client.calls[1]
    assert juniper_call == [{"role": "user", "content": "juniper turn"}]


async def test_ollama_agent_can_override_model_per_decision(monkeypatch):
    fake_module = types.ModuleType("ollama")
    fake_module.AsyncClient = _FakeOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaAgent(model="fallback")
    await agent.decide("turn one", None, character_id="hazel", model="controller-model")

    assert agent._client.models == ["controller-model"]


async def test_ollama_agent_maps_legacy_default_model_to_flash(monkeypatch):
    fake_module = types.ModuleType("ollama")
    fake_module.AsyncClient = _FakeOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaAgent(model="fallback")
    await agent.decide("turn one", None, character_id="hazel", model="llama3")

    assert normalize_model("llama3") == DEFAULT_MODEL
    assert agent._client.models == [DEFAULT_MODEL]


async def test_ollama_agent_retries_transient_provider_errors(monkeypatch):
    fake_module = types.ModuleType("ollama")
    fake_module.AsyncClient = _FlakyOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaAgent(model="llama3", retry_delay_seconds=0)
    call = await agent.decide("turn one", None, character_id="hazel")

    assert call == ToolCall("wait", {})
    assert len(agent._client.calls) == 2
    assert agent._history["hazel"][0] == {"role": "user", "content": "turn one"}


async def test_ollama_agent_returns_wait_after_transient_provider_retries(monkeypatch):
    class AlwaysFailOllamaClient(_FlakyOllamaClient):
        failures = 99

    fake_module = types.ModuleType("ollama")
    fake_module.AsyncClient = AlwaysFailOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaAgent(model="llama3", retry_delay_seconds=0)
    call = await agent.decide("turn one", None, character_id="hazel")

    assert call is None
    assert len(agent._client.calls) == 3
    assert agent._history["hazel"] == []


class _FakeOpenRouterChat:
    def __init__(self):
        self.calls: list[dict] = []

    async def send_async(self, *, model, messages, tools):
        del tools
        self.calls.append({"model": model, "messages": [dict(m) for m in messages]})
        function = types.SimpleNamespace(name="wait", arguments='{"reason": "rest"}')
        tool_call = types.SimpleNamespace(function=function)
        message = types.SimpleNamespace(
            role="assistant",
            content="ok",
            tool_calls=[tool_call],
            model_dump=lambda **_: {
                "role": "assistant",
                "content": "ok",
                "tool_calls": [{"function": {"name": "wait", "arguments": '{"reason": "rest"}'}}],
            },
        )
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class _FakeOpenRouterClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = _FakeOpenRouterChat()


class _FlakyOpenRouterChat(_FakeOpenRouterChat):
    failures = 1

    def __init__(self):
        super().__init__()
        self.remaining_failures = self.failures

    async def send_async(self, *, model, messages, tools):
        self.calls.append({"model": model, "messages": [dict(m) for m in messages]})
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise _FakeProviderError(502)
        function = types.SimpleNamespace(name="wait", arguments='{"reason": "rest"}')
        tool_call = types.SimpleNamespace(function=function)
        message = types.SimpleNamespace(
            role="assistant",
            content="ok",
            tool_calls=[tool_call],
            model_dump=lambda **_: {
                "role": "assistant",
                "content": "ok",
                "tool_calls": [{"function": {"name": "wait", "arguments": '{"reason": "rest"}'}}],
            },
        )
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class _FlakyOpenRouterClient(_FakeOpenRouterClient):
    chat_type = _FlakyOpenRouterChat

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = self.chat_type()


async def test_openrouter_agent_parses_tool_arguments_json(monkeypatch):
    fake_module = types.ModuleType("openrouter")
    fake_module.OpenRouter = _FakeOpenRouterClient
    monkeypatch.setitem(sys.modules, "openrouter", fake_module)

    agent = OpenRouterAgent(model="openai/gpt-4.1-mini", api_key="key")
    call = await agent.decide("turn one", None, character_id="hazel")

    assert call == ToolCall("wait", {"reason": "rest"})
    assert agent._client.kwargs == {"api_key": "key"}
    assert agent._client.chat.calls[0]["model"] == "openai/gpt-4.1-mini"


async def test_openrouter_agent_resends_prior_turns_as_context(monkeypatch):
    fake_module = types.ModuleType("openrouter")
    fake_module.OpenRouter = _FakeOpenRouterClient
    monkeypatch.setitem(sys.modules, "openrouter", fake_module)

    agent = OpenRouterAgent(model="openai/gpt-4.1-mini", api_key="key")
    await agent.decide("turn one", None, character_id="hazel")
    await agent.decide("turn two", None, character_id="hazel")

    second = agent._client.chat.calls[1]["messages"]
    assert second[0] == {"role": "user", "content": "turn one"}
    assert second[1]["role"] == "assistant"
    assert second[2] == {"role": "user", "content": "turn two"}


async def test_openrouter_agent_retries_transient_provider_errors(monkeypatch):
    fake_module = types.ModuleType("openrouter")
    fake_module.OpenRouter = _FlakyOpenRouterClient
    monkeypatch.setitem(sys.modules, "openrouter", fake_module)

    agent = OpenRouterAgent(model="openai/gpt-4.1-mini", api_key="key", retry_delay_seconds=0)
    call = await agent.decide("turn one", None, character_id="hazel")

    assert call == ToolCall("wait", {"reason": "rest"})
    assert len(agent._client.chat.calls) == 2
    assert agent._history["hazel"][0] == {"role": "user", "content": "turn one"}


async def test_openrouter_agent_returns_wait_after_transient_provider_retries(monkeypatch):
    class AlwaysFailOpenRouterChat(_FlakyOpenRouterChat):
        failures = 99

    class AlwaysFailOpenRouterClient(_FlakyOpenRouterClient):
        chat_type = AlwaysFailOpenRouterChat

    fake_module = types.ModuleType("openrouter")
    fake_module.OpenRouter = AlwaysFailOpenRouterClient
    monkeypatch.setitem(sys.modules, "openrouter", fake_module)

    agent = OpenRouterAgent(model="openai/gpt-4.1-mini", api_key="key", retry_delay_seconds=0)
    call = await agent.decide("turn one", None, character_id="hazel")

    assert call is None
    assert len(agent._client.chat.calls) == 3
    assert agent._history["hazel"] == []


async def test_dispatch_records_wait_when_agent_passes():
    scenario = build_scenario()
    builder = PromptBuilder(scenario.actor.world)
    dispatch = ControllerDispatch(scenario.actor, builder, ScriptedAgent([]))

    decisions = await dispatch.run_once()

    assert len(decisions) == 1
    assert decisions[0].tool is None
    assert scenario.actor._inbox.empty()


async def test_dispatch_uses_controller_model_for_character_decision():
    scenario = build_scenario()
    agent = _RecordingAgent([])
    dispatch = ControllerDispatch(scenario.actor, PromptBuilder(scenario.actor.world), agent)

    await dispatch.run_once()

    assert agent.models == ["claude"]


async def test_dispatch_uses_controller_provider_for_character_decision():
    from dataclasses import replace

    from bunnyland.core import replace_component
    from bunnyland.core.controllers import LLMControllerComponent

    scenario = build_scenario()
    controller = scenario.actor.world.get_entity(scenario.controller)
    replace_component(
        controller,
        replace(controller.get_component(LLMControllerComponent), provider="openrouter"),
    )
    agent = _RecordingAgent([])
    dispatch = ControllerDispatch(scenario.actor, PromptBuilder(scenario.actor.world), agent)

    await dispatch.run_once()

    assert agent.providers == ["openrouter"]


async def test_provider_router_uses_selected_agent():
    ollama = _RecordingAgent([])
    openrouter = _RecordingAgent([ToolCall("wait", {})])
    router = ProviderRouterAgent({"ollama": ollama, "openrouter": openrouter})

    call = router.decide(
        "prompt",
        None,
        character_id="hazel",
        model="openai/gpt-4.1-mini",
        provider="openrouter",
    )

    assert call == ToolCall("wait", {})
    assert ollama.prompts == []
    assert openrouter.models == ["openai/gpt-4.1-mini"]


def test_resolve_reference_matches_names_case_insensitively():
    scenario = build_scenario()
    world = scenario.actor.world
    journal = _add_item(scenario, "marsh journal")
    basket = _add_item(scenario, "woven basket", container=True)
    character = world.get_entity(scenario.character)
    candidates = name_candidates(world, character)

    # prefix match: "Mar" -> "marsh journal"
    assert resolve_reference("Mar", candidates, world=world) == str(journal)
    # exact, case-insensitive
    assert resolve_reference("WOVEN BASKET", candidates, world=world) == str(basket)
    # adjacent room resolved by title ("North Tunnel")
    assert resolve_reference("North", candidates, world=world) == str(scenario.room_b)
    # an already-valid id passes through untouched
    assert resolve_reference(str(journal), candidates, world=world) == str(journal)
    # no match -> returned unchanged so the handler rejects it observably
    assert resolve_reference("dragon", candidates, world=world) == "dragon"


def test_resolve_reference_args_reports_unresolved_with_suggestions():
    scenario = build_scenario()
    world = scenario.actor.world
    journal = _add_item(scenario, "marsh journal")
    _add_item(scenario, "woven basket", container=True)
    character = world.get_entity(scenario.character)

    resolved, unresolved = resolve_reference_args(
        world, character, {"item_id": "Mar", "target_container_id": "basket"}
    )
    # "Mar" resolves to the journal id; "basket" does not prefix-match anything.
    assert resolved["item_id"] == str(journal)
    assert "item_id" not in unresolved
    assert "woven basket" in unresolved["target_container_id"]


def test_suggest_names_prefers_substring_then_fuzzy():
    candidates = [("woven basket", None), ("marsh journal", None)]
    assert suggest_names("basket", candidates) == ["woven basket"]  # substring
    assert "woven basket" in suggest_names("woven baskt", candidates)  # fuzzy typo
    assert suggest_names("dragon", candidates) == []  # nothing nearby


def test_did_you_mean_message():
    msg = did_you_mean({"item_id": "baskt"}, {"item_id": ["woven basket"]})
    assert "did you mean" in msg.lower() and "woven basket" in msg
    empty = did_you_mean({"target_id": "ghost"}, {"target_id": []})
    assert "nothing" in empty.lower()


class _RecordingAgent:
    """Records the prompts it is shown and replays a fixed list of calls."""

    def __init__(self, calls):
        self.calls = list(calls)
        self.prompts: list[str] = []
        self.models: list[str | None] = []
        self.providers: list[str | None] = []
        self.tools: list[list[dict] | None] = []
        self._index = 0

    def decide(self, prompt, context, *, character_id, model=None, provider=None, tools=None):
        self.prompts.append(prompt)
        self.models.append(model)
        self.providers.append(provider)
        self.tools.append(tools)
        if self._index >= len(self.calls):
            return None
        call = self.calls[self._index]
        self._index += 1
        return call


async def test_dispatch_feeds_did_you_mean_back_to_the_agent():
    # An LLM agent that names something unreachable gets the same guidance a human would,
    # surfaced as a warning on its next prompt — and the doomed command is never submitted.
    scenario = build_scenario()
    _add_item(scenario, "woven basket", container=True)
    agent = _RecordingAgent([ToolCall("take", {"item_id": "basket"}), None])
    dispatch = ControllerDispatch(scenario.actor, PromptBuilder(scenario.actor.world), agent)

    first = await dispatch.run_once()
    assert first[0].tool == "take"
    assert "did you mean" in first[0].summary.lower()
    assert scenario.actor._inbox.empty()  # nothing submitted

    await dispatch.run_once()  # second turn carries the feedback as a prompt warning
    assert "woven basket" in agent.prompts[1]


async def test_dispatch_resolves_item_names_to_ids_before_submitting():
    scenario = build_scenario()
    scenario.actor.register_handler(TakeHandler())
    world = scenario.actor.world
    journal = _add_item(scenario, "marsh journal")

    builder = PromptBuilder(world)
    agent = ScriptedAgent([ToolCall("take", {"item_id": "Mar"})])
    dispatch = ControllerDispatch(scenario.actor, builder, agent)

    await dispatch.run_once()
    await scenario.actor.tick(3600.0)

    # "Mar" resolved to the journal, which is now in the character's inventory.
    assert container_of(world.get_entity(journal)) == scenario.character


async def test_dispatch_rejects_unknown_agent_tools_without_crashing():
    scenario = build_scenario()
    agent = _RecordingAgent([ToolCall("read", {}), None])
    dispatch = ControllerDispatch(scenario.actor, PromptBuilder(scenario.actor.world), agent)

    first = await dispatch.run_once()

    assert first[0].tool == "read"
    assert "unknown tool" in first[0].summary
    assert scenario.actor._inbox.empty()

    await dispatch.run_once()
    assert "Choose one of the available tools exactly as named" in agent.prompts[1]
