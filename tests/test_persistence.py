"""Tests for world persistence (spec 26): save, reload, autosave, and provenance."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

import pytest
from pydantic import BaseModel
from relics import EntityId, World

from bunnyland.core import (
    ContainmentMode,
    Contains,
    ExitTo,
    RegionComponent,
    RoomComponent,
    WorldActor,
    container_of,
    spawn_entity,
)
from bunnyland.core.components import IdentityComponent
from bunnyland.core.ecs import contents
from bunnyland.engine import GameLoop
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent, ToolCall
from bunnyland.mechanics.needs import HungerComponent
from bunnyland.mechanics.toonsim import ToonRoomComponent
from bunnyland.offline import advance_offline_life
from bunnyland.persistence import (
    WorldMeta,
    YAMLPersistenceDriver,
    _format_for_path,
    load_world,
    save_world,
    type_registries,
)
from bunnyland.plugins import apply_plugins, bunnyland_plugins
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.worldgen import StubWorldBuilder, instantiate


class _YamlFlavor(Enum):
    SWEET = "sweet"


class _YamlNestedModel(BaseModel):
    label: str


@dataclass
class _YamlNestedData:
    flavor: _YamlFlavor
    hidden: str
    _private: str = "ignored"


async def _build_and_play():
    """A fully wired stub world after a couple of in-place actions (no movement)."""
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    result = await instantiate(actor, await StubWorldBuilder().propose("a quiet marsh"))
    # Hazel eats and takes the paper but stays in the burrow.
    agent = ScriptedAgent(
        [
            ToolCall("eat", {"item_id": "three berries"}),
            ToolCall("take", {"item_id": "a scrap of paper"}),
        ]
    )
    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), agent)
    await GameLoop(actor, dispatch).run(max_ticks=3)
    return actor, result


def _inventory(actor, character_id):
    return sorted(
        actor.world.get_entity(c).get_component(IdentityComponent).name
        for c in contents(actor.world.get_entity(character_id))
    )


def test_format_for_path_respects_explicit_format_and_suffixes(tmp_path):
    assert _format_for_path(tmp_path / "world.yml", None) == "yaml"
    assert _format_for_path(tmp_path / "world.yaml", None) == "yaml"
    assert _format_for_path(tmp_path / "world.json", None) == "json"
    assert _format_for_path(tmp_path / "world.yml", "json") == "json"
    assert _format_for_path(tmp_path / "world.json", "yaml") == "yaml"

    with pytest.raises(ValueError, match="unknown persistence format"):
        _format_for_path(tmp_path / "world.json", "toml")


async def test_save_reload_preserves_world(tmp_path):
    actor, result = await _build_and_play()
    hazel = result.characters["hazel"]
    before_room = container_of(actor.world.get_entity(hazel))
    before_inventory = _inventory(actor, hazel)
    before_epoch = actor.epoch
    before_hunger = actor.world.get_entity(hazel).get_component(HungerComponent).meter.value

    path = tmp_path / "world.json"
    save_world(actor, path, meta=WorldMeta(seed="a quiet marsh", prompt="p", generator="oneshot"))
    actor2, meta = load_world(path, plugins=bunnyland_plugins())

    # Topology, containment, the clock, and nested value objects all survive.
    assert container_of(actor2.world.get_entity(hazel)) == before_room
    assert _inventory(actor2, hazel) == before_inventory
    assert "a scrap of paper" in before_inventory
    assert actor2.epoch == before_epoch
    hunger = actor2.world.get_entity(hazel).get_component(HungerComponent)
    assert hunger.meter.value == before_hunger  # Meter is a nested value object

    # Provenance is restored.
    assert (meta.seed, meta.prompt, meta.generator) == ("a quiet marsh", "p", "oneshot")
    assert meta.saved_at_epoch == before_epoch


async def test_reloaded_world_keeps_playing(tmp_path):
    actor, result = await _build_and_play()
    hazel = result.characters["hazel"]
    path = tmp_path / "world.json"
    save_world(actor, path, meta=WorldMeta(seed="s"))

    actor2, _meta = load_world(path, plugins=bunnyland_plugins())
    # The controller edge (and its generation) survived, so dispatch can drive Hazel.
    agent = ScriptedAgent([ToolCall("move", {"direction": "north"})])
    dispatch = ControllerDispatch(actor2, PromptBuilder(actor2.world), agent)
    await GameLoop(actor2, dispatch).run(max_ticks=2)

    assert container_of(actor2.world.get_entity(hazel)) == result.rooms["tunnel"]


async def test_offline_life_advances_reloaded_world_and_persists_changes(tmp_path):
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    result = await instantiate(actor, await StubWorldBuilder().propose("a quiet marsh"))
    hazel = result.characters["hazel"]
    path = tmp_path / "world.json"
    save_world(actor, path, meta=WorldMeta(seed="offline"))

    loaded, meta = load_world(path, plugins=bunnyland_plugins())
    ticks = await advance_offline_life(loaded, 2 * 3600.0, max_ticks=2)
    save_world(loaded, path, meta=meta)
    reloaded, _meta = load_world(path, plugins=bunnyland_plugins())

    assert ticks == 2
    assert "a scrap of paper" in _inventory(reloaded, hazel)
    assert reloaded.epoch > actor.epoch


async def test_offline_life_is_bounded_by_max_ticks(tmp_path):
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    await instantiate(actor, await StubWorldBuilder().propose("a quiet marsh"))

    ticks = await advance_offline_life(actor, 24 * 3600.0, step_seconds=3600.0, max_ticks=3)

    assert ticks == 3
    assert actor.epoch == 3 * 3600


async def test_save_file_embeds_ecs_and_provenance(tmp_path):
    actor, _result = await _build_and_play()
    path = tmp_path / "world.json"
    save_world(actor, path, meta=WorldMeta(seed="marsh", prompt="p", generator="recursive"))

    data = json.loads(path.read_text())
    # One file holds both the Relics ECS sections and the bunnyland provenance.
    assert {"components", "entities", "relationships", "bunnyland"} <= set(data)
    assert data["bunnyland"]["seed"] == "marsh"
    assert data["bunnyland"]["generator"] == "recursive"


async def test_yaml_save_file_uses_compact_entity_records(tmp_path):
    actor, _result = await _build_and_play()
    path = tmp_path / "world.yaml"
    save_world(actor, path, meta=WorldMeta(seed="marsh", prompt="p", generator="recursive"))

    text = path.read_text()
    assert "__metadata__:" in text
    assert "__bunnyland__:" in text
    assert "IdentityComponent:" in text
    assert "Contains -> " in text
    assert '"seed": "marsh"' in text
    assert '"generator": "recursive"' in text
    assert '"name": "a scrap of paper"' in text
    assert '"kind": "paper"' in text


async def test_yaml_save_reload_preserves_world(tmp_path):
    actor, result = await _build_and_play()
    hazel = result.characters["hazel"]
    before_room = container_of(actor.world.get_entity(hazel))
    before_inventory = _inventory(actor, hazel)
    before_epoch = actor.epoch
    before_hunger = actor.world.get_entity(hazel).get_component(HungerComponent).meter.value

    path = tmp_path / "world.yaml"
    save_world(actor, path, meta=WorldMeta(seed="a quiet marsh", prompt="p", generator="oneshot"))
    actor2, meta = load_world(path, plugins=bunnyland_plugins())

    assert container_of(actor2.world.get_entity(hazel)) == before_room
    assert _inventory(actor2, hazel) == before_inventory
    assert actor2.epoch == before_epoch
    hunger = actor2.world.get_entity(hazel).get_component(HungerComponent)
    assert hunger.meter.value == before_hunger
    assert (meta.seed, meta.prompt, meta.generator) == ("a quiet marsh", "p", "oneshot")


def test_yaml_driver_defers_edge_resolution(tmp_path):
    path = tmp_path / "manual.yaml"
    path.write_text(
        """
