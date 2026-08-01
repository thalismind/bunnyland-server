from __future__ import annotations

import asyncio
import threading

import httpx
import pytest
from conftest import build_scenario

from bunnyland.core import (
    ActionDefinition,
    ContainmentMode,
    Contains,
    ControlledBy,
    DeadComponent,
    DownedComponent,
    IdentityComponent,
    MemoryProfileComponent,
    PortableComponent,
    SleepingComponent,
    SuspendedComponent,
    SuspendedControllerComponent,
    WebControllerComponent,
    spawn_entity,
)
from bunnyland.core.events import CommandExecutedEvent, CommandRejectedEvent
from bunnyland.foundation.persona.mechanics import (
    GoalComponent,
    PersonaProfileComponent,
    PreferenceComponent,
    TraitSetComponent,
)
from bunnyland.llm_agents.agent import (
    PROSE_REPLY_CORRECTION_PROMPT,
    TEXT_REPLY_CORRECTION_PROMPT,
    ChatAgentReply,
)
from bunnyland.llm_agents.tools import ToolCall
from bunnyland.memory import InMemoryStore, install_memory
from bunnyland.plugins import apply_plugins, bunnyland_plugins, collect_persona_fragments
from bunnyland.plugins.ids import CORE_VERBS
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.server import app as server_app
from bunnyland.server import character_chat as character_chat_module
from bunnyland.server.app import create_app
from bunnyland.server.character_chat import (
    ALLOWED_CHAT_TOOLS,
    CharacterChatService,
    PendingChatAction,
    build_character_chat_service,
)
from bunnyland.server.client_ids import CLIENT_ID_HEADER
from bunnyland.server.jobs import JobRegistry
from bunnyland.server.models import (
    CharacterChatActionResult,
    CharacterChatPendingResponse,
    CharacterChatRequest,
    CharacterChatResponse,
)
from bunnyland.server.v1_models import ChatJobRequest


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


def install_core(actor):
    apply_plugins([plugin for plugin in bunnyland_plugins() if plugin.id == CORE_VERBS], actor)


def chat_request(message="hello") -> CharacterChatRequest:
    return CharacterChatRequest(client_id="test-client", message=message)


def chat_service(
    scenario,
    agent,
    *,
    timeout=0.01,
    reject_text_tool_calls=True,
    allow_sleeping_character_chat=False,
) -> CharacterChatService:
    return CharacterChatService(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        agent,
        result_timeout_seconds=timeout,
        reject_text_tool_calls=reject_text_tool_calls,
        allow_sleeping_character_chat=allow_sleeping_character_chat,
    )


def route_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={CLIENT_ID_HEADER: "chat-client"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("component", "reason"),
    [
        (DeadComponent(died_at_epoch=1, cause="old age"), "dead character is not available"),
        (
            DownedComponent(downed_at_epoch=1, cause="injury"),
            "unconscious character is not available",
        ),
        (SleepingComponent(started_at_epoch=1), "sleeping character cannot be interrupted"),
        (SuspendedComponent(reason="offline", suspended_at_epoch=1), "must be activated"),
    ],
)
async def test_character_chat_rejects_inactive_character_before_calling_agent(component, reason):
    scenario = build_scenario()
    scenario.actor.world.get_entity(scenario.character).add_component(component)
    agent = FakeChatAgent([ChatAgentReply(content="should not run")])

    with pytest.raises(PermissionError, match=reason):
        await chat_service(scenario, agent).chat(
            str(scenario.character),
            chat_request(),
        )

    assert agent.calls == []


@pytest.mark.asyncio
async def test_character_chat_can_allow_sleeping_character_when_enabled():
    scenario = build_scenario()
    scenario.actor.world.get_entity(scenario.character).add_component(
        SleepingComponent(started_at_epoch=1)
    )
    agent = FakeChatAgent([ChatAgentReply(content="I can still hear you.")])

    response = await chat_service(
        scenario,
        agent,
        allow_sleeping_character_chat=True,
    ).chat(str(scenario.character), chat_request())

    assert response.reply == "I can still hear you."
    assert len(agent.calls) == 1


