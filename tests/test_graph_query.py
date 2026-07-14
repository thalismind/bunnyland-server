"""Behavioral coverage for bounded Relics graph queries."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bunnyland.core import (
    CharacterComponent,
    ComponentTerm,
    Contains,
    EdgeTerm,
    ExitTo,
    GraphQueryError,
    GraphQueryExecutor,
    GraphQuerySpec,
    IdentityComponent,
    RoomComponent,
    spawn_entity,
)
from bunnyland.plugins import PluginRegistry, bunnyland_plugins


def _executor() -> GraphQueryExecutor:
    return GraphQueryExecutor(PluginRegistry(bunnyland_plugins()))


def test_component_seed_fixed_binding_and_exact_fields(scenario):
    spec = GraphQuerySpec(
        terms=(
            ComponentTerm(
                variable="character",
                component="IdentityComponent",
                fields={"name": "Juniper", "kind": "character"},
            ),
        ),
        bindings={"character": str(scenario.character)},
        select=("character",),
    )

    assert _executor().execute(scenario.actor.world, spec) == [
        {"character": str(scenario.character)}
    ]
    assert _executor().execute(
        scenario.actor.world,
        spec.model_copy(
            update={
                "terms": (
                    ComponentTerm(
                        variable="character",
                        component="IdentityComponent",
                        fields={"name": "Hazel"},
                    ),
                )
            }
        ),
    ) == []


def test_outgoing_incoming_two_hop_and_cyclic_joins_are_stable(scenario):
    world = scenario.actor.world
    room_c = spawn_entity(world, [RoomComponent(title="East Tunnel")])
    world.get_entity(scenario.room_b).add_relationship(ExitTo(direction="east"), room_c.id)
    room_c.add_relationship(ExitTo(direction="west"), scenario.room_a)

    outgoing = GraphQuerySpec(
        terms=(EdgeTerm(source="source", edge="ExitTo", target="target"),),
        bindings={"source": str(scenario.room_a)},
        select=("target",),
    )
    incoming = outgoing.model_copy(
        update={"bindings": {"target": str(scenario.room_a)}, "select": ("source",)}
    )
    two_hop = GraphQuerySpec(
        terms=(
            EdgeTerm(source="start", edge="ExitTo", target="middle"),
            EdgeTerm(source="middle", edge="ExitTo", target="end"),
        ),
        bindings={"start": str(scenario.room_a)},
        select=("middle", "end"),
    )
    cycle = GraphQuerySpec(
        terms=(
            EdgeTerm(source="a", edge="ExitTo", target="b"),
            EdgeTerm(source="b", edge="ExitTo", target="c"),
            EdgeTerm(source="c", edge="ExitTo", target="a"),
        ),
        bindings={"a": str(scenario.room_a)},
        select=("a", "b", "c"),
    )

    assert _executor().execute(world, outgoing) == [{"target": str(scenario.room_b)}]
    assert _executor().execute(world, incoming) == [
        {"source": str(scenario.room_b)},
        {"source": str(room_c.id)},
    ]
    assert _executor().execute(world, two_hop) == [
        {"middle": str(scenario.room_b), "end": str(scenario.room_a)},
        {"middle": str(scenario.room_b), "end": str(room_c.id)},
    ]
    assert _executor().execute(world, cycle) == [
        {"a": str(scenario.room_a), "b": str(scenario.room_b), "c": str(room_c.id)}
    ]


def test_rows_are_deduplicated_and_sorted_by_selected_entity_ids(scenario):
    world = scenario.actor.world
    other = spawn_entity(
        world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    spec = GraphQuerySpec(
        terms=(
            ComponentTerm(variable="person", component="CharacterComponent"),
            ComponentTerm(variable="person", component="CharacterComponent"),
        ),
        select=("person",),
    )

    assert _executor().execute(world, spec) == sorted(
        [{"person": str(scenario.character)}, {"person": str(other.id)}],
        key=lambda row: row["person"],
    )

    room = world.get_entity(scenario.room_a)
    room.add_relationship(Contains(), other.id)
    edge_spec = GraphQuerySpec(
        terms=(EdgeTerm(source="room", edge="Contains", target="contents"),),
        select=("room",),
    )
    assert _executor().execute(world, edge_spec) == [{"room": str(scenario.room_a)}]


def test_unbound_edge_seed_self_join_and_unbound_field_filter(scenario):
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    room.add_relationship(ExitTo(direction="loop"), room.id)

    all_edges = GraphQuerySpec(
        terms=(EdgeTerm(source="source", edge="ExitTo", target="target"),),
        select=("source", "target"),
    )
    self_edges = GraphQuerySpec(
        terms=(EdgeTerm(source="room", edge="ExitTo", target="room"),),
        select=("room",),
    )
    hazel = GraphQuerySpec(
        terms=(
            ComponentTerm(
                variable="character",
                component="IdentityComponent",
                fields={"name": "missing"},
            ),
        ),
        select=("character",),
    )
    wrong_fixed_component = GraphQuerySpec(
        terms=(ComponentTerm(variable="room", component="CharacterComponent"),),
        bindings={"room": str(scenario.room_a)},
        select=("room",),
    )

    assert {tuple(row.values()) for row in _executor().execute(world, all_edges)} >= {
        (str(scenario.room_a), str(scenario.room_a)),
        (str(scenario.room_a), str(scenario.room_b)),
    }
    assert _executor().execute(world, self_edges) == [{"room": str(scenario.room_a)}]
    assert _executor().execute(world, hazel) == []
    assert _executor().execute(world, wrong_fixed_component) == []


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        (
            GraphQuerySpec(
                terms=(ComponentTerm(variable="x", component="MissingComponent"),),
                select=("x",),
            ),
            "unknown component type",
        ),
        (
            GraphQuerySpec(
                terms=(EdgeTerm(source="x", edge="MissingEdge", target="y"),),
                select=("x",),
            ),
            "unknown edge type",
        ),
        (
            GraphQuerySpec(
                terms=(ComponentTerm(variable="x", component="CharacterComponent"),),
                bindings={"x": "entity_999999"},
                select=("x",),
            ),
            "fixed binding 'x' refers to missing entity",
        ),
    ],
)
def test_executor_rejects_unknown_types_and_missing_fixed_entities(scenario, spec, message):
    with pytest.raises(GraphQueryError, match=message):
        _executor().execute(scenario.actor.world, spec)


def test_spec_rejects_undefined_disconnected_duplicate_and_oversized_shapes():
    with pytest.raises(ValidationError, match="undefined"):
        GraphQuerySpec(
            terms=(ComponentTerm(variable="x", component="CharacterComponent"),),
            select=("y",),
        )
    with pytest.raises(ValidationError, match="disconnected"):
        GraphQuerySpec(
            terms=(
                ComponentTerm(variable="x", component="CharacterComponent"),
                ComponentTerm(variable="y", component="RoomComponent"),
            ),
            select=("x", "y"),
        )
    with pytest.raises(ValidationError, match="must be unique"):
        GraphQuerySpec(
            terms=(ComponentTerm(variable="x", component="CharacterComponent"),),
            select=("x", "x"),
        )
    with pytest.raises(ValidationError, match="maximum is 6"):
        GraphQuerySpec(
            terms=tuple(
                EdgeTerm(source=f"x{index}", edge="ExitTo", target=f"x{index + 1}")
                for index in range(6)
            ),
            select=("x0",),
        )
    with pytest.raises(ValidationError):
        GraphQuerySpec(
            terms=tuple(
                ComponentTerm(variable="x", component="CharacterComponent")
                for _index in range(9)
            ),
            select=("x",),
        )


def test_executor_rejects_result_and_candidate_expansion_budget_exhaustion(scenario):
    world = scenario.actor.world
    for index in range(101):
        spawn_entity(world, [IdentityComponent(name=f"extra {index}", kind="item")])
    too_many_results = GraphQuerySpec(
        terms=(ComponentTerm(variable="item", component="IdentityComponent"),),
        select=("item",),
    )
    with pytest.raises(GraphQueryError, match="100 result budget"):
        _executor().execute(world, too_many_results)

    sources = [
        spawn_entity(world, [RoomComponent(title=f"source {index}")])
        for index in range(101)
    ]
    targets = [spawn_entity(world) for _index in range(100)]
    for source in sources:
        for target in targets:
            source.add_relationship(Contains(), target.id)
    expansion_budget = GraphQuerySpec(
        terms=(
            ComponentTerm(variable="source", component="RoomComponent"),
            EdgeTerm(source="source", edge="Contains", target="target"),
            ComponentTerm(
                variable="target",
                component="IdentityComponent",
                fields={"name": "never present"},
            ),
        ),
        select=("source",),
    )
    with pytest.raises(GraphQueryError, match="10000 candidate expansions"):
        _executor().execute(world, expansion_budget)
