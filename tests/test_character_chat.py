from __future__ import annotations

import asyncio

import pytest
from conftest import build_scenario

from bunnyland.core import (
    ActionDefinition,
    ContainmentMode,
    Contains,
    IdentityComponent,
    MemoryProfileComponent,
    PortableComponent,
    WebControllerComponent,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.llm_agents.agent import ChatAgentReply
from bunnyland.llm_agents.tools import ToolCall
from bunnyland.mechanics.persona import (
    GoalComponent,
    PersonaProfileComponent,
    PreferenceComponent,
    TraitSetComponent,
)
from bunnyland.memory import InMemoryStore, install_memory
from bunnyland.plugins import apply_plugins, collect_persona_fragments
from bunnyland.plugins.builtin import CORE_VERBS, bunnyland_plugins
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.server import character_chat as character_chat_module
from bunnyland.server.app import create_app
from bunnyland.server.character_chat import (
    ALLOWED_CHAT_TOOLS,
    CharacterChatService,
    build_character_chat_service,
)
from bunnyland.server.models import CharacterChatRequest


class FakeChatAgent:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def chat(self, messages, *, character_id, model=None, provider=None, tools=None):
        self.calls.append(
            {
                "messages": messages,
                "character_id": character_id,
                "model": model,
                "provider": provider,
                "tools": tools or [],
            }
        )
        if not self.replies:
            return ChatAgentReply(content="done")
        return self.replies.pop(0)


class SyncChatAgent:
    def chat(self, messages, *, character_id, model=None, provider=None, tools=None):
        del messages, character_id, model, provider, tools
        return ChatAgentReply(content="sync reply")


def install_core(actor):
    apply_plugins([plugin for plugin in bunnyland_plugins() if plugin.id == CORE_VERBS], actor)


def chat_request(message="hello") -> CharacterChatRequest:
    return CharacterChatRequest(client_id="test-client", message=message)


def chat_service(scenario, agent, *, timeout=0.01) -> CharacterChatService:
    return CharacterChatService(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        agent,
        result_timeout_seconds=timeout,
    )


@pytest.mark.asyncio
async def test_character_chat_no_tool_reply_does_not_submit_command():
    scenario = build_scenario()
    install_core(scenario.actor)
    agent = FakeChatAgent([ChatAgentReply(content="I hear you.")])
    service = chat_service(scenario, agent)

    response = await service.chat(str(scenario.character), chat_request("look"))

    assert response.reply == "I hear you."
    assert response.action.status == "none"
    assert scenario.actor.pending_submissions() == []
    system_prompt = agent.calls[0]["messages"][0]["content"]
    assert "call that tool instead of merely describing the action" in system_prompt
    assert "prefer take_note" in system_prompt
    tool_names = {
        tool["function"]["name"]
        for tool in agent.calls[0]["tools"]
        if tool.get("type") == "function"
    }
    assert tool_names == ALLOWED_CHAT_TOOLS
    assert "move" not in tool_names


@pytest.mark.asyncio
async def test_character_chat_builds_prompt_with_history_and_summary():
    scenario = build_scenario()
    install_core(scenario.actor)
    agent = FakeChatAgent([ChatAgentReply(content="I remember.")])
    service = chat_service(scenario, agent)

    response = await service.chat(
        str(scenario.character),
        CharacterChatRequest(
            client_id="test-client",
            message="what now?",
            history_summary="We talked about tunnels.",
            history=[
                {"role": "user", "text": "hello"},
                {"role": "character", "text": "quietly, hello"},
            ],
        ),
    )

    assert response.reply == "I remember."
    prompt = agent.calls[0]["messages"][1]["content"]
    assert "We talked about tunnels." in prompt
    assert "Human: hello" in prompt
    assert "Character: quietly, hello" in prompt


@pytest.mark.asyncio
async def test_character_chat_initial_prompt_includes_game_context_and_conversation():
    scenario = build_scenario()
    install_core(scenario.actor)
    compass = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="silver compass", kind="item"), PortableComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), compass.id
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(PersonaProfileComponent(voice="quiet and precise", role="scout"))
    character.add_component(TraitSetComponent(traits=("observant",)))
    character.add_component(PreferenceComponent(likes=("clear landmarks",)))
    character.add_component(GoalComponent(active_goals=("map the moss tunnels",)))
    agent = FakeChatAgent([ChatAgentReply(content="I see it.")])
    service = CharacterChatService(
        scenario.actor,
        PromptBuilder(
            scenario.actor.world,
            persona_providers=collect_persona_fragments(bunnyland_plugins()),
        ),
        agent,
    )

    await service.chat(str(scenario.character), chat_request("what do you notice?"))

    system = agent.calls[0]["messages"][0]["content"]
    prompt = agent.calls[0]["messages"][1]["content"]
    assert "speaking as the Bunnyland character" in system
    assert "conversation or a suggestion" in system
    assert "Character context:" in prompt
    assert "Mosslit Burrow" in prompt
    assert "silver compass" in prompt
    assert "Your name is Juniper." in prompt
    assert "Your voice: quiet and precise." in prompt
    assert "Your current role: scout." in prompt
    assert "You are observant." in prompt
    assert "You like clear landmarks." in prompt
    assert "Your goal: map the moss tunnels." in prompt
    assert "Human now:\nwhat do you notice?" in prompt


