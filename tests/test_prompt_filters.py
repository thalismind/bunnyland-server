"""Behavioral coverage for persisted asynchronous prompt filters."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from conftest import build_scenario
from pydantic.dataclasses import dataclass
from relics import Component

from bunnyland.core import MemoryProfileComponent, spawn_entity
from bunnyland.core.world_actor import WorldActor
from bunnyland.foundation.prompt_filters.mechanics import (
    BUILTIN_PROMPT_FILTERS,
    CorruptedPromptFilterComponent,
    PromptFilterBinding,
    RecallPromptFilterComponent,
    RedactedPromptFilterComponent,
    StorytellerPromptFilterComponent,
)
from bunnyland.llm_agents import ControllerDispatch
from bunnyland.llm_agents.agent import ChatAgentReply
from bunnyland.mcp.server import (
    ClaimSecretRegistry,
    assign_mcp_controller,
    render_mcp_client_prompt,
)
from bunnyland.memory import InMemoryStore, install_memory
from bunnyland.persistence import WorldMeta, load_world, save_world
from bunnyland.plugins import PluginRegistry, bunnyland_plugins
from bunnyland.prompts import (
    PromptBuilder,
    PromptFilterDefinition,
    PromptFilterRuntime,
    apply_prompt_filters,
)
from bunnyland.prompts.builder import render_prompt
from bunnyland.server.character_chat import CharacterChatService
from bunnyland.server.models import CharacterChatRequest


def _bind(scenario, component: Component, *, order: int = 0):
    filter_entity = spawn_entity(scenario.actor.world, [component])
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        PromptFilterBinding(order=order), filter_entity.id
    )
    return filter_entity


def _runtime(scenario, *, llm=None) -> PromptFilterRuntime:
    return PromptFilterRuntime(scenario.actor, BUILTIN_PROMPT_FILTERS, llm=llm)


def _prompt(scenario):
    return PromptBuilder(scenario.actor.world).build(scenario.character)


@pytest.mark.asyncio
async def test_redacted_filter_is_stable_and_respects_strength_targets_and_punctuation():
    scenario = build_scenario()
    _bind(
        scenario,
        RedactedPromptFilterComponent(
            strength=1.0,
            replacement="-",
            targets=("Mosslit", "Burrow"),
        ),
    )
    context = _prompt(scenario)
    text = render_prompt(context)

    first = await _runtime(scenario).apply(
        text, character=scenario.actor.world.get_entity(scenario.character), prompt=context
    )
    second = await _runtime(scenario).apply(
        text, character=scenario.actor.world.get_entity(scenario.character), prompt=context
    )

    assert first == second
    assert "- -" in first
    assert "Location:" in first
    assert "Juniper" in first

    zero = build_scenario()
    _bind(zero, RedactedPromptFilterComponent(strength=0.0))
    zero_context = _prompt(zero)
    zero_text = render_prompt(zero_context)
    assert (
        await _runtime(zero).apply(
            zero_text,
            character=zero.actor.world.get_entity(zero.character),
            prompt=zero_context,
        )
        == zero_text
    )


@pytest.mark.asyncio
async def test_corruption_is_typed_configurable_and_stack_order_is_authoritative():
    first = build_scenario()
    _bind(
        first,
        CorruptedPromptFilterComponent(
            strength=1.0,
            replacements=("changed",),
            phrases=(),
        ),
        order=1,
    )
    _bind(
        first,
        RedactedPromptFilterComponent(strength=1.0, targets=("Mosslit",)),
        order=2,
    )
    context = _prompt(first)
    corrupted_then_redacted = await _runtime(first).apply(
        render_prompt(context),
        character=first.actor.world.get_entity(first.character),
        prompt=context,
    )

    second = build_scenario()
    _bind(
        second,
        RedactedPromptFilterComponent(strength=1.0, targets=("Mosslit",)),
        order=1,
    )
    _bind(
        second,
        CorruptedPromptFilterComponent(
            strength=1.0,
            replacements=("changed",),
            phrases=(),
        ),
        order=2,
    )
    second_context = _prompt(second)
    redacted_then_corrupted = await _runtime(second).apply(
        render_prompt(second_context),
        character=second.actor.world.get_entity(second.character),
        prompt=second_context,
    )

    assert "Mosslit" not in corrupted_then_redacted
    assert "changed" in corrupted_then_redacted
    assert "Mosslit" not in redacted_then_corrupted
    assert "-" in redacted_then_corrupted


@pytest.mark.asyncio
async def test_corruption_handles_empty_configuration_and_phrase_insertion(monkeypatch):
    from bunnyland.foundation.prompt_filters import mechanics

    empty = build_scenario()
    _bind(
        empty,
        CorruptedPromptFilterComponent(strength=1.0, replacements=(), phrases=()),
    )
    empty_context = _prompt(empty)
    assert (
        await _runtime(empty).apply(
            "raw",
            character=empty.actor.world.get_entity(empty.character),
            prompt=empty_context,
        )
        == "raw"
    )

    phrases = build_scenario()
    _bind(
        phrases,
        CorruptedPromptFilterComponent(
            strength=1.0,
            replacements=(),
            phrases=("[whisper]",),
        ),
    )
    monkeypatch.setattr(mechanics, "_unit_hash", lambda *_values: 0.0)
    phrase_context = _prompt(phrases)
    filtered = await _runtime(phrases).apply(
        "Title:\na cat\n",
        character=phrases.actor.world.get_entity(phrases.character),
        prompt=phrase_context,
    )
    assert filtered == "Title:\na cat\n[whisper]\n"

    no_newline = await _runtime(phrases).apply(
        "Title:\nlongword",
        character=phrases.actor.world.get_entity(phrases.character),
        prompt=phrase_context,
    )
    assert no_newline == "Title:\nlongword\n[whisper]"

    monkeypatch.setattr(mechanics, "_unit_hash", lambda *_values: 1.0)
    not_inserted = await _runtime(phrases).apply(
        "longword",
        character=phrases.actor.world.get_entity(phrases.character),
        prompt=phrase_context,
    )
    assert not_inserted == "longword"

    zero = build_scenario()
    _bind(
        zero,
        CorruptedPromptFilterComponent(
            strength=0.0,
            replacements=("changed",),
            phrases=("[whisper]",),
        ),
    )
    zero_context = _prompt(zero)
    assert (
        await _runtime(zero).apply(
            "longword",
            character=zero.actor.world.get_entity(zero.character),
            prompt=zero_context,
        )
        == "longword"
    )


@pytest.mark.asyncio
async def test_recall_queries_preceding_text_and_appends_three_auditable_memories():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MemoryProfileComponent(vector_collection="juniper-private"))
    store = install_memory(scenario.actor, InMemoryStore())
    for index in range(4):
        store.add(
            "juniper-private",
            text=f"Juniper remembers Mosslit Burrow clue {index}",
            source="note",
        )
    _bind(scenario, RecallPromptFilterComponent())
    context = _prompt(scenario)

    filtered = await _runtime(scenario).apply(
        render_prompt(context), character=character, prompt=context
    )

    appended = filtered.rsplit("Recall:\n", maxsplit=1)[1]
    assert appended.count("[untrusted world memory]") == 3
    assert appended.count("[memory:") == 3
    assert "source:note" in appended


@pytest.mark.asyncio
async def test_recall_missing_dependencies_empty_results_and_zero_limit_fail_open(caplog):
    missing_store = build_scenario()
    _bind(missing_store, RecallPromptFilterComponent())
    missing_context = _prompt(missing_store)
    assert (
        await _runtime(missing_store).apply(
            "raw",
            character=missing_store.actor.world.get_entity(missing_store.character),
            prompt=missing_context,
        )
        == "raw"
    )

    missing_profile = build_scenario()
    install_memory(missing_profile.actor, InMemoryStore())
    _bind(missing_profile, RecallPromptFilterComponent())
    profile_context = _prompt(missing_profile)
    assert (
        await _runtime(missing_profile).apply(
            "raw",
            character=missing_profile.actor.world.get_entity(missing_profile.character),
            prompt=profile_context,
        )
        == "raw"
    )

    empty = build_scenario()
    empty_character = empty.actor.world.get_entity(empty.character)
    empty_character.add_component(MemoryProfileComponent(vector_collection="empty"))
    install_memory(empty.actor, InMemoryStore())
    _bind(empty, RecallPromptFilterComponent(limit=0), order=1)
    _bind(empty, RecallPromptFilterComponent(limit=3), order=2)
    empty_context = _prompt(empty)
    assert (
        await _runtime(empty).apply(
            "raw", character=empty_character, prompt=empty_context
        )
        == "raw"
    )
    assert "recall prompt filter requires" in caplog.text


class _Narrator:
    def __init__(self) -> None:
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return SimpleNamespace(content="The moss-lit chamber waits in attentive silence.")


class _EmptyNarrator:
    async def chat(self, messages, **kwargs):
        del messages, kwargs
        return SimpleNamespace(content="")


@pytest.mark.asyncio
async def test_storyteller_rewrites_only_narrative_and_uses_component_model_overrides():
    scenario = build_scenario()
    _bind(
        scenario,
        StorytellerPromptFilterComponent(
            provider="openrouter",
            model="narrator-model",
            instruction="Write with clipped, noir tension.",
        ),
    )
    narrator = _Narrator()
    context = _prompt(scenario)
    original = render_prompt(context)

    filtered = await _runtime(scenario, llm=narrator).apply(
        original,
        character=scenario.actor.world.get_entity(scenario.character),
        prompt=context,
    )

    assert "Narrative:\nThe moss-lit chamber waits in attentive silence." in filtered
    assert "Location:" not in filtered
    assert "Exits:\n- north" in filtered
    assert "Points:\nAction: 5.0/5.0\nFocus: 3.0/3.0" in filtered
    assert "Available commands:" in filtered
    messages, kwargs = narrator.calls[0]
    assert "Style instruction: Write with clipped, noir tension." in messages[0]["content"]
    assert kwargs["provider"] == "openrouter"
    assert kwargs["model"] == "narrator-model"
    assert kwargs["tools"] == []


@pytest.mark.asyncio
async def test_storyteller_missing_llm_empty_reply_and_corrupted_headings_fail_open(caplog):
    missing = build_scenario()
    _bind(missing, StorytellerPromptFilterComponent())
    missing_context = _prompt(missing)
    raw = render_prompt(missing_context)
    assert (
        await _runtime(missing).apply(
            raw,
            character=missing.actor.world.get_entity(missing.character),
            prompt=missing_context,
        )
        == raw
    )

    empty = build_scenario()
    _bind(empty, StorytellerPromptFilterComponent())
    empty_context = _prompt(empty)
    assert (
        await _runtime(empty, llm=_EmptyNarrator()).apply(
            raw,
            character=empty.actor.world.get_entity(empty.character),
            prompt=empty_context,
        )
        == raw
    )

    corrupted = build_scenario()
    _bind(corrupted, StorytellerPromptFilterComponent())
    corrupted_context = _prompt(corrupted)
    narrator = _Narrator()
    assert (
        await _runtime(corrupted, llm=narrator).apply(
            "all headings are gone",
            character=corrupted.actor.world.get_entity(corrupted.character),
            prompt=corrupted_context,
        )
        == "all headings are gone"
    )
    assert narrator.calls == []
    assert "storyteller prompt filter requires" in caplog.text


@pytest.mark.asyncio
async def test_storyteller_consumes_narrative_from_the_preceding_filter_output():
    scenario = build_scenario()
    _bind(
        scenario,
        RedactedPromptFilterComponent(strength=1.0, targets=("Mosslit",)),
        order=1,
    )
    _bind(scenario, StorytellerPromptFilterComponent(), order=2)
    narrator = _Narrator()
    context = _prompt(scenario)

    await _runtime(scenario, llm=narrator).apply(
        render_prompt(context),
        character=scenario.actor.world.get_entity(scenario.character),
        prompt=context,
    )

    assert "Location:\n- Burrow" in narrator.calls[0][0][1]["content"]


def test_narrative_replacement_handles_a_final_section_without_blank_line():
    from bunnyland.foundation.prompt_filters.mechanics import _replace_narrative_sections

    assert _replace_narrative_sections("Location:\nA room", "Rewritten") == (
        "Narrative:\nRewritten\n"
    )


@pytest.mark.asyncio
async def test_filter_failures_keep_prior_text_and_continue(caplog):
    scenario = build_scenario()
    _bind(scenario, RedactedPromptFilterComponent(strength=2.0), order=1)
    _bind(
        scenario,
        RedactedPromptFilterComponent(strength=1.0, targets=("Mosslit",)),
        order=2,
    )
    context = _prompt(scenario)

    filtered = await _runtime(scenario).apply(
        render_prompt(context),
        character=scenario.actor.world.get_entity(scenario.character),
        prompt=context,
    )

    assert "Mosslit" not in filtered
    assert "keeping prior text" in caplog.text


@pytest.mark.asyncio
async def test_runtime_skips_unregistered_or_ambiguous_filter_entities(caplog):
    unregistered = build_scenario()
    unknown = spawn_entity(unregistered.actor.world)
    unregistered.actor.world.get_entity(unregistered.character).add_relationship(
        PromptFilterBinding(), unknown.id
    )
    context = _prompt(unregistered)
    assert (
        await _runtime(unregistered).apply(
            "raw",
            character=unregistered.actor.world.get_entity(unregistered.character),
            prompt=context,
        )
        == "raw"
    )

    ambiguous = build_scenario()
    both = spawn_entity(
        ambiguous.actor.world,
        [RedactedPromptFilterComponent(), CorruptedPromptFilterComponent()],
    )
    ambiguous.actor.world.get_entity(ambiguous.character).add_relationship(
        PromptFilterBinding(), both.id
    )
    ambiguous_context = _prompt(ambiguous)
    assert (
        await _runtime(ambiguous).apply(
            "raw",
            character=ambiguous.actor.world.get_entity(ambiguous.character),
            prompt=ambiguous_context,
        )
        == "raw"
    )
    assert "has 0 registered filter components" in caplog.text
    assert "has 2 registered filter components" in caplog.text


@dataclass(frozen=True)
class _CountingFilterComponent(Component):
    suffix: str = "!"


@pytest.mark.asyncio
async def test_filter_selection_scales_with_character_bindings_not_world_entities():
    scenario = build_scenario()
    calls = []

    async def count(text, context, component):
        assert context.epoch == 42
        calls.append(context.filter_entity.id)
        return text + component.suffix

    definition = PromptFilterDefinition(
        id="example.count",
        component_type=_CountingFilterComponent,
        handler=count,
    )
    bound = _bind(scenario, _CountingFilterComponent())
    for _index in range(500):
        spawn_entity(scenario.actor.world, [_CountingFilterComponent()])
    context = _prompt(scenario)

    filtered = await PromptFilterRuntime(scenario.actor, (definition,)).apply(
        "prompt",
        character=scenario.actor.world.get_entity(scenario.character),
        prompt=context,
        epoch=42,
    )

    assert filtered == "prompt!"
    assert calls == [bound.id]


@pytest.mark.asyncio
async def test_runtime_rejects_duplicate_component_definitions_and_non_text_results(caplog):
    scenario = build_scenario()

    async def identity(text, context, component):
        del context, component
        return text

    first = PromptFilterDefinition("example.first", _CountingFilterComponent, identity)
    second = PromptFilterDefinition("example.second", _CountingFilterComponent, identity)
    with pytest.raises(ValueError, match="registered by both"):
        PromptFilterRuntime(scenario.actor, (first, second))

    async def invalid(text, context, component):
        del text, context, component
        return None

    _bind(scenario, _CountingFilterComponent())
    context = _prompt(scenario)
    runtime = PromptFilterRuntime(
        scenario.actor,
        (PromptFilterDefinition("example.invalid", _CountingFilterComponent, invalid),),
    )
    assert (
        await runtime.apply(
            "raw",
            character=scenario.actor.world.get_entity(scenario.character),
            prompt=context,
        )
        == "raw"
    )

    bare_runtime = PromptFilterRuntime.from_actor(WorldActor())
    assert bare_runtime._by_component == {}
    assert "returned NoneType, expected str" in caplog.text

    assert (
        await apply_prompt_filters(
            "raw",
            runtime=None,
            character=scenario.actor.world.get_entity(scenario.character),
            context=context,
        )
        == "raw"
    )


def test_filter_components_and_bindings_survive_save_reload(tmp_path):
    scenario = build_scenario()
    filter_entity = _bind(
        scenario,
        RedactedPromptFilterComponent(strength=0.6, replacement="---"),
        order=7,
    )
    storyteller = _bind(
        scenario,
        StorytellerPromptFilterComponent(instruction="Use terse cave-horror prose."),
        order=8,
    )
    path = tmp_path / "filtered-world.json"
    save_world(scenario.actor, path, meta=WorldMeta(seed="filters"))

    loaded, _meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))
    character = loaded.world.get_entity(scenario.character)
    bindings = character.get_relationships(PromptFilterBinding)
    component = loaded.world.get_entity(filter_entity.id).get_component(
        RedactedPromptFilterComponent
    )
    storyteller_component = loaded.world.get_entity(storyteller.id).get_component(
        StorytellerPromptFilterComponent
    )

    assert bindings == [
        (PromptFilterBinding(order=7), filter_entity.id),
        (PromptFilterBinding(order=8), storyteller.id),
    ]
    assert component == RedactedPromptFilterComponent(strength=0.6, replacement="---")
    assert storyteller_component.instruction == "Use terse cave-horror prose."


class _CapturingAgent:
    def __init__(self) -> None:
        self.prompts = []
        self.messages = []

    async def decide(self, prompt, context, **kwargs):
        del context, kwargs
        self.prompts.append(prompt)
        return None

    async def chat(self, messages, **kwargs):
        del kwargs
        self.messages.append(messages)
        return ChatAgentReply(content="I hear you.")


@pytest.mark.asyncio
async def test_autonomous_and_character_chat_paths_receive_filtered_text():
    scenario = build_scenario()
    _bind(
        scenario,
        RedactedPromptFilterComponent(strength=1.0, targets=("Mosslit", "Burrow")),
    )
    agent = _CapturingAgent()
    dispatch = ControllerDispatch(scenario.actor, PromptBuilder(scenario.actor.world), agent)

    await dispatch.run_once()
    await asyncio.gather(*tuple(dispatch._inflight.values()))
    assert "Mosslit Burrow" not in agent.prompts[0]

    chat = CharacterChatService(scenario.actor, PromptBuilder(scenario.actor.world), agent)
    await chat.chat(
        str(scenario.character),
        CharacterChatRequest(client_id="test", message="Where are we?"),
    )
    compiled_context = agent.messages[0][1]["content"]
    assert "Mosslit Burrow" not in compiled_context


@pytest.mark.asyncio
async def test_mcp_prompt_path_receives_filtered_text():
    scenario = build_scenario()
    _bind(
        scenario,
        RedactedPromptFilterComponent(strength=1.0, targets=("Mosslit", "Burrow")),
    )
    secrets = ClaimSecretRegistry()
    claim = assign_mcp_controller(
        scenario.actor,
        claim_secrets=secrets,
        client_id="filter-client",
        character_name="Juniper",
    )

    response = await render_mcp_client_prompt(
        scenario.actor,
        claim_secrets=secrets,
        client_id="filter-client",
        claim_id=claim["claim_id"],
        claim_secret=claim["claim_secret"],
        prompt_filter_runtime=_runtime(scenario),
    )

    assert "Mosslit Burrow" not in response["prompt"]
    assert response["character_id"] == str(scenario.character)
