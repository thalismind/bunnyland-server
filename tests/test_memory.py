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
    NotesSearchedEvent,
    NoteTakenEvent,
    ReflectionCreatedEvent,
)
from bunnyland.memory import InMemoryStore, install_memory

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


def test_inmemory_store_vector_falls_back_to_keyword():
    store = InMemoryStore()
    store.add("c", text="the basin water is unsafe", created_at_epoch=1)
    store.add("c", text="berries are tasty", created_at_epoch=2)
    results = store.search("c", query="water", mode="vector", limit=5)
    assert len(results) == 1
    assert "basin" in results[0].text