@pytest.mark.asyncio
async def test_character_chat_supports_sync_chat_agent():
    scenario = build_scenario()
    install_core(scenario.actor)
    service = chat_service(scenario, SyncChatAgent())

    response = await service.chat(str(scenario.character), chat_request("hi"))

    assert response.reply == "sync reply"


@pytest.mark.asyncio
async def test_character_chat_rejects_missing_non_character_and_no_chat_agent():
    scenario = build_scenario()
    install_core(scenario.actor)
    service = chat_service(scenario, FakeChatAgent([ChatAgentReply(content="hi")]))

    with pytest.raises(ValueError, match="character does not exist"):
        await service.chat("not-an-id", chat_request())

    item = spawn_entity(scenario.actor.world, [IdentityComponent(name="stone", kind="item")])
    with pytest.raises(TypeError, match="entity is not a character"):
        await service.chat(str(item.id), chat_request())

    with pytest.raises(RuntimeError, match="does not support character chat"):
        await chat_service(scenario, object()).chat(str(scenario.character), chat_request())


@pytest.mark.asyncio
async def test_character_chat_look_executes_and_second_pass_gets_result_events():
    scenario = build_scenario()
    install_core(scenario.actor)
    pebble = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="pebble", kind="item"), PortableComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), pebble.id
    )
    agent = FakeChatAgent(
        [
            ChatAgentReply(tool_call=ToolCall("look", {})),
            ChatAgentReply(content="I can see the pebble."),
        ]
    )
    service = chat_service(scenario, agent, timeout=1.0)

    task = asyncio.create_task(service.chat(str(scenario.character), chat_request("what is here?")))
    await asyncio.sleep(0)
    await scenario.actor.tick(0)
    response = await task

    assert response.reply == "I can see the pebble."
    assert response.action.status == "executed"
    assert response.action.tool == "look"
    assert response.action.result_events[0]["event_type"] == "RoomLookedEvent"
    assert "pebble" in str(agent.calls[-1]["messages"])


@pytest.mark.asyncio
async def test_character_chat_action_queues_without_immediate_tick():
    scenario = build_scenario()
    install_core(scenario.actor)
    agent = FakeChatAgent([ChatAgentReply(tool_call=ToolCall("say", {"text": "soon"}))])
    service = chat_service(scenario, agent, timeout=0.0)

    response = await service.chat(str(scenario.character), chat_request("say something"))

    assert response.action.status == "queued"
    assert response.action.command_id
    assert response.reply == "I will try that when I can."