async def claim_character(client: httpx.AsyncClient, character_id: str) -> tuple[str, dict]:
    response = await client.post("/v1/play/claims", json={"character_id": character_id})
    return response.json()["id"], {
        CLIENT_ID_HEADER: "chat-client",
        "X-Bunnyland-Claim-Secret": response.headers["X-Bunnyland-Claim-Secret"],
    }


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
    assert "native structured tool-call interface" in system_prompt
    assert "prefer take_note" in system_prompt
    tool_names = {
        tool["function"]["name"]
        for tool in agent.calls[0]["tools"]
        if tool.get("type") == "function"
    }
    assert tool_names == ALLOWED_CHAT_TOOLS
    assert "move" not in tool_names


@pytest.mark.asyncio
async def test_character_chat_retries_text_tool_call_as_native_structured_call():
    scenario = build_scenario()
    install_core(scenario.actor)
    malformed = (
        '<invoke name="inspect"> <｜DSML｜ name="target_id" '
        'string="true">courier letter</｜DSML｜> </invoke>'
    )
    agent = FakeChatAgent(
        [
            ChatAgentReply(content=malformed),
            ChatAgentReply(content=malformed, tool_call=ToolCall("look", {})),
        ]
    )
    service = chat_service(scenario, agent, timeout=0.0)

    response = await service.chat(str(scenario.character), chat_request("look around"))

    assert response.action.status == "queued"
    assert response.action.tool == "look"
    assert malformed not in response.reply
    assert len(agent.calls) == 2
    retry_messages = agent.calls[1]["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": malformed}
    assert retry_messages[-1] == {
        "role": "user",
        "content": TEXT_REPLY_CORRECTION_PROMPT,
    }
    assert agent.calls[1]["tools"] == agent.calls[0]["tools"]


@pytest.mark.asyncio
async def test_character_chat_keeps_native_call_and_drops_tagged_content():
    scenario = build_scenario()
    install_core(scenario.actor)
    malformed = '<invoke name="look"></invoke>'
    agent = FakeChatAgent([ChatAgentReply(content=malformed, tool_call=ToolCall("look", {}))])
    service = chat_service(scenario, agent, timeout=0.0)

    response = await service.chat(str(scenario.character), chat_request("look around"))

    assert response.action.status == "queued"
    assert response.action.tool == "look"
    assert malformed not in response.reply
    assert len(agent.calls) == 1


@pytest.mark.parametrize(
    "malformed",
    [
        '<invoke name="look"></invoke>',
        '<｜DSML｜ name="target_id">crate</｜DSML｜>',
        '<tool_call>{"name": "look"}</tool_call>',
        '<function_call name="look"></function_call>',
    ],
)
@pytest.mark.asyncio
async def test_character_chat_detects_text_tool_call_tag_variants(malformed):
    scenario = build_scenario()
    install_core(scenario.actor)
    agent = FakeChatAgent(
        [
            ChatAgentReply(content=malformed),
            ChatAgentReply(content="Let me answer plainly."),
        ]
    )
    service = chat_service(scenario, agent)

    response = await service.chat(str(scenario.character), chat_request("try again"))

    assert response.reply == "Let me answer plainly."
    assert len(agent.calls) == 2


@pytest.mark.asyncio
async def test_character_chat_suppresses_repeated_text_tool_call():
    scenario = build_scenario()
    install_core(scenario.actor)
    malformed = '<invoke name="look"></invoke>'
    agent = FakeChatAgent(
        [
            ChatAgentReply(content=malformed),
            ChatAgentReply(content=malformed),
        ]
    )
    service = chat_service(scenario, agent)

    response = await service.chat(str(scenario.character), chat_request("try again"))

    assert response.reply == "..."
    assert malformed not in response.reply
    assert len(agent.calls) == 2


