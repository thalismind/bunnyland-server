"""Perspective query catalogue behavior and isolation."""

import pytest
from pydantic import RootModel, ValidationError

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    DomainEvent,
    EventVisibility,
    Lane,
    build_submitted_command,
    event_base,
)
from bunnyland.core.perspective import (
    V1_PERSPECTIVE_QUERIES,
    AvailableActionsInput,
    PerspectiveQueryDefinition,
    PerspectiveQueryRegistry,
)
from bunnyland.server.serialization import serialize_character_projection
from bunnyland.server.subscriptions import EventStream


class IntListOutput(RootModel[list[int]]):
    pass


def _register_v1(actor):
    for definition in V1_PERSPECTIVE_QUERIES:
        actor.perspective_queries.register(definition, owner="bunnyland.core_verbs")


def test_v1_catalogue_is_bounded_owned_and_projection_scoped(scenario):
    _register_v1(scenario.actor)

    actions = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "available_actions",
        {},
        actor_id=str(scenario.character),
    )
    targets = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "valid_targets",
        {"action": "move"},
        actor_id=str(scenario.character),
    )
    why = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "why_not",
        {"action": "move", "target": "entity_999999"},
        actor_id=str(scenario.character),
    )

    assert actions.owner == "bunnyland.core_verbs"
    assert actions.output_type == "AvailableActionsOutput"
    assert any(action["command_type"] == "move" for action in actions.result)
    assert targets.result["exit_id"] == [
        {"id": str(scenario.room_b), "label": f"north: {scenario.room_b}", "kind": "exit"}
    ]
    assert why.result["available"] is False
    assert why.result["reason"] == "target is not valid"
    serialized = actions.model_dump(mode="json")
    assert "components" not in str(serialized)
    assert "relationships" not in str(serialized)


async def test_what_changed_since_filters_by_epoch_and_character_visibility(scenario):
    _register_v1(scenario.actor)
    scenario.actor.event_stream = EventStream(scenario.actor)
    command = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
    )
    await scenario.actor.submit(command)
    await scenario.actor.tick(1.0)

    projection = serialize_character_projection(scenario.actor, str(scenario.character))
    assert {room.id for room in projection.known_rooms} == {
        str(scenario.room_a),
        str(scenario.room_b),
    }

    changed = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "what_changed_since",
        {"epoch": 0},
        actor_id=str(scenario.character),
    )
    assert any(
        update["data"]["event_type"] == "ActorMovedEvent" for update in changed.result["events"]
    )
    assert changed.result["complete"] is True
    assert changed.result["resync_required"] is False


def test_registry_rejects_unknown_query_and_spoofed_actor_argument(scenario):
    _register_v1(scenario.actor)
    with pytest.raises(ValueError, match="unknown perspective query"):
        scenario.actor.perspective_queries.execute(
            scenario.actor, "raw_relics", {}, actor_id=str(scenario.character)
        )

    result = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "available_actions",
        {"actor_id": "entity_999999"},
        actor_id=str(scenario.character),
    )
    assert result.actor_id == str(scenario.character)


def test_registry_catalogue_duplicate_limit_and_budget(monkeypatch, scenario):
    registry = PerspectiveQueryRegistry()
    definition = PerspectiveQueryDefinition(
        name="bounded",
        input_model=AvailableActionsInput,
        output_model=IntListOutput,
        result_limit=1,
        execute=lambda actor, request: ([1, 2], ("test",)),
    )
    registry.register(definition)
    assert [item.name for item in registry.definitions()] == ["bounded"]
    with pytest.raises(ValueError, match="duplicate perspective query"):
        registry.register(definition)
    result = registry.execute(scenario.actor, "bounded", {}, actor_id=str(scenario.character))
    assert result.result == [1]
    assert result.truncated is True

    import bunnyland.core.perspective as perspective

    moments = iter((0.0, 1.0))
    monkeypatch.setattr(perspective.time, "perf_counter", lambda: next(moments))
    with pytest.raises(TimeoutError, match="exceeded"):
        registry.execute(scenario.actor, "bounded", {}, actor_id=str(scenario.character))


