"""Tests for private notes and remember/search (focus lane)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    ActionPointsComponent,
    CommandCost,
    FocusPointsComponent,
    Lane,
    MemoryProfileComponent,
    OnInsufficientPoints,
    build_submitted_command,
    replace_component,
)
from bunnyland.core.events import (
    CommandRejectedEvent,
    NoteForgottenEvent,
    NotesSearchedEvent,
    NoteTakenEvent,
    ReflectionCreatedEvent,
)
from bunnyland.core.handlers.base import HandlerContext
from bunnyland.memory import InMemoryStore, install_memory
from bunnyland.memory.chroma import ChromaMemoryStore
from bunnyland.memory.handlers import (
    ForgetHandler,
    ReflectHandler,
    ReflectionLoopConsequence,
    RememberHandler,
    TakeNoteHandler,
)

HOUR = 3600.0


def memory_scenario():
    scenario = build_scenario()
    store = install_memory(scenario.actor, InMemoryStore())
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(MemoryProfileComponent(vector_collection="juniper"))
    return scenario, store


def note_cmd(scenario, text, tags=()):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take-note",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload={"text": text, "tags": list(tags)},
    )


def remember_cmd(scenario, query=None, mode="recent", limit=5):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="remember",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload={"query": query, "mode": mode, "limit": limit},
    )


def forget_cmd(scenario, note_id):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="forget",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload={"note_id": note_id},
    )


def reflect_cmd(scenario, text="", query=None, mode="recent", limit=5):
    payload = {"text": text, "query": query, "mode": mode, "limit": limit}
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="reflect",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload=payload,
    )


def shared_note_cmd(scenario, text, collection="burrow-board"):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take-note",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload={"text": text, "scope": "shared", "collection": collection},
    )


def shared_remember_cmd(scenario, query=None, collection="burrow-board"):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="remember",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload={
            "query": query,
            "mode": "keyword" if query else "recent",
            "limit": 5,
            "scope": "shared",
            "collection": collection,
        },
    )


def handler_context(scenario):
    return HandlerContext(scenario.actor.world, scenario.actor.epoch)


def with_character_id(command, scenario, character_id):
    return build_submitted_command(
        character_id=character_id,
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command.command_type,
        cost=command.cost,
        lane=command.lane,
        payload=command.payload,
    )


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


async def test_take_note_stores_privately_and_spends_focus():
    scenario, store = memory_scenario()
    notes = collect(scenario.actor, NoteTakenEvent)
    char = scenario.actor.world.get_entity(scenario.character)
    focus_before = char.get_component(FocusPointsComponent).current

    await scenario.actor.submit(note_cmd(scenario, "The basin water tastes strange."))
    await scenario.actor.tick(0.0)

    assert len(notes) == 1
    assert notes[0].visibility == "private"
    # focus spent (1), action untouched
    assert char.get_component(FocusPointsComponent).current == focus_before - 1
    assert char.get_component(ActionPointsComponent).current == 5.0
    # stored in the private collection
    assert len(store.search("juniper", mode="recent")) == 1


async def test_remember_returns_recent_notes_privately():
    scenario, _store = memory_scenario()
    searched = collect(scenario.actor, NotesSearchedEvent)

    await scenario.actor.submit(note_cmd(scenario, "Hazel distrusts the basin."))
    await scenario.actor.submit(note_cmd(scenario, "Berries grow by the north tunnel."))
    await scenario.actor.tick(0.0)

    await scenario.actor.submit(remember_cmd(scenario, mode="recent", limit=5))
    await scenario.actor.tick(0.0)

    assert searched[-1].visibility == "private"
    assert "Berries grow by the north tunnel." in searched[-1].results
    assert "Hazel distrusts the basin." in searched[-1].results
    assert len(searched[-1].note_ids) == 2


async def test_remember_keyword_filters_results():
    scenario, _store = memory_scenario()
    searched = collect(scenario.actor, NotesSearchedEvent)

    await scenario.actor.submit(note_cmd(scenario, "Hazel distrusts the basin water."))
    await scenario.actor.submit(note_cmd(scenario, "The north tunnel is cold."))
    await scenario.actor.tick(0.0)

    await scenario.actor.submit(remember_cmd(scenario, query="basin", mode="keyword"))
    await scenario.actor.tick(0.0)

    results = searched[-1].results
    assert any("basin" in r for r in results)
    assert all("tunnel" not in r for r in results)


async def test_forget_removes_note_by_id():
    scenario, store = memory_scenario()
    taken = collect(scenario.actor, NoteTakenEvent)
    forgotten = collect(scenario.actor, NoteForgottenEvent)

    await scenario.actor.submit(note_cmd(scenario, "The key is under the flowerpot."))
    await scenario.actor.tick(0.0)
    note_id = taken[-1].note_id

    await scenario.actor.submit(forget_cmd(scenario, note_id))
    await scenario.actor.tick(0.0)

    assert forgotten[-1].note_id == note_id
    assert store.search("juniper", mode="recent") == []


async def test_forget_rejects_unknown_note_id():
    scenario, _store = memory_scenario()
    rejects = collect(scenario.actor, CommandRejectedEvent)

    await scenario.actor.submit(forget_cmd(scenario, "missing-note"))
    await scenario.actor.tick(0.0)

    assert any(r.reason == "note not found" for r in rejects)


async def test_shared_notes_use_authorized_shared_collection():
    scenario, store = memory_scenario()
    char = scenario.actor.world.get_entity(scenario.character)
    replace_component(
        char,
        MemoryProfileComponent(
            vector_collection="juniper", shared_collections=("burrow-board",)
        ),
    )
    taken = collect(scenario.actor, NoteTakenEvent)
    searched = collect(scenario.actor, NotesSearchedEvent)

    await scenario.actor.submit(shared_note_cmd(scenario, "Basin water is for everyone."))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(shared_remember_cmd(scenario, query="basin"))
    await scenario.actor.tick(0.0)

    assert taken[-1].scope == "shared"
    assert taken[-1].collection == "burrow-board"
    assert searched[-1].results == ("Basin water is for everyone.",)
    assert len(store.search("juniper", mode="recent")) == 0


async def test_shared_notes_reject_unavailable_collection():
    scenario, _store = memory_scenario()
    rejects = collect(scenario.actor, CommandRejectedEvent)

    await scenario.actor.submit(shared_note_cmd(scenario, "secret", collection="unknown"))
    await scenario.actor.tick(0.0)

    assert any(r.reason == "shared collection is not available" for r in rejects)


async def test_reflect_summarizes_recent_notes_into_private_memory():
    scenario, store = memory_scenario()
    reflected = collect(scenario.actor, ReflectionCreatedEvent)
    profile_before = scenario.actor.world.get_entity(scenario.character).get_component(
        MemoryProfileComponent
    )

    await scenario.actor.submit(note_cmd(scenario, "Hazel distrusts the basin."))
    await scenario.actor.submit(note_cmd(scenario, "The north tunnel is cold."))
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(reflect_cmd(scenario, limit=2))
    await scenario.actor.tick(0.0)

    assert reflected[-1].visibility == "private"
    assert "Reflection:" in reflected[-1].text
    assert "north tunnel" in reflected[-1].text
    assert len(reflected[-1].source_note_ids) == 2
    entries = store.search("juniper", query="reflection", mode="keyword")
    assert entries[0].source == "reflection"
    profile_after = scenario.actor.world.get_entity(scenario.character).get_component(
        MemoryProfileComponent
    )
    assert profile_after.last_reflection_epoch >= profile_before.last_reflection_epoch


async def test_reflect_rejects_without_notes_or_text():
    scenario, _store = memory_scenario()
    rejects = collect(scenario.actor, CommandRejectedEvent)

    await scenario.actor.submit(reflect_cmd(scenario))
    await scenario.actor.tick(0.0)

    assert any(r.reason == "nothing to reflect on" for r in rejects)


async def test_reflection_loop_creates_retrievable_private_memory():
    scenario, store = memory_scenario()
    reflected = collect(scenario.actor, ReflectionCreatedEvent)
    scenario.actor.register_consequence(
        ReflectionLoopConsequence(store, interval_seconds=0, min_entries=2, limit=2)
    )

    await scenario.actor.submit(note_cmd(scenario, "Hazel found fresh tracks."))
    await scenario.actor.submit(note_cmd(scenario, "The north bridge cracked."))
    await scenario.actor.tick(HOUR)

    assert len(reflected) == 1
    assert reflected[0].visibility == "private"
    assert "Hazel found fresh tracks" in reflected[0].text
    assert "north bridge cracked" in reflected[0].text
    assert len(reflected[0].source_note_ids) == 2

    results = store.search("juniper", query="bridge", mode="keyword", limit=3)
    assert any(entry.source == "reflection" for entry in results)


async def test_reflection_loop_waits_for_interval_and_new_source_notes():
    scenario, store = memory_scenario()
    reflected = collect(scenario.actor, ReflectionCreatedEvent)
    scenario.actor.register_consequence(
        ReflectionLoopConsequence(
            store,
            interval_seconds=int(HOUR),
            min_entries=2,
            limit=2,
            scan_limit=5,
        )
    )

    await scenario.actor.submit(note_cmd(scenario, "The lantern went out."))
    await scenario.actor.submit(note_cmd(scenario, "Hazel carried a spare wick."))
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(0.0)

    assert len(reflected) == 1

    await scenario.actor.tick(HOUR)
    assert len(reflected) == 1

    await scenario.actor.submit(note_cmd(scenario, "The wick fit the lantern."))
    await scenario.actor.submit(note_cmd(scenario, "Hazel trusted the repair."))
    await scenario.actor.tick(HOUR)

    assert len(reflected) == 2
    assert "spare wick" not in reflected[1].text
    assert "trusted the repair" in reflected[1].text


async def test_focus_lane_note_does_not_consume_world_action():
    # A note (focus) and a move (world) can both run in the same tick.
    scenario, _store = memory_scenario()  # build_scenario already registered MoveHandler
    move = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
    )
    await scenario.actor.submit(note_cmd(scenario, "Heading north now."))
    await scenario.actor.submit(move)
    await scenario.actor.tick(HOUR)

    # The note was stored and the move happened in the same tick.
    assert scenario.character_room() == scenario.room_b


async def test_note_without_memory_profile_is_rejected():
    scenario = build_scenario()
    install_memory(scenario.actor, InMemoryStore())  # no MemoryProfileComponent added
    from bunnyland.core.events import CommandRejectedEvent

    rejects = collect(scenario.actor, CommandRejectedEvent)
    cmd = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take-note",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        on_insufficient_points=OnInsufficientPoints.DENY,
        payload={"text": "orphan note"},
    )
    await scenario.actor.submit(cmd)
    await scenario.actor.tick(0.0)

    assert any(r.reason == "character has no memory profile" for r in rejects)


def test_memory_handlers_reject_invalid_character_ids():
    scenario, store = memory_scenario()
    ctx = handler_context(scenario)

    handlers = (
        (TakeNoteHandler(store), note_cmd(scenario, "note")),
        (RememberHandler(store), remember_cmd(scenario)),
        (ForgetHandler(store), forget_cmd(scenario, "note-1")),
        (ReflectHandler(store), reflect_cmd(scenario, text="x")),
    )
    for handler, command in handlers:
        invalid = with_character_id(command, scenario, "not-an-id")
        missing = with_character_id(command, scenario, "entity_999")

        assert handler.execute(ctx, invalid).reason == "invalid character id"
        assert handler.execute(ctx, missing).reason == "character does not exist"


def test_take_note_rejects_blank_text_and_bad_memory_scopes():
    scenario, store = memory_scenario()
    ctx = handler_context(scenario)
    handler = TakeNoteHandler(store)

    assert handler.execute(ctx, note_cmd(scenario, "   ")).reason == "nothing to note"

    bad_scope = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take-note",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload={"text": "note", "scope": "guild"},
    )
    assert handler.execute(ctx, bad_scope).reason == "memory scope must be private or shared"

    shared_missing = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take-note",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload={"text": "note", "scope": "shared"},
    )
    assert handler.execute(ctx, shared_missing).reason == "shared collection is required"


def test_shared_collection_defaults_when_profile_has_one_shared_collection():
    scenario, store = memory_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    replace_component(
        character,
        MemoryProfileComponent(
            vector_collection="juniper",
            shared_collections=("burrow-board",),
        ),
    )
    ctx = handler_context(scenario)
    command = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take-note",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload={"text": "shared by default", "scope": "shared"},
    )

    result = TakeNoteHandler(store).execute(ctx, command)

    assert result.ok is True
    assert result.events[0].collection == "burrow-board"
    assert result.events[0].scope == "shared"


def test_remember_and_forget_reject_collection_errors_and_missing_note_ids():
    scenario, store = memory_scenario()
    ctx = handler_context(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.remove_component(MemoryProfileComponent)

    assert RememberHandler(store).execute(ctx, remember_cmd(scenario)).reason == (
        "character has no memory profile"
    )

    character.add_component(MemoryProfileComponent(vector_collection="juniper"))
    assert ForgetHandler(store).execute(ctx, forget_cmd(scenario, " ")).reason == (
        "note id is required"
    )

    bad_shared = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="forget",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload={"note_id": "note-1", "scope": "shared", "collection": "unknown"},
    )
    assert ForgetHandler(store).execute(ctx, bad_shared).reason == (
        "shared collection is not available"
    )


def test_reflect_rejects_missing_profile_nonpositive_limit_and_accepts_explicit_text():
    scenario, store = memory_scenario()
    ctx = handler_context(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.remove_component(MemoryProfileComponent)

    assert ReflectHandler(store).execute(ctx, reflect_cmd(scenario, text="x")).reason == (
        "character has no memory profile"
    )

    character.add_component(MemoryProfileComponent(vector_collection="juniper"))
    assert ReflectHandler(store).execute(ctx, reflect_cmd(scenario, limit=0)).reason == (
        "reflection limit must be positive"
    )

    result = ReflectHandler(store).execute(ctx, reflect_cmd(scenario, text="  I learned.  "))

    assert result.ok is True
    assert result.events[0].text == "I learned."
    assert result.events[0].source_note_ids == ()
    assert store.search("juniper", query="I learned", mode="keyword")[0].source == "reflection"


def test_inmemory_store_vector_falls_back_to_keyword():
    store = InMemoryStore()
    store.add("c", text="the basin water is unsafe", created_at_epoch=1)
    store.add("c", text="berries are tasty", created_at_epoch=2)
    results = store.search("c", query="water", mode="vector", limit=5)
    assert len(results) == 1
    assert "basin" in results[0].text


def test_chroma_store_delete_removes_existing_note():
    class FakeCollection:
        def __init__(self) -> None:
            self.ids: list[str] = []
            self.documents: list[str] = []
            self.metadatas: list[dict] = []

        def add(self, *, ids, documents, metadatas):
            self.ids.extend(ids)
            self.documents.extend(documents)
            self.metadatas.extend(metadatas)

        def get(self, ids=None, include=None):
            del include
            selected = set(ids or self.ids)
            rows = [
                (id_, doc, meta)
                for id_, doc, meta in zip(
                    self.ids, self.documents, self.metadatas, strict=False
                )
                if id_ in selected
            ]
            return {
                "ids": [row[0] for row in rows],
                "documents": [row[1] for row in rows],
                "metadatas": [row[2] for row in rows],
            }

        def delete(self, *, ids):
            selected = set(ids)
            rows = [
                (id_, doc, meta)
                for id_, doc, meta in zip(
                    self.ids, self.documents, self.metadatas, strict=False
                )
                if id_ not in selected
            ]
            self.ids = [row[0] for row in rows]
            self.documents = [row[1] for row in rows]
            self.metadatas = [row[2] for row in rows]

    class FakeClient:
        def __init__(self) -> None:
            self.collection = FakeCollection()

        def get_or_create_collection(self, *, name, **kwargs):
            del name, kwargs
            return self.collection

    store = ChromaMemoryStore(client=FakeClient())
    entry = store.add("c", text="the basin water is unsafe", created_at_epoch=1)

    assert store.delete("c", entry.id) is True
    assert store.search("c", mode="recent") == []
    assert store.delete("c", entry.id) is False