@pytest.mark.asyncio
async def test_character_chat_ignores_unrelated_command_events_while_waiting():
    scenario = build_scenario()
    install_core(scenario.actor)
    service = chat_service(scenario, FakeChatAgent([]), timeout=1.0)

    task = asyncio.create_task(
        service._submit_tool(
            scenario.character,
            str(scenario.controller),
            scenario.generation,
            ToolCall("say", {"text": "hello"}),
        )
    )
    await asyncio.sleep(0)
    await scenario.actor.bus.publish(
        CommandRejectedEvent(
            **scenario.actor._event_base(
                actor_id=str(scenario.character),
                command_id="other-command",
                command_type="say",
                reason="other rejection",
            )
        )
    )
    await scenario.actor.tick(0)

    action = await task

    assert action.status == "executed"
    assert action.tool == "say"


@pytest.mark.asyncio
async def test_character_chat_rejected_action_gets_second_pass_and_fallback():
    scenario = build_scenario()
    install_core(scenario.actor)
    agent = FakeChatAgent(
        [
            ChatAgentReply(tool_call=ToolCall("say", {"text": "stale"})),
            ChatAgentReply(content="That did not work."),
        ]
    )
    service = chat_service(scenario, agent, timeout=1.0)

    task = asyncio.create_task(
        service._submit_tool(
            scenario.character,
            str(scenario.controller),
            scenario.generation + 1,
            ToolCall("say", {"text": "stale"}),
        )
    )
    await asyncio.sleep(0)
    await scenario.actor.tick(0)
    action = await task

    assert action.status == "rejected"
    assert action.reason == "stale controller generation"
    assert CharacterChatService._fallback_reply(action) == "I could not do that."


@pytest.mark.asyncio
async def test_character_chat_immediate_rejection_uses_second_pass_reply():
    scenario = build_scenario()
    install_core(scenario.actor)
    agent = FakeChatAgent(
        [
            ChatAgentReply(tool_call=ToolCall("say", {})),
            ChatAgentReply(content="I could not find the words."),
        ]
    )
    service = chat_service(scenario, agent)

    response = await service.chat(str(scenario.character), chat_request("say something"))

    assert response.action.status == "rejected"
    assert response.action.reason == "missing required argument: text"
    assert response.reply == "I could not find the words."


@pytest.mark.asyncio
async def test_character_chat_submit_reports_immediate_rejection_and_unknown_definition(
    monkeypatch,
):
    scenario = build_scenario()
    service = chat_service(scenario, FakeChatAgent([]))
    scenario.actor.register_action_definition(ActionDefinition("wait", tool_name="wait"))

    rejected = await service._submit_tool(
        scenario.character,
        str(scenario.controller),
        scenario.generation,
        ToolCall("wait", {}),
    )

    assert rejected.status == "rejected"
    assert rejected.reason == "no handler for wait"

    def fail_conversion(*args, **kwargs):
        del args, kwargs
        raise ValueError("unknown tool 'look'")

    monkeypatch.setattr(character_chat_module, "command_from_tool_call", fail_conversion)
    missing_definition = await service._submit_tool(
        scenario.character,
        str(scenario.controller),
        scenario.generation,
        ToolCall("look", {}),
    )
    assert missing_definition.status == "rejected"
    assert missing_definition.reason == "unknown tool 'look'"


@pytest.mark.asyncio
async def test_character_chat_rejects_unallowed_tool_before_submission():
    scenario = build_scenario()
    install_core(scenario.actor)
    agent = FakeChatAgent([ChatAgentReply(tool_call=ToolCall("move", {"direction": "north"}))])
    service = chat_service(scenario, agent)

    response = await service.chat(str(scenario.character), chat_request("go north"))

    assert response.action.status == "rejected"
    assert "not available" in response.action.reason
    assert scenario.actor.pending_submissions() == []