@pytest.mark.asyncio
async def test_character_chat_can_allow_text_tool_calls_for_provider_debugging():
    scenario = build_scenario()
    install_core(scenario.actor)
    malformed = '<invoke name="look"></invoke>'
    agent = FakeChatAgent([ChatAgentReply(content=malformed)])
    service = chat_service(scenario, agent, reject_text_tool_calls=False)

    response = await service.chat(str(scenario.character), chat_request("look around"))

    assert response.reply == malformed
    assert len(agent.calls) == 1


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

    assert "look" in service.allowed_tools
    web = spawn_entity(
        scenario.actor.world,
        [WebControllerComponent(client_id="browser", label="manual")],
    )
    scenario.actor.assign_controller(scenario.character, web.id)
    with pytest.raises(PermissionError, match="current controller to be llm"):
        await service.chat(str(scenario.character), chat_request())


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
async def test_character_chat_inspect_resolves_reachable_target_and_executes():
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
            ChatAgentReply(tool_call=ToolCall("inspect", {"target_id": "pebble"})),
            ChatAgentReply(content="It is a small pebble."),
        ]
    )
    service = chat_service(scenario, agent, timeout=1.0)

    assert {"look", "inspect"}.issubset(service.allowed_tools)

    task = asyncio.create_task(
        service.chat(str(scenario.character), chat_request("inspect the pebble"))
    )
    await asyncio.sleep(0)
    await scenario.actor.tick(0)
    response = await task

    assert response.reply == "It is a small pebble."
    assert response.action.status == "executed"
    assert response.action.tool == "inspect"
    assert response.action.result_events[0]["event_type"] == "EntityInspectedEvent"
    assert response.action.result_events[0]["target_ids"] == [str(pebble.id)]


@pytest.mark.asyncio
async def test_character_chat_retries_tagged_action_followup_as_clean_prose():
    scenario = build_scenario()
    install_core(scenario.actor)
    malformed = '<invoke name="look"></invoke>'
    agent = FakeChatAgent(
        [
            ChatAgentReply(tool_call=ToolCall("look", {})),
            ChatAgentReply(content=malformed),
            ChatAgentReply(content="I can answer without tags."),
        ]
    )
    service = chat_service(scenario, agent, timeout=1.0)

    task = asyncio.create_task(service.chat(str(scenario.character), chat_request("what is here?")))
    await asyncio.sleep(0)
    await scenario.actor.tick(0)
    response = await task

    assert response.reply == "I can answer without tags."
    assert agent.calls[2]["tools"] == []
    assert agent.calls[2]["messages"][-1]["content"] == PROSE_REPLY_CORRECTION_PROMPT


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
async def test_character_chat_queued_remember_result_is_wrapped_when_polled():
    scenario = build_scenario()
    install_core(scenario.actor)
    store = install_memory(scenario.actor, InMemoryStore())
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MemoryProfileComponent(vector_collection="juniper"))
    store.add("juniper", text="The greenhouse vines are a human alien hybrid.", source="manual")
    agent = FakeChatAgent(
        [
            ChatAgentReply(tool_call=ToolCall("remember", {"query": "greenhouse vines"})),
            ChatAgentReply(content="I remember the greenhouse vines are a hybrid."),
        ]
    )
    service = chat_service(scenario, agent, timeout=0.0)

    response = await service.chat(str(scenario.character), chat_request("remember the vines"))
    assert response.action.status == "queued"
    assert response.action.command_id

    queued = await service.pending_result(
        str(scenario.character), "test-client", response.action.command_id
    )
    assert queued.complete is False
    assert queued.reply == ""
    assert queued.action.status == "queued"

    await scenario.actor.tick(0)
    wrapped = await service.pending_result(
        str(scenario.character), "test-client", response.action.command_id
    )

    assert wrapped.complete is True
    assert wrapped.action.status == "executed"
    assert wrapped.action.result_events[0]["event_type"] == "NotesSearchedEvent"
    assert wrapped.reply == "I remember the greenhouse vines are a hybrid."
    assert "human alien hybrid" in str(agent.calls[-1]["messages"])


@pytest.mark.asyncio
async def test_character_chat_retries_tagged_pending_followup_as_clean_prose():
    scenario = build_scenario()
    install_core(scenario.actor)
    malformed = '<｜DSML｜ name="target_id">room</｜DSML｜>'
    agent = FakeChatAgent(
        [
            ChatAgentReply(tool_call=ToolCall("say", {"text": "soon"})),
            ChatAgentReply(content=malformed),
            ChatAgentReply(content="That is done."),
        ]
    )
    service = chat_service(scenario, agent, timeout=0.0)

    response = await service.chat(
        str(scenario.character),
        chat_request("say something"),
    )
    await scenario.actor.tick(0)
    pending = await service.pending_result(
        str(scenario.character),
        "test-client",
        response.action.command_id,
    )

    assert pending.complete is True
    assert pending.reply == "That is done."
    assert agent.calls[2]["tools"] == []
    assert agent.calls[2]["messages"][-1]["content"] == PROSE_REPLY_CORRECTION_PROMPT


