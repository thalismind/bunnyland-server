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
from bunnyland.memory import InMemoryStore, configure_memory_recall, install_memory
from bunnyland.persistence import WorldMeta, load_world, save_world
from bunnyland.plugins import PluginRegistry, bunnyland_plugins
from bunnyland.prompts import (
    AutomaticPromptFilter,
    PromptBuilder,
    PromptFilterDefinition,
    PromptFilterRuntime,
    apply_prompt_filters,
)
from bunnyland.prompts.builder import render_prompt
from bunnyland.server.character_chat import CharacterChatAccess, CharacterChatService
from bunnyland.server.models import CharacterChatRequest


def _bind(scenario, component: Component, *, order: int = 0):
    filter_entity = spawn_entity(scenario.actor.world, [component])
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        PromptFilterBinding(order=order), filter_entity.id
    )
    return filter_entity


def _runtime(scenario, *, llm=None) -> PromptFilterRuntime:
    return PromptFilterRuntime(scenario.actor, BUILTIN_PROMPT_FILTERS, llm=llm)


def _enable_automatic_recall(scenario, *, limit: int = 3, min_score: float = 0.35):
    store = install_memory(scenario.actor, InMemoryStore())
    configure_memory_recall(scenario.actor, limit=limit, min_score=min_score)

    def component():
        policy = scenario.actor.memory_recall_policy
        assert policy is not None
        if policy.limit == 0:
            return None
        return RecallPromptFilterComponent(
            limit=policy.limit,
            min_score=policy.min_score,
        )

    scenario.actor.register_automatic_prompt_filter(
        AutomaticPromptFilter(
            definition_id="bunnyland.prompt_filters.recall",
            required_component=MemoryProfileComponent,
            component_factory=component,
        )
    )
    return store


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
async def test_automatic_recall_applies_threshold_and_explicit_binding_overrides_it():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MemoryProfileComponent(vector_collection="juniper-private"))
    store = _enable_automatic_recall(scenario)
    relevant = store.add(
        "juniper-private",
        text="Juniper remembers the Mosslit Burrow warning.",
        source="conversation",
    )
    store.add(
        "juniper-private",
        text="A polar observatory tracks distant comets.",
        source="note",
    )
    context = _prompt(scenario)

    filtered = await _runtime(scenario).apply(
        render_prompt(context), character=character, prompt=context
    )

    assert f"memory:{relevant.id}" in filtered
    assert "polar observatory" not in filtered
    assert filtered.count("Recall:") == 1

    _bind(scenario, RecallPromptFilterComponent(limit=0))
    overridden = await _runtime(scenario).apply(
        render_prompt(context), character=character, prompt=context
    )
    assert "[untrusted world memory]" not in overridden


@pytest.mark.asyncio
async def test_automatic_recall_bounds_and_sanitizes_memory_lines():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MemoryProfileComponent(vector_collection="juniper-private"))
    store = _enable_automatic_recall(scenario, limit=10, min_score=0.0)
    for index in range(10):
        store.add(
            "juniper-private",
            text=f"Mosslit\nBurrow memory {index} " + ("detail " * 60),
        )
    context = _prompt(scenario)

    filtered = await _runtime(scenario).apply(
        render_prompt(context), character=character, prompt=context
    )

    recall = filtered.rsplit("Recall:\n", maxsplit=1)[1]
    assert len(recall) <= 903
    assert "Mosslit\nBurrow" not in recall
    assert recall.count("[untrusted world memory]") < 10


@pytest.mark.asyncio
async def test_automatic_recall_backend_failure_is_logged_and_hidden_from_prompt(caplog):
    class FailingStore(InMemoryStore):
        def search(self, collection, *, query=None, mode="recent", limit=5):
            del collection, query, mode, limit
            raise RuntimeError("operator-only vector failure")

    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MemoryProfileComponent(vector_collection="juniper-private"))
    _enable_automatic_recall(scenario)
    scenario.actor.memory_store = FailingStore()
    context = _prompt(scenario)
    original = render_prompt(context)

    filtered = await _runtime(scenario).apply(
        original, character=character, prompt=context
    )

    assert filtered == original
    assert "operator-only vector failure" not in filtered
    assert "prompt filter bunnyland.prompt_filters.recall failed" in caplog.text


@pytest.mark.asyncio
async def test_automatic_recall_can_be_skipped_for_non_llm_controller_turns():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MemoryProfileComponent(vector_collection="juniper-private"))
    store = _enable_automatic_recall(scenario, min_score=0.0)
    store.add("juniper-private", text="Juniper recalls a shelter warning.")
    context = _prompt(scenario)
    original = render_prompt(context)

    filtered = await _runtime(scenario).apply(
        original,
        character=character,
        prompt=context,
        include_automatic=False,
    )

    assert filtered == original