@pytest.mark.asyncio
async def test_character_chat_remember_result_can_ground_second_pass():
    scenario = build_scenario()
    install_core(scenario.actor)
    store = install_memory(scenario.actor, InMemoryStore())
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MemoryProfileComponent(vector_collection="juniper"))
    store.add("juniper", text="The north tunnel floods.", source="manual")
    agent = FakeChatAgent(
        [
            ChatAgentReply(tool_call=ToolCall("remember", {"query": "north tunnel"})),
            ChatAgentReply(content="I remember the tunnel floods."),
        ]
    )
    service = chat_service(scenario, agent, timeout=1.0)

    task = asyncio.create_task(service.chat(str(scenario.character), chat_request("remember")))
    await asyncio.sleep(0)
    await scenario.actor.tick(0)
    response = await task

    assert response.action.status == "executed"
    assert response.action.result_events[0]["event_type"] == "NotesSearchedEvent"
    assert response.reply == "I remember the tunnel floods."


@pytest.mark.asyncio
async def test_character_chat_unresolved_reference_does_not_submit():
    scenario = build_scenario()
    install_core(scenario.actor)
    agent = FakeChatAgent([ChatAgentReply(tool_call=ToolCall("inspect", {"target_id": "moon"}))])
    service = chat_service(scenario, agent)

    response = await service.chat(str(scenario.character), chat_request("inspect the moon"))

    assert response.action.status == "unresolved"
    assert "moon" in response.action.reason
    assert scenario.actor.pending_submissions() == []
    assert CharacterChatService._fallback_reply(response.action) == "I am not sure what you mean."
    fallback = CharacterChatService._fallback_reply(
        response.action.model_copy(update={"status": "none"})
    )
    assert fallback == "All right."


def test_character_chat_status_and_disabled_route():
    scenario = build_scenario()
    app = create_app(scenario.actor)

    from fastapi.testclient import TestClient

    client = TestClient(app)
    assert client.get("/world/chat/status").json()["enabled"] is False
    response = client.post(
        f"/world/character/{scenario.character}/chat",
        json={"client_id": "c", "message": "hi"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "character chat is not enabled"


def test_character_chat_route_reports_invalid_character_and_wrong_kind():
    scenario = build_scenario()
    install_core(scenario.actor)
    service = chat_service(scenario, FakeChatAgent([ChatAgentReply(content="hi")]))
    item = spawn_entity(scenario.actor.world, [IdentityComponent(name="stone", kind="item")])
    app = create_app(scenario.actor, character_chat=service)

    from fastapi.testclient import TestClient

    client = TestClient(app)
    assert client.post(
        "/world/character/not-real/chat",
        json={"client_id": "c", "message": "hi"},
    ).status_code == 404
    assert client.post(
        f"/world/character/{item.id}/chat",
        json={"client_id": "c", "message": "hi"},
    ).status_code == 400


def test_character_chat_route_conflicts_for_non_llm_character():
    scenario = build_scenario()
    install_core(scenario.actor)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="web")])
    scenario.actor.assign_controller(scenario.character, web.id)
    service = chat_service(scenario, FakeChatAgent([ChatAgentReply(content="hi")]))
    app = create_app(scenario.actor, character_chat=service)

    from fastapi.testclient import TestClient

    response = TestClient(app).post(
        f"/world/character/{scenario.character}/chat",
        json={"client_id": "c", "message": "hi"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "character chat requires the current controller to be llm"


def test_character_chat_route_validates_request_and_reports_allowed_tools():
    scenario = build_scenario()
    install_core(scenario.actor)
    service = chat_service(scenario, FakeChatAgent([ChatAgentReply(content="hi")]))
    app = create_app(scenario.actor, character_chat=service)

    from fastapi.testclient import TestClient

    client = TestClient(app)
    status = client.get("/world/chat/status").json()
    assert status["enabled"] is True
    assert set(status["allowed_tools"]) == ALLOWED_CHAT_TOOLS
    assert {"remember", "take_note", "reflect", "forget"}.issubset(status["allowed_tools"])
    response = client.post(
        f"/world/character/{scenario.character}/chat",
        json={"client_id": "c", "message": ""},
    )
    assert response.status_code == 422


def test_build_character_chat_service_factory_returns_service():
    scenario = build_scenario()
    service = build_character_chat_service(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        FakeChatAgent([ChatAgentReply(content="hi")]),
    )

    assert isinstance(service, CharacterChatService)