__metadata__: {"version": "1.0", "epoch": 7}
__prefabs__: {"entity": {"components": {}}}
entity_1:
  IdentityComponent: {"name": "Source \\"quoted\\" ☃", "kind": "room", "tags": ["start"]}
  ExitTo -> entity_2: {
    "direction": "north",
    "label": "North",
    "locked": false,
    "hidden": false,
    "action_cost": 1
  }
entity_2:
  IdentityComponent: {"name": "Target", "kind": "room", "tags": []}
""".lstrip()
    )
    components, edges = type_registries(bunnyland_plugins())
    world = World()
    YAMLPersistenceDriver().load(world, path, components, edges)

    source_id = EntityId.parse("entity_1")
    target_id = EntityId.parse("entity_2")
    source = world.get_entity(source_id)
    assert world.epoch == 7
    assert source.get_component(IdentityComponent).name == 'Source "quoted" ☃'
    assert source.get_relationships(ExitTo) == [
        (ExitTo(direction="north", label="North"), target_id)
    ]


def test_yaml_driver_save_serializes_world_prefabs_entities_and_relationships(tmp_path):
    driver = YAMLPersistenceDriver()
    world = World()
    world.register_edge_type(ExitTo)
    world.register_prefab("room", {IdentityComponent: IdentityComponent(name="Room", kind="room")})
    source = world.spawn("room", {IdentityComponent: IdentityComponent(name="Source", kind="room")})
    target = world.spawn("room", {IdentityComponent: IdentityComponent(name="Target", kind="room")})
    source.add_relationship(ExitTo(direction="north", label="North"), target.id)

    path = tmp_path / "world.yaml"
    driver.save(world, path, relic_name="saved-room")
    snapshot = driver.read_snapshot(path)

    assert snapshot["metadata"]["relic_name"] == "saved-room"
    assert snapshot["prefabs"]["room"]["components"]["IdentityComponent"]["name"] == "Room"
    assert snapshot["entities"][str(source.id)]["prefab"] == "room"
    assert snapshot["components"]["IdentityComponent"][str(source.id)]["name"] == "Source"
    assert snapshot["relationships"]["ExitTo"][str(source.id)] == [
        {
            "target": str(target.id),
            "edge": {
                "action_cost": 1,
                "direction": "north",
                "hidden": False,
                "label": "North",
                "locked": False,
            },
        }
    ]


def test_yaml_driver_dumps_plain_values_and_quoted_keys():
    driver = YAMLPersistenceDriver()

    text = driver.dumps_snapshot(
        {
            "metadata": None,
            "bunnyland": {
                "model": _YamlNestedModel(label="nested"),
                "data": _YamlNestedData(flavor=_YamlFlavor.SWEET, hidden="visible"),
                "items": {"tuple": ("a", _YamlFlavor.SWEET), "set": {"b"}},
                7: "numeric key",
            },
            "prefabs": {},
            "entities": {
                "plain_1": {},
                "room-with-dash_2": {},
            },
            "components": {
                "Odd Component": {
                    "room-with-dash_2": {"value": _YamlFlavor.SWEET},
                },
            },
        }
    )

    assert "__metadata__: {}" in text
    assert '"7": "numeric key"' in text
    assert '"flavor": "sweet"' in text
    assert '"label": "nested"' in text
    assert '"_private"' not in text
    assert "plain_1: {}" in text
    assert '"Odd Component": {"value": "sweet"}' in text


def test_yaml_driver_parses_compact_reserved_sections_and_empty_yaml(tmp_path):
    driver = YAMLPersistenceDriver()
    path = tmp_path / "empty.yaml"
    path.write_text("")

    assert driver.read_snapshot(path) == {
        "metadata": {},
        "bunnyland": {},
        "prefabs": {},
        "entities": {},
        "components": {},
        "relationships": {},
        "relics": [],
    }

    snapshot = driver.snapshot_from_document(
        {
            "__metadata__": {"epoch": 3},
            "__bunnyland__": {"seed": "marsh"},
            "__prefabs__": {"room": {"components": {}}},
            "room_1": {
                "IdentityComponent": {"name": "Room", "kind": "room"},
                "ExitTo -> room_2": {"direction": "east", "label": "East"},
            },
            "room_2": {},
        }
    )

    assert snapshot["metadata"] == {"epoch": 3}
    assert snapshot["bunnyland"] == {"seed": "marsh"}
    assert snapshot["prefabs"] == {"room": {"components": {}}}
    assert snapshot["components"]["IdentityComponent"]["room_1"]["name"] == "Room"
    assert snapshot["relationships"]["ExitTo"]["room_1"] == [
        {"target": "room_2", "edge": {"direction": "east", "label": "East"}}
    ]


def test_yaml_driver_rejects_malformed_snapshot_sections():
    driver = YAMLPersistenceDriver()

    with pytest.raises(ValueError, match="metadata must be a YAML mapping"):
        driver.dumps_snapshot({"metadata": []})

    with pytest.raises(ValueError, match="YAML document must be a YAML mapping"):
        driver.snapshot_from_document(["not", "a", "mapping"])

    with pytest.raises(ValueError, match="Contains edges for entity_1 must be a list"):
        driver.dumps_snapshot(
            {
                "entities": {"entity_1": {}},
                "relationships": {"Contains": {"entity_1": {"target": "entity_2"}}},
            }
        )

    with pytest.raises(ValueError, match="Contains edge must be a YAML mapping"):
        driver.dumps_snapshot(
            {
                "entities": {"entity_1": {}},
                "relationships": {"Contains": {"entity_1": ["not a mapping"]}},
            }
        )

    with pytest.raises(ValueError, match="entity_1.IdentityComponent must be a YAML mapping"):
        driver.snapshot_from_document({"entity_1": {"IdentityComponent": ["bad"]}})

    with pytest.raises(ValueError, match="__bunnyland__ must be a YAML mapping"):
        driver.snapshot_from_document({"__bunnyland__": []})


def test_yaml_driver_handles_relic_listing_errors_and_duplicates(tmp_path):
    driver = YAMLPersistenceDriver()
    relics_dir = tmp_path / "relics"
    world = World()

    assert driver.list_relics(relics_dir) == []

    driver.save_relic(world, "smoke", relics_dir)
    with pytest.raises(FileExistsError, match="Relic 'smoke' already exists"):
        driver.save_relic(world, "smoke", relics_dir)

    (relics_dir / "_hidden.yaml").write_text("__metadata__: {\"relic_name\": \"hidden\"}\n")
    (relics_dir / "broken.yaml").write_text("- not\n- a\n- mapping\n")

    relics = driver.list_relics(relics_dir)
    assert [relic.name for relic in relics] == ["smoke"]

    driver.load_relic(World(), "smoke", relics_dir)

    with pytest.raises(FileNotFoundError, match="Relic 'missing' not found"):
        driver.load_relic(world, "missing", relics_dir)


def test_yaml_driver_loads_yml_relic_fallback(tmp_path):
    driver = YAMLPersistenceDriver()
    relics_dir = tmp_path / "relics"
    relics_dir.mkdir()
    (relics_dir / "smoke.yml").write_text(
        """