@pytest.mark.asyncio
async def test_character_chat_pending_result_is_client_scoped():
    scenario = build_scenario()
    install_core(scenario.actor)
    agent = FakeChatAgent([ChatAgentReply(tool_call=ToolCall("say", {"text": "soon"}))])
    service = chat_service(scenario, agent, timeout=0.0)

    response = await service.chat(str(scenario.character), chat_request("say something"))

    with pytest.raises(ValueError, match="pending chat action does not exist"):
        await service.pending_result(
            str(scenario.character), "other-client", response.action.command_id
        )


@pytest.mark.asyncio
async def test_character_chat_pending_registration_handles_already_completed_event():
    scenario = build_scenario()
    install_core(scenario.actor)
    agent = FakeChatAgent([ChatAgentReply(content="That already happened.")])
    service = chat_service(scenario, agent, timeout=0.0)
    service._pending[("test-client", str(scenario.character), "other-command")] = PendingChatAction(
        client_id="test-client",
        character_id=str(scenario.character),
        command_id="other-command",
        messages=[],
        user_message="wait",
        model=None,
        provider=None,
        action=CharacterChatActionResult(tool="wait", command_id="other-command", status="queued"),
    )
    service._complete_pending(
        CommandExecutedEvent(
            **scenario.actor._event_base(
                actor_id=str(scenario.character),
                command_id="cmd-completed",
                command_type="say",
                result_events=(),
            )
        )
    )
    service._register_pending(
        PendingChatAction(
            client_id="test-client",
            character_id=str(scenario.character),
            command_id="cmd-completed",
            messages=[],
            user_message="say something",
            model=None,
            provider=None,
            action=CharacterChatActionResult(
                tool="say", command_id="cmd-completed", status="queued"
            ),
        )
    )

    result = await service.pending_result(str(scenario.character), "test-client", "cmd-completed")

    assert result.complete is True
    assert result.action.tool == "say"
    assert result.action.status == "executed"
    assert result.reply == "That already happened."


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
    scenario.actor.register_action_definition(
        ActionDefinition("wait", tool_name="wait", chat_safe=True)
    )

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
async def test_character_chat_rejects_verb_that_is_not_chat_safe():
    # Fail-safe default: a real, handled verb that does not declare chat_safe must not be
    # reachable through character chat, even though it is a valid in-world action.
    scenario = build_scenario()
    service = chat_service(scenario, FakeChatAgent([]))

    assert "move" not in service.allowed_tools
    rejected = await service._submit_tool(
        scenario.character,
        str(scenario.controller),
        scenario.generation,
        ToolCall("move", {"direction": "north"}),
    )

    assert rejected.status == "rejected"
    assert rejected.reason == "tool 'move' is not available in character chat"


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


@pytest.mark.asyncio
async def test_character_chat_status_and_disabled_route():
    scenario = build_scenario()
    app = create_app(scenario.actor, allow_unauthenticated_embedding=True)

    async with route_client(app) as client:
        features = (await client.get("/v1/public/features")).json()
        assert features["character_chat"] is False
        assert features["allow_sleeping_character_chat"] is False
        response = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "hi"},
        )
        assert response.status_code == 202
        assert response.json()["status"] == "failed"
    assert response.json()["failure"]["detail"] == "character chat is not enabled"


@pytest.mark.asyncio
async def test_character_chat_route_reports_invalid_character_and_wrong_kind():
    scenario = build_scenario()
    install_core(scenario.actor)
    service = chat_service(scenario, FakeChatAgent([ChatAgentReply(content="hi")]))
    item = spawn_entity(scenario.actor.world, [IdentityComponent(name="stone", kind="item")])
    app = create_app(scenario.actor, character_chat=service, allow_unauthenticated_embedding=True)

    async with route_client(app) as client:
        assert (
            await client.post(
                "/v1/chat/characters/not-real/jobs",
                json={"kind": "chat", "message": "hello"},
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/v1/chat/characters/{item.id}/jobs",
                json={"kind": "chat", "message": "hello"},
            )
        ).status_code == 400
        assert (await client.get("/v1/profile/characters/not-real")).status_code == 404
        assert (await client.get(f"/v1/profile/characters/{item.id}")).status_code == 400


