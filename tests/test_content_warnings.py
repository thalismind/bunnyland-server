from __future__ import annotations

import pytest

from bunnyland.content_warnings import (
    normalize_content_flags,
    visible_content_flags,
    world_content_flags,
)
from bunnyland.core.components import WorldInfoComponent
from bunnyland.core.ecs import replace_component, spawn_entity
from bunnyland.core.world_actor import WorldActor
from bunnyland.plugins.model import Plugin, PolicyContribution
from bunnyland.plugins.registry import PluginRegistry
from bunnyland.server.app import create_app


def flagged_actor() -> WorldActor:
    actor = WorldActor()
    actor.plugins = PluginRegistry(
        (
            Plugin(
                id="example.flagged",
                name="Flagged",
                policy=PolicyContribution(boundary_tags=frozenset({"adult:violence"})),
            ),
        )
    )
    replace_component(
        actor._clock_entity,
        WorldInfoComponent(content_flags=frozenset({"admin:grim"})),
    )
    return actor


def test_world_content_flags_union_plugins_and_admin_world_flags():
    assert world_content_flags(flagged_actor()) == ("admin:grim", "adult:violence")
    assert world_content_flags(WorldActor()) == ()


def test_world_info_is_singleton_state_on_the_world_clock():
    actor = WorldActor()
    info_entities = list(
        actor.world.query().with_all([WorldInfoComponent]).execute_entities()
    )

    assert info_entities == [actor._clock_entity]
    assert actor.world_info == WorldInfoComponent()


def test_binding_a_saved_clock_initializes_missing_world_info():
    actor = WorldActor()
    actor._clock_entity.remove_component(WorldInfoComponent)

    actor.bind_clock()

    assert actor.world_info == WorldInfoComponent()


def test_binding_a_saved_clock_rejects_invalid_world_info_singletons():
    misplaced = WorldActor()
    misplaced._clock_entity.remove_component(WorldInfoComponent)
    spawn_entity(misplaced.world, [WorldInfoComponent()])
    with pytest.raises(RuntimeError, match="stored on the world clock"):
        misplaced.bind_clock()

    duplicated = WorldActor()
    spawn_entity(duplicated.world, [WorldInfoComponent()])
    with pytest.raises(RuntimeError, match="exactly one world info"):
        duplicated.bind_clock()


def test_content_flags_are_validated_sorted_and_filtered():
    assert normalize_content_flags(["pvp", "adult:violence", "pvp"]) == (
        "adult:violence",
        "pvp",
    )
    assert visible_content_flags(
        ["pvp", "adult:violence"], ["pvp"]
    ) == ("adult:violence",)
    with pytest.raises(ValueError, match="boundary scopes"):
        normalize_content_flags(["Not Valid"])


def test_public_world_content_contract_is_available_before_join():
    testclient = pytest.importorskip("fastapi.testclient")
    actor = flagged_actor()
    replace_component(
        actor._clock_entity,
        WorldInfoComponent(
            title="Clover City",
            description="Mind the foxes after dark.",
            content_flags=frozenset({"admin:grim"}),
        ),
    )
    client = testclient.TestClient(create_app(actor))

    response = client.get("/v1/public/world")

    assert response.status_code == 200
    assert response.json() == {
        "world_id": str(actor.world_id),
        "world_epoch": 0,
        "title": "Clover City",
        "description": "Mind the foxes after dark.",
        "content_flags": ["admin:grim", "adult:violence"],
    }
