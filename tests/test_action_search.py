from __future__ import annotations

import sys

import pytest

import bunnyland.server.action_search as action_search_module
from bunnyland.core.actions import (
    ActionArgument,
    ActionDefinition,
    ActionEffort,
    ActionExample,
    ActionPattern,
    effort_cost,
)
from bunnyland.core.commands import CommandCost
from bunnyland.server.action_search import (
    ActionSearchEmbedding,
    ChromaActionSearchIndex,
    _tokens,
    smart_action_search,
)


def test_action_search_embedding_is_deterministic_and_chroma_compatible():
    embedding = ActionSearchEmbedding()

    walk = embedding(["walk north"])[0]
    repeated = embedding.embed_query(["walk north"])[0]
    blank = embedding([""])[0]

    assert walk == repeated
    assert len(walk) == 64
    assert any(value > 0.0 for value in walk)
    assert blank[0] == 0.001
    assert ActionSearchEmbedding.name() == "bunnyland-action-search"
    assert isinstance(ActionSearchEmbedding.build_from_config({}), ActionSearchEmbedding)
    assert embedding.get_config() == {}
    assert embedding.default_space() == "l2"
    assert embedding.supported_spaces() == ["l2"]
    assert embedding.is_legacy() is False


def test_chroma_action_search_index_populates_and_reuses_catalogue_collection():
    class FakeCollection:
        def __init__(self) -> None:
            self.ids: list[str] = []
            self.documents: list[str] = []
            self.metadatas: list[dict] = []
            self.upsert_count = 0

        def upsert(self, *, ids, documents, metadatas):
            self.ids = list(ids)
            self.documents = list(documents)
            self.metadatas = list(metadatas)
            self.upsert_count += 1

        def query(self, *, query_texts, n_results):
            assert query_texts == ["look at the shiny thing"]
            assert n_results == 2
            return {"ids": [["inspect", "missing-action", "move"]]}

    class FakeClient:
        def __init__(self) -> None:
            self.collection = FakeCollection()
            self.collection_names: list[str] = []

        def get_or_create_collection(self, *, name, **kwargs):
            self.collection_names.append(name)
            assert kwargs["embedding_function"] is embedding
            return self.collection

    embedding = ActionSearchEmbedding()
    client = FakeClient()
    index = ChromaActionSearchIndex(client=client, embedding_function=embedding)
    definitions = (
        ActionDefinition(
            command_type="move",
            title="Move",
            description="Travel through an exit.",
            natural_patterns=(ActionPattern("go {direction}"),),
        ),
        ActionDefinition(
            command_type="inspect",
            title="Inspect",
            description="Look closely at something.",
            arguments={
                "target_id": ActionArgument(
                    title="Target", kind="entity", description="Thing to inspect."
                )
            },
            examples=(ActionExample("inspect lantern"),),
            natural_patterns=(ActionPattern("look at {target_id}"),),
        ),
    )

    assert index.search((), query="anything") == []

    ranked = index.search(definitions, query="look at the shiny thing")
    ranked_again = index.search(definitions, query="look at the shiny thing")

    assert [definition.command_type for definition in ranked] == ["inspect", "move"]
    assert [definition.command_type for definition in ranked_again] == ["inspect", "move"]
    assert client.collection.upsert_count == 1
    assert client.collection.ids == ["move", "inspect"]
    assert client.collection.metadatas == [
        {"command_type": "move"},
        {"command_type": "inspect"},
    ]
    assert "look at {target_id}" in "\n".join(client.collection.documents)
    assert client.collection_names[0].startswith("bunnyland-action-verbs-")


def test_tokens_skips_non_alias_token_in_the_middle_of_text():
    # "look" aliases to itself (alias == token) so it adds no synonym, and it is
    # followed by another token, exercising the loop-continue branch (52->49).
    tokens = _tokens("look gizmo north")

    assert tokens == ["look", "gizmo", "north", "move"]
    # "look" added no alias (alias == token), "gizmo" has no alias, "north" -> "move".
    assert tokens.count("look") == 1


def test_smart_action_search_reuses_the_module_level_index():
    definitions = (
        ActionDefinition(
            command_type="move",
            title="Move",
            description="Travel through an exit.",
            natural_patterns=(ActionPattern("go {direction}"),),
        ),
    )

    class RecordingIndex:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def search(self, defs, *, query):
            self.calls.append(query)
            return list(defs)

    recording = RecordingIndex()
    previous = action_search_module._SMART_ACTION_INDEX
    action_search_module._SMART_ACTION_INDEX = recording
    try:
        result = smart_action_search(definitions, query="travel somewhere")
    finally:
        action_search_module._SMART_ACTION_INDEX = previous

    # The existing singleton was reused (branch 198->200 false), no new index built.
    assert result == list(definitions)
    assert recording.calls == ["travel somewhere"]


def test_chroma_action_search_index_missing_extra_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "chromadb", None)
    with pytest.raises(RuntimeError, match="smart action search requires the 'chroma' extra"):
        ChromaActionSearchIndex()


def test_action_effort_builds_typed_wire_costs_and_rejects_invalid_costs():
    assert effort_cost(action=ActionEffort.EPIC) == CommandCost(action=5)
    assert effort_cost(focus=ActionEffort.MAJOR) == CommandCost(focus=3)

    with pytest.raises(ValueError, match="focus effort"):
        effort_cost(focus=ActionEffort.EPIC)
    with pytest.raises(ValueError, match="ActionEffort"):
        ActionDefinition(command_type="invalid", cost=CommandCost(action=4))
    with pytest.raises(ValueError, match="focus cost"):
        ActionDefinition(command_type="invalid-focus", cost=CommandCost(focus=5))