@pytest.mark.asyncio
async def test_claim_job_rejects_chat_without_changing_controller():
    scenario = build_scenario()
    install_core(scenario.actor)
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="web")])
    scenario.actor.assign_controller(scenario.character, web.id)
    app = create_app(scenario.actor, allow_unauthenticated_embedding=True)

    async with route_client(app) as client:
        claim_id, headers = await claim_character(client, str(scenario.character))
        controller_before = scenario.actor.world.get_entity(scenario.character).get_relationships(
            ControlledBy
        )[0][1]
        response = await client.post(
            f"/v1/play/claims/{claim_id}/jobs",
            headers=headers,
            json={"kind": "chat", "message": "hi"},
        )
    assert response.status_code == 422
    assert (
        scenario.actor.world.get_entity(scenario.character).get_relationships(ControlledBy)[0][1]
        == controller_before
    )


@pytest.mark.asyncio
async def test_character_profile_and_chat_do_not_require_or_change_a_claim():
    scenario = build_scenario()
    install_core(scenario.actor)
    service = chat_service(scenario, FakeChatAgent([ChatAgentReply(content="hi")]))
    app = create_app(scenario.actor, character_chat=service, allow_unauthenticated_embedding=True)

    async with route_client(app) as client:
        profiles = await client.get("/v1/profile/characters")
        profile = await client.get(f"/v1/profile/characters/{scenario.character}")
        submitted = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "hello"},
        )
        await asyncio.sleep(0)
        fetched = await client.get(
            f"/v1/chat/characters/{scenario.character}/jobs/{submitted.json()['id']}"
        )

    assert profiles.status_code == 200
    assert str(scenario.character) in {item["id"] for item in profiles.json()["characters"]}
    assert profile.status_code == 200
    assert profile.json()["character_id"] == str(scenario.character)
    assert profile.json()["sheet"]["vitals"]
    assert "actions" not in profile.json()
    assert submitted.status_code == 202
    assert fetched.json()["status"] == "succeeded"
    assert fetched.json()["result"]["reply"] == "hi"
    assert (
        scenario.actor.world.get_entity(scenario.character).get_relationships(ControlledBy)[0][1]
        == scenario.controller
    )


@pytest.mark.asyncio
async def test_character_chat_job_returns_before_the_llm_finishes():
    scenario = build_scenario()
    install_core(scenario.actor)
    release = asyncio.Event()

    class WaitingAgent(FakeChatAgent):
        async def chat(self, messages, **kwargs):
            await release.wait()
            return await super().chat(messages, **kwargs)

    service = chat_service(scenario, WaitingAgent([ChatAgentReply(content="ready")]))
    app = create_app(scenario.actor, character_chat=service, allow_unauthenticated_embedding=True)

    async with route_client(app) as client:
        submitted = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "hello"},
        )
        assert submitted.status_code == 202
        assert submitted.json()["status"] == "queued"
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        fetched = await client.get(
            f"/v1/chat/characters/{scenario.character}/jobs/{submitted.json()['id']}"
        )

    assert fetched.json()["status"] == "succeeded"
    assert fetched.json()["result"]["reply"] == "ready"


def test_character_chat_job_is_cancelled_during_app_shutdown():
    scenario = build_scenario()
    started = threading.Event()
    cancelled = threading.Event()

    class WaitingChat:
        async def chat(self, _character_id, _request):
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    app = create_app(
        scenario.actor,
        character_chat=WaitingChat(),
        allow_unauthenticated_embedding=True,
    )
    testclient = pytest.importorskip("fastapi.testclient")
    with testclient.TestClient(app) as client:
        response = client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            headers={CLIENT_ID_HEADER: "chat-client"},
            json={"kind": "chat", "message": "hello"},
        )
        assert response.status_code == 202
        assert started.wait(timeout=1)

    assert cancelled.wait(timeout=1)