__metadata__: {"version": "1.0", "epoch": 5}
__prefabs__: {}
entity_1:
  IdentityComponent: {"name": "Smoke", "kind": "room"}
""".lstrip()
    )
    world = World()

    driver.load_relic(world, "smoke", relics_dir, *type_registries())

    assert world.epoch == 5
    assert (
        world.get_entity(EntityId.parse("entity_1")).get_component(IdentityComponent).name
        == "Smoke"
    )


def test_yaml_driver_returns_regular_relics_snapshot_unchanged():
    snapshot = {"metadata": {"epoch": 12}, "entities": {"entity_1": {}}}

    assert YAMLPersistenceDriver().snapshot_from_document(snapshot) == snapshot


def test_yaml_driver_load_snapshot_uses_world_registries_and_skips_unknowns():
    driver = YAMLPersistenceDriver()
    world = World()
    world.register_component_type(IdentityComponent)
    world.register_edge_type(ExitTo)

    driver.load_snapshot(
        world,
        {
            "metadata": {"epoch": 9},
            "prefabs": {
                "room": {
                    "components": {
                        "IdentityComponent": {"name": "Prefab Room", "kind": "room"},
                        "MissingComponent": {"ignored": True},
                    }
                }
            },
            "entities": {
                "room_1": {},
                "room_2": {"prefab": "room"},
            },
            "components": {
                "IdentityComponent": {
                    "room_1": {"name": "Start", "kind": "room"},
                    "missing_1": {"name": "Missing", "kind": "room"},
                },
                "MissingComponent": {
                    "room_1": {"ignored": True},
                },
            },
            "relationships": {
                "ExitTo": {
                    "room_1": [
                        {
                            "target": "room_2",
                            "edge": {"direction": "north", "label": "North"},
                        },
                        {
                            "target": "missing_1",
                            "edge": {"direction": "south", "label": "Missing"},
                        },
                    ],
                    "missing_1": [
                        {
                            "target": "room_2",
                            "edge": {"direction": "east", "label": "Ignored"},
                        }
                    ],
                },
                "MissingEdge": {
                    "room_1": [{"target": "room_2", "edge": {}}],
                },
            },
        },
    )

    room_1 = world.get_entity(EntityId.parse("room_1"))
    room_2_id = EntityId.parse("room_2")
    assert world.epoch == 9
    assert world._prefabs["room"][IdentityComponent].name == "Prefab Room"
    assert room_1.get_component(IdentityComponent).name == "Start"
    assert room_1.get_relationships(ExitTo) == [
        (ExitTo(direction="north", label="North"), room_2_id)
    ]


def test_yaml_driver_load_snapshot_rejects_malformed_sections():
    driver = YAMLPersistenceDriver()
    world = World()
    world.register_edge_type(ExitTo)

    with pytest.raises(ValueError, match="prefab room components must be a YAML mapping"):
        driver.load_snapshot(
            world,
            {
                "prefabs": {"room": {"components": []}},
            },
        )

    with pytest.raises(ValueError, match="ExitTo edges for room_1 must be a list"):
        driver.load_snapshot(
            world,
            {
                "entities": {"room_1": {}, "room_2": {}},
                "relationships": {"ExitTo": {"room_1": {"target": "room_2"}}},
            },
        )


async def test_reload_starts_with_empty_command_queues(tmp_path):
    actor, _result = await _build_and_play()
    path = tmp_path / "world.json"
    save_world(actor, path, meta=WorldMeta())
    actor2, _meta = load_world(path, plugins=bunnyland_plugins())

    # Volatile queues are never persisted (spec 26): a reload resumes with empty queues.
    assert actor2.queues.characters_with_pending() == []
    assert actor2._inbox.empty()


async def test_game_loop_autosaves_every_n_ticks(tmp_path):
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    await instantiate(actor, await StubWorldBuilder().propose("seed"))
    path = tmp_path / "auto.json"

    saved_at: list[int] = []

    def autosave(ticks: int) -> None:
        saved_at.append(ticks)
        save_world(actor, path, meta=WorldMeta(seed="seed"))

    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), ScriptedAgent([]))
    loop = GameLoop(actor, dispatch, autosave=autosave, autosave_every=2)
    await loop.run(max_ticks=5)

    assert saved_at == [2, 4]
    assert path.exists()


def test_type_registries_cover_core_and_plugin_types():
    components, edges = type_registries(bunnyland_plugins())
    assert {
        "IdentityComponent",
        "HungerComponent",
        "RegionComponent",
        "RoomComponent",
        "ToonRoomComponent",
    } <= set(components)
    assert {"Contains", "ExitTo", "ControlledBy"} <= set(edges)


def test_toon_room_default_start_reloads_with_plugin_registry(tmp_path):
    actor = WorldActor()
    room = spawn_entity(
        actor.world,
        [RoomComponent(title="Landing Room"), ToonRoomComponent(default_start=True)],
    )

    path = tmp_path / "toon-room.json"
    save_world(actor, path, meta=WorldMeta(seed="toon"))
    loaded, _meta = load_world(path, plugins=bunnyland_plugins())

    loaded_room = loaded.world.get_entity(room.id)
    assert loaded_room.get_component(ToonRoomComponent).default_start is True


def test_region_hierarchy_uses_contains_region_mode_and_reloads(tmp_path):
    actor = WorldActor()
    chain = [
        spawn_entity(
            actor.world,
            [
                RegionComponent(
                    name="Lapin Prime",
                    kind="planet",
                    population=8_400_000_000,
                    climate="temperate",
                    terrain="mixed biomes",
                )
            ],
        ),
        spawn_entity(actor.world, [RegionComponent(name="Mossreach", kind="continent")]),
        spawn_entity(actor.world, [RegionComponent(name="Burrowmark", kind="country")]),
        spawn_entity(actor.world, [RegionComponent(name="North Warren", kind="region")]),
        spawn_entity(actor.world, [RegionComponent(name="Clover City", kind="city")]),
        spawn_entity(actor.world, [RegionComponent(name="Old Market", kind="area")]),
        spawn_entity(actor.world, [RegionComponent(name="Greenhill", kind="neighborhood")]),
        spawn_entity(actor.world, [RegionComponent(name="Sunstem Zone", kind="zone")]),
        spawn_entity(actor.world, [RegionComponent(name="Carrot Street", kind="street")]),
        spawn_entity(actor.world, [RegionComponent(name="Moonroot Tower", kind="building")]),
        spawn_entity(actor.world, [RegionComponent(name="Story Three", kind="story")]),
        spawn_entity(actor.world, [RoomComponent(title="Observatory Room", indoor=True)]),
    ]
    for parent, child in zip(chain, chain[1:], strict=False):
        parent.add_relationship(Contains(mode=ContainmentMode.REGION), child.id)

    path = tmp_path / "regions.json"
    save_world(actor, path, meta=WorldMeta(seed="regional"))
    loaded, _meta = load_world(path)

    loaded_root = loaded.world.get_entity(chain[0].id).get_component(RegionComponent)
    assert loaded_root.population == 8_400_000_000
    assert loaded_root.climate == "temperate"
    assert loaded_root.terrain == "mixed biomes"

    for parent, child in zip(chain, chain[1:], strict=False):
        relationships = loaded.world.get_entity(parent.id).get_relationships(Contains)
        assert any(
            target == child.id and edge.mode == ContainmentMode.REGION
            for edge, target in relationships
        )