def test_registry_enforces_visibility_indexes_and_output_schema(scenario):
    registry = PerspectiveQueryRegistry()
    registry.register(
        PerspectiveQueryDefinition(
            name="admin_only",
            input_model=AvailableActionsInput,
            output_model=IntListOutput,
            visibility="admin",
            execute=lambda actor, request: ([1], ()),
        )
    )
    with pytest.raises(PermissionError, match="requires admin access"):
        registry.execute(
            scenario.actor,
            "admin_only",
            {},
            actor_id=str(scenario.character),
            access="claim",
        )
    assert registry.execute(
        scenario.actor,
        "admin_only",
        {},
        actor_id=str(scenario.character),
        access="admin",
    ).result == [1]

    registry.register(
        PerspectiveQueryDefinition(
            name="indexed",
            input_model=AvailableActionsInput,
            output_model=IntListOutput,
            required_indexes=("characters_by_room",),
            execute=lambda actor, request: ([1], ()),
        )
    )
    with pytest.raises(RuntimeError, match="characters_by_room"):
        registry.execute(scenario.actor, "indexed", {}, actor_id=str(scenario.character))
    scenario.actor.perspective_index_names = {"characters_by_room"}
    assert registry.execute(
        scenario.actor, "indexed", {}, actor_id=str(scenario.character)
    ).result == [1]

    registry.register(
        PerspectiveQueryDefinition(
            name="bad_output",
            input_model=AvailableActionsInput,
            output_model=IntListOutput,
            execute=lambda actor, request: (["not-an-integer"], ()),
        )
    )
    with pytest.raises(ValidationError):
        registry.execute(scenario.actor, "bad_output", {}, actor_id=str(scenario.character))


def test_query_rejections_optional_target_and_unavailable_event_stream(scenario):
    _register_v1(scenario.actor)
    with pytest.raises(ValueError, match="unknown action"):
        scenario.actor.perspective_queries.execute(
            scenario.actor,
            "valid_targets",
            {"action": "not-an-action"},
            actor_id=str(scenario.character),
        )
    why = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "why_not",
        {"action": "move"},
        actor_id=str(scenario.character),
    )
    assert why.result["target_valid"] is None

    changed = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "what_changed_since",
        {"epoch": 0},
        actor_id=str(scenario.character),
    )
    assert changed.result["events"] == []
    assert changed.result["complete"] is False
    assert changed.result["resync_required"] is True
    assert "event_stream:unavailable" in changed.provenance

    scenario.actor.event_stream = EventStream(scenario.actor)
    scenario.actor.event_stream.record(
        DomainEvent(
            **event_base(
                1,
                event_id="room-event",
                visibility=EventVisibility.ROOM,
                room_id=str(scenario.room_a),
            )
        )
    )
    ghost = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "what_changed_since",
        {"epoch": 0},
        actor_id="entity_999999",
    )
    assert ghost.result["events"] == []

    visible = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "what_changed_since",
        {"epoch": 0},
        actor_id=str(scenario.character),
    )
    assert visible.result["events"][0]["data"]["event"]["event_id"] == "room-event"

    from bunnyland.core import CharacterComponent, spawn_entity

    unplaced = spawn_entity(scenario.actor.world, [CharacterComponent()])
    unplaced_result = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "what_changed_since",
        {"epoch": 0},
        actor_id=str(unplaced.id),
    )
    assert unplaced_result.result["events"] == []


def test_what_changed_since_preserves_occurrence_visibility_and_reports_history_gap(scenario):
    _register_v1(scenario.actor)
    stream = EventStream(scenario.actor, recent_limit=2)
    scenario.actor.event_stream = stream
    stream.record(
        DomainEvent(
            **event_base(
                1,
                event_id="seen-in-a",
                visibility=EventVisibility.ROOM,
                room_id=str(scenario.room_a),
            )
        )
    )

    character = scenario.actor.world.get_entity(scenario.character)
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(Contains, character.id)
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        character.id,
    )
    stream.record(
        DomainEvent(
            **event_base(
                2,
                event_id="seen-in-b",
                visibility=EventVisibility.ROOM,
                room_id=str(scenario.room_b),
            )
        )
    )

    changed = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "what_changed_since",
        {"epoch": 0},
        actor_id=str(scenario.character),
    )

    assert [message["data"]["event"]["event_id"] for message in changed.result["events"]] == [
        "seen-in-a",
        "seen-in-b",
    ]
    assert changed.result["complete"] is True

    stream.record(
        DomainEvent(
            **event_base(
                3,
                event_id="newest-in-b",
                visibility=EventVisibility.ROOM,
                room_id=str(scenario.room_b),
            )
        )
    )
    changed = scenario.actor.perspective_queries.execute(
        scenario.actor,
        "what_changed_since",
        {"epoch": 0},
        actor_id=str(scenario.character),
    )

    assert [message["data"]["event"]["event_id"] for message in changed.result["events"]] == [
        "seen-in-b",
        "newest-in-b",
    ]
    assert changed.result["complete"] is False
    assert changed.result["resync_required"] is True
    assert changed.result["available_after_epoch"] == 1