@pytest.mark.asyncio
async def test_character_chat_job_reports_pending_result_failure():
    scenario = build_scenario()

    class FailingPendingChat:
        async def chat(self, character_id, _request):
            return CharacterChatResponse(
                world_epoch=scenario.actor.epoch,
                character_id=character_id,
                reply="",
                complete=False,
                action=CharacterChatActionResult(
                    tool="say",
                    command_id="command:pending",
                    status="queued",
                ),
            )

        async def pending_result(self, *_args):
            raise RuntimeError("pending result failed")

    app = create_app(
        scenario.actor,
        character_chat=FailingPendingChat(),
        allow_unauthenticated_embedding=True,
    )
    async with route_client(app) as client:
        submitted = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "hello"},
        )
        await asyncio.sleep(0.3)
        fetched = await client.get(submitted.headers["Location"])

    assert fetched.json()["status"] == "failed"
    assert fetched.json()["failure"]["detail"] == "pending result failed"


@pytest.mark.asyncio
async def test_character_chat_job_handles_eviction_while_work_is_running(monkeypatch):
    scenario = build_scenario()
    monkeypatch.setattr(server_app, "JobRegistry", lambda: JobRegistry(max_total=1))
    started = {
        "success": asyncio.Event(),
        "failure": asyncio.Event(),
    }
    release = {
        "success": asyncio.Event(),
        "failure": asyncio.Event(),
    }

    class EvictedChat:
        async def chat(self, character_id, request):
            outcome = request.message.removeprefix("first-")
            if request.message.startswith("first-"):
                started[outcome].set()
                await release[outcome].wait()
                if outcome == "failure":
                    raise RuntimeError("evicted failure")
            return CharacterChatResponse(
                world_epoch=scenario.actor.epoch,
                character_id=character_id,
                reply=request.message,
            )

    app = create_app(
        scenario.actor,
        character_chat=EvictedChat(),
        allow_unauthenticated_embedding=True,
    )
    async with route_client(app) as client:
        first_success = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "first-success"},
        )
        await started["success"].wait()
        await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "evict-success"},
        )
        release["success"].set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        first_failure = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "first-failure"},
        )
        await started["failure"].wait()
        await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "evict-failure"},
        )
        release["failure"].set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert (await client.get(first_success.headers["Location"])).status_code == 404
        assert (await client.get(first_failure.headers["Location"])).status_code == 404


@pytest.mark.asyncio
async def test_character_chat_job_fails_after_pending_action_timeout(monkeypatch):
    scenario = build_scenario()
    monkeypatch.setattr(server_app, "CHAT_JOB_PENDING_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(server_app, "CHAT_JOB_POLL_SECONDS", 0)

    class NeverCompletesChat:
        async def chat(self, character_id, _request):
            return CharacterChatResponse(
                world_epoch=scenario.actor.epoch,
                character_id=character_id,
                reply="",
                complete=False,
                action=CharacterChatActionResult(
                    tool="say",
                    command_id="command:pending",
                    status="queued",
                ),
            )

        async def pending_result(self, character_id, *_args):
            return CharacterChatPendingResponse(
                world_epoch=scenario.actor.epoch,
                character_id=character_id,
                command_id="command:pending",
                reply="",
                complete=False,
                action=CharacterChatActionResult(
                    tool="say",
                    command_id="command:pending",
                    status="queued",
                ),
            )

    app = create_app(
        scenario.actor,
        character_chat=NeverCompletesChat(),
        allow_unauthenticated_embedding=True,
    )
    async with route_client(app) as client:
        submitted = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "hello"},
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        fetched = await client.get(submitted.headers["Location"])

    assert fetched.json()["status"] == "failed"
    assert fetched.json()["failure"]["detail"] == "the character did not finish this action in time"