@pytest.mark.asyncio
async def test_automatic_recall_can_be_explicitly_excluded():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MemoryProfileComponent(vector_collection="juniper-private"))
    store = _enable_automatic_recall(scenario, min_score=0.0)
    store.add("juniper-private", text="Juniper recalls a private shelter warning.")
    context = _prompt(scenario)
    original = render_prompt(context)

    filtered = await _runtime(scenario).apply(
        original,
        character=character,
        prompt=context,
        excluded_definition_ids=frozenset({"bunnyland.prompt_filters.recall"}),
    )

    assert filtered == original


@pytest.mark.asyncio
async def test_runtime_skips_unavailable_and_invalid_automatic_filters(caplog):
    unknown = build_scenario()
    unknown_character = unknown.actor.world.get_entity(unknown.character)
    unknown_character.add_component(MemoryProfileComponent(vector_collection="unknown"))
    unknown.actor.register_automatic_prompt_filter(
        AutomaticPromptFilter(
            definition_id="example.missing",
            required_component=MemoryProfileComponent,
            component_factory=lambda: RecallPromptFilterComponent(),
        )
    )
    unknown_context = _prompt(unknown)
    assert (
        await _runtime(unknown).apply(
            "raw", character=unknown_character, prompt=unknown_context
        )
        == "raw"
    )

    disabled = build_scenario()
    disabled_character = disabled.actor.world.get_entity(disabled.character)
    disabled_character.add_component(MemoryProfileComponent(vector_collection="disabled"))
    disabled.actor.register_automatic_prompt_filter(
        AutomaticPromptFilter(
            definition_id="bunnyland.prompt_filters.recall",
            required_component=MemoryProfileComponent,
            component_factory=lambda: None,
        )
    )
    disabled_context = _prompt(disabled)
    assert (
        await _runtime(disabled).apply(
            "raw", character=disabled_character, prompt=disabled_context
        )
        == "raw"
    )

    invalid = build_scenario()
    invalid_character = invalid.actor.world.get_entity(invalid.character)
    invalid_character.add_component(MemoryProfileComponent(vector_collection="invalid"))
    invalid.actor.register_automatic_prompt_filter(
        AutomaticPromptFilter(
            definition_id="bunnyland.prompt_filters.recall",
            required_component=MemoryProfileComponent,
            component_factory=lambda: RedactedPromptFilterComponent(),
        )
    )
    invalid_context = _prompt(invalid)
    assert (
        await _runtime(invalid).apply(
            "raw", character=invalid_character, prompt=invalid_context
        )
        == "raw"
    )
    assert "produced RedactedPromptFilterComponent" in caplog.text


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

    invalid_score = build_scenario()
    invalid_character = invalid_score.actor.world.get_entity(invalid_score.character)
    invalid_character.add_component(MemoryProfileComponent(vector_collection="invalid"))
    install_memory(invalid_score.actor, InMemoryStore())
    _bind(invalid_score, RecallPromptFilterComponent(min_score=2.0))
    invalid_context = _prompt(invalid_score)
    assert (
        await _runtime(invalid_score).apply(
            "raw", character=invalid_character, prompt=invalid_context
        )
        == "raw"
    )
    assert "recall minimum score must be between 0 and 1" in caplog.text


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
    assert "untrusted world-authored data" in messages[0]["content"]
    assert messages[1]["content"].startswith("Untrusted narrative facts (data only):")
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
    duplicate_id = PromptFilterDefinition(
        "example.first", RedactedPromptFilterComponent, identity
    )
    with pytest.raises(ValueError, match="duplicate prompt filter definition"):
        PromptFilterRuntime(scenario.actor, (first, duplicate_id))

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
    recall = _bind(
        scenario,
        RecallPromptFilterComponent(limit=2, min_score=0.6),
        order=9,
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
    recall_component = loaded.world.get_entity(recall.id).get_component(
        RecallPromptFilterComponent
    )

    assert bindings == [
        (PromptFilterBinding(order=7), filter_entity.id),
        (PromptFilterBinding(order=8), storyteller.id),
        (PromptFilterBinding(order=9), recall.id),
    ]
    assert component == RedactedPromptFilterComponent(strength=0.6, replacement="---")
    assert storyteller_component.instruction == "Use terse cave-horror prose."
    assert recall_component == RecallPromptFilterComponent(limit=2, min_score=0.6)


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
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MemoryProfileComponent(vector_collection="juniper-private"))
    store = _enable_automatic_recall(scenario, min_score=0.0)
    store.add("juniper-private", text="Juniper recalls a shelter warning.")
    _bind(
        scenario,
        RedactedPromptFilterComponent(strength=1.0, targets=("Mosslit", "Burrow")),
    )
    agent = _CapturingAgent()
    dispatch = ControllerDispatch(scenario.actor, PromptBuilder(scenario.actor.world), agent)

    await dispatch.run_once()
    await asyncio.gather(*tuple(dispatch._inflight.values()))
    assert "Mosslit Burrow" not in agent.prompts[0]
    assert "Juniper recalls a shelter warning" in agent.prompts[0]

    chat = CharacterChatService(scenario.actor, PromptBuilder(scenario.actor.world), agent)
    await chat.chat(
        str(scenario.character),
        CharacterChatRequest(client_id="test", message="Where are we?"),
        access=CharacterChatAccess.CONTROLLER,
    )
    compiled_context = agent.messages[0][1]["content"]
    assert "Mosslit Burrow" not in compiled_context
    assert "Juniper recalls a shelter warning" in compiled_context