@pytest.mark.asyncio
async def test_character_chat_requires_client_and_supported_controller():
    scenario = build_scenario()
    app = create_app(scenario.actor, allow_unauthenticated_embedding=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        missing_client = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "hello"},
        )
        missing_poll_client = await client.get(
            f"/v1/chat/characters/{scenario.character}/jobs/missing"
        )

    assert missing_client.status_code == 403
    assert missing_poll_client.status_code == 403

    submit_route = next(
        route for route in app.routes if route.path == "/v1/chat/characters/{character_id}/jobs"
    )
    poll_route = next(
        route
        for route in app.routes
        if route.path == "/v1/chat/characters/{character_id}/jobs/{job_id}"
    )
    with pytest.raises(server_app.HTTPException, match=f"{CLIENT_ID_HEADER} header is required"):
        await submit_route.endpoint(
            str(scenario.character),
            ChatJobRequest(kind="chat", message="hello"),
            server_app.Response(),
            None,
        )
    with pytest.raises(server_app.HTTPException, match=f"{CLIENT_ID_HEADER} header is required"):
        await poll_route.endpoint(str(scenario.character), "missing", None)

    character = scenario.actor.world.get_entity(scenario.character)
    character.remove_relationship(ControlledBy, scenario.controller)
    async with route_client(app) as client:
        no_controller = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "hello"},
        )
        suspended = spawn_entity(
            scenario.actor.world,
            [SuspendedControllerComponent(reason="offline")],
        )
        scenario.actor.assign_controller(scenario.character, suspended.id)
        unavailable = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "hello"},
        )

    assert no_controller.status_code == 409
    assert unavailable.status_code == 202
    assert unavailable.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_human_controlled_character_receives_chat_and_replies_through_claim():
    scenario = build_scenario()
    install_core(scenario.actor)
    app = create_app(
        scenario.actor,
        character_chat=chat_service(scenario, FakeChatAgent([])),
        allow_unauthenticated_embedding=True,
    )

    async with route_client(app) as client:
        claim_id, claim_headers = await claim_character(client, str(scenario.character))
        controller_id = client.headers[CLIENT_ID_HEADER]
        submitted = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            headers={CLIENT_ID_HEADER: "profile-client"},
            json={"kind": "chat", "message": "Are you there?"},
        )
        events = await client.get(f"/v1/play/claims/{claim_id}/events", headers=claim_headers)
        hidden = await client.get(
            f"/v1/chat/characters/{scenario.character}/jobs/{submitted.json()['id']}",
            headers={CLIENT_ID_HEADER: "different-profile-client"},
        )
        missing = await client.post(
            f"/v1/play/claims/{claim_id}/chat-jobs/missing",
            headers=claim_headers,
            json={"reply": "No job."},
        )
        replied = await client.post(
            f"/v1/play/claims/{claim_id}/chat-jobs/{submitted.json()['id']}",
            headers=claim_headers,
            json={"reply": "I am here."},
        )
        fetched = await client.get(
            f"/v1/chat/characters/{scenario.character}/jobs/{submitted.json()['id']}",
            headers={CLIENT_ID_HEADER: "profile-client"},
        )
        repeated = await client.post(
            f"/v1/play/claims/{claim_id}/chat-jobs/{submitted.json()['id']}",
            headers=claim_headers,
            json={"reply": "Too late."},
        )

    assert submitted.status_code == 202
    assert submitted.json()["status"] == "queued"
    requested = [
        item["data"]["event"]
        for item in events.json()["events"]
        if item["data"]["event_type"] == "CharacterChatRequestedEvent"
    ]
    assert requested[0]["message"] == "Are you there?"
    assert hidden.status_code == 404
    assert missing.status_code == 404
    assert replied.status_code == 200
    assert repeated.status_code == 409
    assert fetched.json()["status"] == "succeeded"
    assert fetched.json()["result"]["reply"] == "I am here."
    active_controller_id = scenario.actor.world.get_entity(scenario.character).get_relationships(
        ControlledBy
    )[0][1]
    active_controller = scenario.actor.world.get_entity(active_controller_id)
    assert active_controller.get_component(WebControllerComponent).client_id == controller_id