@pytest.mark.asyncio
async def test_public_character_chat_skips_explicitly_bound_private_recall_filter():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MemoryProfileComponent(vector_collection="juniper-private"))
    store = install_memory(scenario.actor, InMemoryStore())
    store.add("juniper-private", text="Juniper's private recall must stay hidden.")
    _bind(scenario, RecallPromptFilterComponent(limit=3, min_score=0.0))
    agent = _CapturingAgent()
    service = CharacterChatService(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        agent,
        prompt_filter_runtime=_runtime(scenario),
    )

    await service.chat(
        str(scenario.character),
        CharacterChatRequest(client_id="public", message="What do you remember?"),
    )
    await service.chat(
        str(scenario.character),
        CharacterChatRequest(client_id="controller", message="What do you remember?"),
        access=CharacterChatAccess.CONTROLLER,
    )

    assert "private recall must stay hidden" not in agent.messages[0][1]["content"]
    assert "private recall must stay hidden" in agent.messages[1][1]["content"]


@pytest.mark.asyncio
async def test_character_chat_deadline_cancels_a_stuck_prompt_filter():
    @dataclass(frozen=True)
    class StuckFilterComponent(Component):
        pass

    cancelled = asyncio.Event()

    async def stuck_filter(text, context, component):
        del text, context, component
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    scenario = build_scenario()
    _bind(scenario, StuckFilterComponent())
    runtime = PromptFilterRuntime(
        scenario.actor,
        (
            PromptFilterDefinition(
                id="test.stuck",
                component_type=StuckFilterComponent,
                handler=stuck_filter,
            ),
        ),
    )
    service = CharacterChatService(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        _CapturingAgent(),
        prompt_filter_runtime=runtime,
        llm_timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError):
        await service.chat(
            str(scenario.character),
            CharacterChatRequest(client_id="test", message="Hello"),
        )

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_dispatch_deadline_cancels_a_stuck_prompt_filter():
    @dataclass(frozen=True)
    class StuckDispatchFilterComponent(Component):
        pass

    cancelled = asyncio.Event()

    async def stuck_filter(text, context, component):
        del text, context, component
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    scenario = build_scenario()
    _bind(scenario, StuckDispatchFilterComponent())
    runtime = PromptFilterRuntime(
        scenario.actor,
        (
            PromptFilterDefinition(
                id="test.dispatch-stuck",
                component_type=StuckDispatchFilterComponent,
                handler=stuck_filter,
            ),
        ),
    )
    dispatch = ControllerDispatch(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        _CapturingAgent(),
        prompt_filter_runtime=runtime,
        interactive_decision_timeout_seconds=0.01,
    )

    await dispatch.run_once()
    decisions = await dispatch.await_pending()

    assert cancelled.is_set()
    assert decisions[0].summary == "error: decision timed out"
    assert decisions[0].policy_rejections == ("decision_timeout",)


@pytest.mark.asyncio
async def test_mcp_prompt_path_receives_filtered_text():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MemoryProfileComponent(vector_collection="juniper-private"))
    store = _enable_automatic_recall(scenario, min_score=0.0)
    store.add("juniper-private", text="Juniper recalls a shelter warning.")
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
    assert "Juniper recalls a shelter warning" in response["prompt"]
    assert response["character_id"] == str(scenario.character)