@pytest.mark.asyncio
async def test_character_chat_route_validates_request_and_reports_allowed_tools():
    scenario = build_scenario()
    install_core(scenario.actor)
    service = chat_service(
        scenario,
        FakeChatAgent([ChatAgentReply(content="hi")]),
        allow_sleeping_character_chat=True,
    )
    app = create_app(scenario.actor, character_chat=service, allow_unauthenticated_embedding=True)

    async with route_client(app) as client:
        features = (await client.get("/v1/public/features")).json()
        assert features["character_chat"] is True
        assert features["allow_sleeping_character_chat"] is True
        claim_id, headers = await claim_character(client, str(scenario.character))
        response = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": ""},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_character_chat_route_allows_sleeping_character_only_when_enabled():
    scenario = build_scenario()
    install_core(scenario.actor)
    scenario.actor.world.get_entity(scenario.character).add_component(
        SleepingComponent(started_at_epoch=1)
    )
    disabled_app = create_app(
        scenario.actor,
        character_chat=chat_service(scenario, FakeChatAgent([])),
        allow_unauthenticated_embedding=True,
    )

    async with route_client(disabled_app) as client:
        rejected = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "Can you hear me?"},
        )

    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "sleeping character cannot be interrupted by chat"

    enabled_app = create_app(
        scenario.actor,
        character_chat=chat_service(
            scenario,
            FakeChatAgent([ChatAgentReply(content="I can still hear you.")]),
            allow_sleeping_character_chat=True,
        ),
        allow_unauthenticated_embedding=True,
    )
    async with route_client(enabled_app) as client:
        submitted = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "Can you hear me?"},
        )
        await asyncio.sleep(0)
        fetched = await client.get(submitted.headers["Location"])

    assert submitted.status_code == 202
    assert fetched.json()["status"] == "succeeded"
    assert fetched.json()["result"]["reply"] == "I can still hear you."


@pytest.mark.asyncio
async def test_character_chat_job_reports_and_completes_queued_action():
    scenario = build_scenario()
    install_core(scenario.actor)
    service = chat_service(
        scenario,
        FakeChatAgent([ChatAgentReply(tool_call=ToolCall("say", {"text": "soon"}))]),
        timeout=0.0,
    )
    app = create_app(scenario.actor, character_chat=service, allow_unauthenticated_embedding=True)

    async with route_client(app) as client:
        response = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "say something"},
        )
        await asyncio.sleep(0)
        body = await client.get(
            f"/v1/chat/characters/{scenario.character}/jobs/{response.json()['id']}"
        )
        assert body.json()["status"] == "running"
        assert body.json()["result"]["action"]["status"] == "queued"
        await asyncio.sleep(0.3)
        await scenario.actor.tick(0)
        await asyncio.sleep(0.3)
        completed = await client.get(
            f"/v1/chat/characters/{scenario.character}/jobs/{response.json()['id']}"
        )

    assert completed.json()["status"] == "succeeded"
    assert completed.json()["result"]["action"]["status"] == "executed"


def test_build_character_chat_service_factory_returns_service():
    scenario = build_scenario()
    service = build_character_chat_service(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        FakeChatAgent([ChatAgentReply(content="hi")]),
    )

    assert isinstance(service, CharacterChatService)
    assert service.allow_sleeping_character_chat is False


async def test_completed_action_cache_stays_bounded_under_world_command_volume():
    # _complete_pending is subscribed to every CommandExecutedEvent and CommandRejectedEvent
    # in the world, not just chat-driven ones, and parked each unmatched result in
    # _completed_actions. Nothing evicted them, so the map grew with total command volume
    # for the life of the process -- NPC ticks alone were enough to leak it.
    scenario = build_scenario()
    install_core(scenario.actor)
    service = chat_service(scenario, FakeChatAgent([]), timeout=0.0)
    service._completed_cache_size = 32

    for index in range(500):
        await scenario.actor.bus.publish(
            CommandRejectedEvent(
                **scenario.actor._event_base(
                    actor_id=str(scenario.character),
                    command_id=f"unrelated-{index}",
                    command_type="move",
                    reason="nope",
                )
            )
        )

    assert len(service._completed_actions) <= 32


async def test_pending_action_cache_stays_bounded():
    scenario = build_scenario()
    install_core(scenario.actor)
    service = chat_service(scenario, FakeChatAgent([]), timeout=0.0)
    service._pending_cache_size = 16

    for index in range(200):
        service._register_pending(
            PendingChatAction(
                client_id="client-a",
                character_id=str(scenario.character),
                command_id=f"cmd-{index}",
                messages=[],
                user_message="hi",
                model=None,
                provider=None,
                action=CharacterChatActionResult(tool="say", command_id=f"cmd-{index}"),
            )
        )

    assert len(service._pending) <= 16
    # The most recent pending action is still resolvable; the oldest were dropped.
    assert ("client-a", str(scenario.character), "cmd-199") in service._pending
    assert ("client-a", str(scenario.character), "cmd-0") not in service._pending
