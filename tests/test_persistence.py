"""Tests for world persistence (spec 26): save, reload, autosave, and provenance."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

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
from bunnyland.discord.components import DiscordRoomFeedComponent
from bunnyland.engine import GameLoop
from bunnyland.foundation.needs.mechanics import HungerComponent
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent, ToolCall
from bunnyland.migrations import WorldMigrationError, migrate_snapshot
from bunnyland.offline import advance_offline_life
from bunnyland.persistence import (
    WorldMeta,
    YAMLPersistenceDriver,
    _format_for_path,
    load_world,
    save_world,
    type_registries,
)
from bunnyland.plugins import PluginRegistry, apply_plugins, bunnyland_plugins
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.simpacks.toonsim.mechanics import ToonRoomComponent
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


def _schema_v1_generated_quest_snapshot():
    return {
        "metadata": {"version": "1.0", "epoch": 12},
        "bunnyland": {"schema_version": 1, "plugins": ["bunnyland.dragonsim"]},
        "prefabs": {"entity": {"components": {}}},
        "entities": {
            "entity_1": {"prefab": "entity", "created_epoch": 0},
            "entity_2": {"prefab": "entity", "created_epoch": 0},
            "entity_3": {"prefab": "entity", "created_epoch": 0},
        },
        "components": {
            "GeneratedQuestComponent": {
                "entity_1": {
                    "title": "Carry the Letter",
                    "objective": "deliver it",
                    "status": "active",
                    "accepted_by": "entity_2",
                }
            },
            "QuestDeadlineComponent": {"entity_1": {"due_at_epoch": 99}},
            "DaggerQuestRewardComponent": {
                "entity_1": {"item_name": "guild writ", "claimed": False}
            },
            "WorldClockComponent": {
                "entity_3": {
                    "game_time_seconds": 12,
                    "tick_index": 0,
                    "time_scale": 1.0,
                }
            },
        },
        "relationships": {},
        "relics": [],
    }


def test_schema_v1_quest_snapshot_migrates_to_canonical_graph_without_mutating_source():
    source = _schema_v1_generated_quest_snapshot()

    migrated = migrate_snapshot(source)

    assert source["bunnyland"]["schema_version"] == 1
    assert migrated["bunnyland"]["schema_version"] == 2
    assert (
        not {
            "GeneratedQuestComponent",
            "QuestDeadlineComponent",
            "DaggerQuestRewardComponent",
        }
        & migrated["components"].keys()
    )
    assert migrated["components"]["QuestComponent"]["entity_1"] == {
        "quest_id": "entity_1",
        "title": "Carry the Letter",
        "description": "deliver it",
    }
    assert migrated["components"]["QuestStateComponent"]["entity_1"] == {
        "status": "active",
        "due_at_epoch": 99,
    }
    assert migrated["relationships"]["QuestAcceptedBy"]["entity_1"][0]["target"] == ("entity_2")
    objective_id = migrated["relationships"]["QuestHasObjective"]["entity_1"][0]["target"]
    reward_id = migrated["relationships"]["QuestHasReward"]["entity_1"][0]["target"]
    assert objective_id == "quest_objective_1"
    assert reward_id == "quest_reward_1"


def test_schema_migration_rejects_future_and_ambiguous_worlds():
    with pytest.raises(WorldMigrationError, match="newer than supported"):
        migrate_snapshot({"bunnyland": {"schema_version": 3}})

    snapshot = _schema_v1_generated_quest_snapshot()
    snapshot["components"]["QuestComponent"] = {
        "entity_1": {"quest_id": "duplicate", "title": "Duplicate"},
        "entity_2": {"quest_id": "duplicate", "title": "Also Duplicate"},
    }
    with pytest.raises(WorldMigrationError, match="refers to both"):
        migrate_snapshot(snapshot)


def test_load_schema_v1_migrates_in_memory_and_next_save_is_v2(tmp_path):
    source = tmp_path / "world-v1.json"
    dest = tmp_path / "world-v2.json"
    snapshot = _schema_v1_generated_quest_snapshot()
    source.write_text(json.dumps(snapshot))

    actor, meta = load_world(source, registry=PluginRegistry(bunnyland_plugins()))

    from bunnyland.simpacks.dragonsim.mechanics import (
        QuestAcceptedBy,
        QuestComponent,
        QuestHasObjective,
        QuestHasReward,
        QuestStateComponent,
    )

    quest = actor.world.get_entity(EntityId.parse("entity_1"))
    assert quest.has_component(QuestComponent)
    assert quest.get_component(QuestStateComponent).due_at_epoch == 99
    assert quest.has_relationship(QuestAcceptedBy, EntityId.parse("entity_2"))
    assert len(quest.get_relationships(QuestHasObjective)) == 1
    assert len(quest.get_relationships(QuestHasReward)) == 1
    assert meta.schema_version == 2
    assert json.loads(source.read_text())["bunnyland"]["schema_version"] == 1

    save_world(actor, dest, meta=meta)

    assert json.loads(dest.read_text())["bunnyland"]["schema_version"] == 2


def test_schema_v1_regular_quest_collections_become_ordered_edges():
    snapshot = _schema_v1_generated_quest_snapshot()
    snapshot["components"].pop("GeneratedQuestComponent")
    snapshot["components"].pop("DaggerQuestRewardComponent")
    snapshot["components"]["QuestComponent"] = {
        "entity_1": {
            "quest_id": "letter",
            "title": "Carry the Letter",
            "status": "active",
            "accepted_by": "entity_2",
            "completed_at_epoch": 20,
        }
    }
    snapshot["entities"].update(
        {
            "entity_4": {"prefab": "entity", "created_epoch": 0},
            "entity_5": {"prefab": "entity", "created_epoch": 0},
            "entity_6": {"prefab": "entity", "created_epoch": 0},
        }
    )
    snapshot["components"]["QuestStageComponent"] = {
        "entity_4": {
            "quest_id": "letter",
            "stage": 2,
            "branch": "honest",
            "tracked_by": ["entity_2"],
        }
    }
    snapshot["components"]["QuestObjectiveComponent"] = {
        "entity_4": {"quest_id": "letter", "description": "Deliver it"}
    }
    snapshot["components"]["QuestRewardComponent"] = {
        "entity_5": {
            "quest_id": "letter",
            "description": "A writ",
            "item_ids": ["entity_6"],
        }
    }

    migrated = migrate_snapshot(snapshot)

    assert migrated["components"]["QuestComponent"]["entity_1"]["description"] == ""
    assert migrated["components"]["QuestStateComponent"]["entity_1"] == {
        "status": "active",
        "completed_at_epoch": 20,
        "stage": 2,
        "branch": "honest",
        "due_at_epoch": 99,
    }
    assert migrated["relationships"]["TracksQuest"]["entity_2"][0]["target"] == "entity_1"
    assert migrated["relationships"]["QuestHasObjective"]["entity_1"][0]["target"] == ("entity_4")
    assert migrated["relationships"]["QuestHasReward"]["entity_1"][0]["target"] == ("entity_5")
    assert migrated["relationships"]["QuestRewardGrants"]["entity_5"][0]["target"] == ("entity_6")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"components": []}), "section 'components'"),
        (
            lambda value: value["components"].update({"GeneratedQuestComponent": []}),
            "GeneratedQuestComponent.*mapping",
        ),
        (
            lambda value: value["components"].update({"GeneratedQuestComponent": {"entity_1": []}}),
            "fields.*mapping",
        ),
        (
            lambda value: value["relationships"].update({"QuestAcceptedBy": {"entity_1": {}}}),
            "QuestAcceptedBy edges.*list",
        ),
        (
            lambda value: value["components"].update(
                {"QuestObjectiveComponent": {"entity_4": {"quest_id": "missing"}}}
            ),
            "unknown quest",
        ),
        (
            lambda value: value["components"].update({"QuestStageComponent": []}),
            "QuestStageComponent.*mapping",
        ),
        (
            lambda value: value["components"].update({"QuestDeadlineComponent": []}),
            "QuestDeadlineComponent.*mapping",
        ),
        (
            lambda value: value["components"].update({"DaggerQuestRewardComponent": []}),
            "DaggerQuestRewardComponent.*mapping",
        ),
    ],
)
def test_schema_v1_migration_rejects_malformed_relationships(mutate, message):
    snapshot = _schema_v1_generated_quest_snapshot()
    mutate(snapshot)
    with pytest.raises(WorldMigrationError, match=message):
        migrate_snapshot(snapshot)


def test_schema_migration_validates_version_and_v2_sections():
    with pytest.raises(WorldMigrationError, match="must be a mapping"):
        migrate_snapshot([])
    with pytest.raises(WorldMigrationError, match="must be an integer"):
        migrate_snapshot({"bunnyland": {"schema_version": "2"}})
    with pytest.raises(WorldMigrationError, match="unsupported world schema"):
        migrate_snapshot({"bunnyland": {"schema_version": 0}})
    with pytest.raises(WorldMigrationError, match="section 'entities'"):
        migrate_snapshot({"bunnyland": {"schema_version": 2}, "entities": []})


def test_schema_v1_dragon_stealth_name_migrates_without_mutating_source():
    source = _schema_v1_generated_quest_snapshot()
    source["components"]["StealthComponent"] = {"entity_2": {"sneaking": True, "since_epoch": 7}}

    migrated = migrate_snapshot(source)

    assert "StealthComponent" in source["components"]
    assert "StealthComponent" not in migrated["components"]
    assert migrated["components"]["SneakingComponent"] == {
        "entity_2": {"sneaking": True, "since_epoch": 7}
    }

    ambiguous = _schema_v1_generated_quest_snapshot()
    ambiguous["components"]["StealthComponent"] = {"entity_2": {"sneaking": True, "since_epoch": 7}}
    ambiguous["components"]["SneakingComponent"] = {
        "entity_3": {"sneaking": False, "since_epoch": 0}
    }
    with pytest.raises(WorldMigrationError, match="both StealthComponent and SneakingComponent"):
        migrate_snapshot(ambiguous)


def test_schema_v1_cure_quest_hook_name_migrates_to_affliction_request():
    source = _schema_v1_generated_quest_snapshot()
    source["components"]["CureQuestHookComponent"] = {
        "entity_2": {"affliction_type": "moon-form", "quest_id": None}
    }

    migrated = migrate_snapshot(source)

    assert "CureQuestHookComponent" in source["components"]
    assert "CureQuestHookComponent" not in migrated["components"]
    assert migrated["components"]["CureRequestComponent"] == {
        "entity_2": {"affliction_type": "moon-form", "quest_id": None}
    }

    source["components"]["CureRequestComponent"] = {}
    with pytest.raises(WorldMigrationError, match="both CureQuestHookComponent"):
        migrate_snapshot(source)


def test_schema_v1_potion_recipe_ingredients_migrate_to_ordered_edges():
    source = _schema_v1_generated_quest_snapshot()
    source["entities"]["entity_4"] = {"prefab": "entity", "created_epoch": 0}
    source["components"]["PotionRecipeComponent"] = {
        "entity_2": {
            "name": "moon tonic",
            "potion_name": "Moon Tonic",
            "ingredient_ids": ["entity_4"],
        }
    }

    migrated = migrate_snapshot(source)

    assert source["components"]["PotionRecipeComponent"]["entity_2"]["ingredient_ids"] == [
        "entity_4"
    ]
    assert "ingredient_ids" not in migrated["components"]["PotionRecipeComponent"]["entity_2"]
    assert migrated["relationships"]["DependsOnIngredient"]["entity_2"] == [
        {"target": "entity_4", "edge": {"order": 0}}
    ]

    missing = _schema_v1_generated_quest_snapshot()
    missing["components"]["PotionRecipeComponent"] = {
        "entity_2": {"name": "bad", "potion_name": "Bad", "ingredient_ids": ["missing"]}
    }
    with pytest.raises(
        WorldMigrationError,
        match=r"entity 'entity_2'.*PotionRecipeComponent\.ingredient_ids.*'missing'",
    ):
        migrate_snapshot(missing)

    malformed = _schema_v1_generated_quest_snapshot()
    malformed["components"]["PotionRecipeComponent"] = {
        "entity_2": {"name": "bad", "potion_name": "Bad", "ingredient_ids": 7}
    }
    with pytest.raises(WorldMigrationError, match="ingredient_ids.*must be a sequence"):
        migrate_snapshot(malformed)


def test_schema_v1_egg_parents_migrate_to_ordered_edges():
    source = _schema_v1_generated_quest_snapshot()
    source["components"]["EggComponent"] = {
        "entity_1": {
            "species_name": "raptor",
            "laid_at_epoch": 3,
            "parent_ids": ["entity_2"],
        }
    }

    migrated = migrate_snapshot(source)

    assert source["components"]["EggComponent"]["entity_1"]["parent_ids"] == ["entity_2"]
    assert "parent_ids" not in migrated["components"]["EggComponent"]["entity_1"]
    assert migrated["relationships"]["DescendsFromParent"]["entity_1"] == [
        {"target": "entity_2", "edge": {"order": 0}}
    ]

    missing = _schema_v1_generated_quest_snapshot()
    missing["components"]["EggComponent"] = {
        "entity_1": {"species_name": "raptor", "laid_at_epoch": 3, "parent_ids": ["missing"]}
    }
    with pytest.raises(WorldMigrationError, match=r"EggComponent\.parent_ids.*'missing'"):
        migrate_snapshot(missing)

    malformed = _schema_v1_generated_quest_snapshot()
    malformed["components"]["EggComponent"] = {
        "entity_1": {"species_name": "raptor", "laid_at_epoch": 3, "parent_ids": 7}
    }
    with pytest.raises(WorldMigrationError, match="parent_ids.*must be a sequence"):
        migrate_snapshot(malformed)


@pytest.mark.parametrize("suffix", ["json", "yaml"])
def test_schema_v1_relationship_fixtures_load_and_resave_as_v2(tmp_path, suffix):
    import yaml

    source = Path(__file__).parent / "fixtures" / "migrations" / f"relationships-v1.{suffix}"
    before = source.read_text()
    raw = json.loads(before) if suffix == "json" else yaml.safe_load(before)

    migrated = migrate_snapshot(raw)

    assert source.read_text() == before
    assert migrated["bunnyland"]["schema_version"] == 2
    expected = {
        "AllowedIn": ("entity_1", "entity_2"),
        "MemberOfCaravan": ("entity_1", "entity_3"),
        "StoredIn": ("entity_4", "entity_3"),
        "HasAccessToService": ("entity_1", "entity_5"),
        "MemberOfFestival": ("entity_1", "entity_3"),
        "MemberOfAwayTeam": ("entity_1", "entity_3"),
        "DependsOnIngredient": ("entity_5", "entity_4"),
        "DescendsFromParent": ("entity_6", "entity_1"),
        "RumorHeardBy": ("entity_4", "entity_1"),
        "OriginatesFromSource": ("entity_4", "entity_2"),
        "RefersToSubject": ("entity_4", "entity_6"),
    }
    for edge_name, (source_id, target_id) in expected.items():
        assert migrated["relationships"][edge_name][source_id][0]["target"] == target_id

    actor, meta = load_world(source, registry=PluginRegistry(bunnyland_plugins()))
    destination = tmp_path / f"relationships-v2.{suffix}"
    save_world(actor, destination, meta=meta)
    saved = json.loads(destination.read_text()) if suffix == "json" else yaml.safe_load(
        destination.read_text()
    )
    metadata_key = "bunnyland" if suffix == "json" else "__bunnyland__"
    assert saved[metadata_key]["schema_version"] == 2


@pytest.mark.parametrize(
    ("component", "field"),
    [
        ("AllowedAreaComponent", "room_ids"),
        ("CaravanComponent", "member_ids"),
        ("SafeStorageComponent", "item_ids"),
        ("ServiceAccessComponent", "service_ids"),
        ("FestivalComponent", "joined_character_ids"),
        ("AwayTeamComponent", "member_ids"),
        ("RumorComponent", "heard_by"),
    ],
)
def test_schema_v1_relationship_sequences_reject_malformed_and_missing_targets(
    component, field
):
    malformed = _schema_v1_generated_quest_snapshot()
    malformed["components"][component] = {"entity_1": {field: 7}}
    with pytest.raises(WorldMigrationError, match=rf"{field}.*must be a sequence"):
        migrate_snapshot(malformed)

    missing = _schema_v1_generated_quest_snapshot()
    missing["components"][component] = {"entity_1": {field: ["missing"]}}
    with pytest.raises(
        WorldMigrationError,
        match=rf"entity 'entity_1'.*{component}\.{field}.*'missing'",
    ):
        migrate_snapshot(missing)


@pytest.mark.parametrize("component", ["AllowedAreaComponent", "ServiceAccessComponent"])
def test_schema_v1_empty_relationship_wrappers_must_be_mappings(component):
    source = _schema_v1_generated_quest_snapshot()
    source["components"][component] = []
    with pytest.raises(WorldMigrationError, match=rf"type '{component}'.*mapping"):
        migrate_snapshot(source)


@pytest.mark.parametrize(
    ("component", "field"),
    [("RumorSourceComponent", "source_id"), ("RumorTargetComponent", "target_id")],
)
def test_schema_v1_rumor_relationship_wrappers_reject_missing_targets(component, field):
    source = _schema_v1_generated_quest_snapshot()
    source["components"][component] = {"entity_1": {field: "missing"}}
    with pytest.raises(
        WorldMigrationError,
        match=rf"entity 'entity_1'.*{component}\.{field}.*'missing'",
    ):
        migrate_snapshot(source)


@pytest.mark.parametrize("component", ["RumorSourceComponent", "RumorTargetComponent"])
def test_schema_v1_rumor_relationship_wrappers_must_be_mappings(component):
    source = _schema_v1_generated_quest_snapshot()
    source["components"][component] = []
    with pytest.raises(WorldMigrationError, match=rf"type '{component}'.*mapping"):
        migrate_snapshot(source)


def test_schema_v1_rumor_without_source_drops_empty_wrapper():
    source = _schema_v1_generated_quest_snapshot()
    source["components"]["RumorSourceComponent"] = {"entity_1": {"source_id": None}}

    migrated = migrate_snapshot(source)

    assert "RumorSourceComponent" not in migrated["components"]
    assert "OriginatesFromSource" not in migrated["relationships"]


def test_schema_v1_migration_handles_collisions_and_unaccepted_generated_quests():
    snapshot = _schema_v1_generated_quest_snapshot()
    snapshot["components"]["GeneratedQuestComponent"]["entity_1"].pop("accepted_by")
    snapshot["entities"]["quest_objective_1"] = {
        "prefab": "quest_objective",
        "created_epoch": 0,
    }

    migrated = migrate_snapshot(snapshot)

    assert migrated["relationships"]["QuestHasObjective"]["entity_1"][0]["target"] == (
        "quest_objective_2"
    )
    assert "QuestAcceptedBy" not in migrated["relationships"]


def test_schema_v1_migration_rejects_ambiguous_quest_state():
    both_families = _schema_v1_generated_quest_snapshot()
    both_families["components"]["QuestComponent"] = {
        "entity_1": {"quest_id": "other", "title": "Other"}
    }
    with pytest.raises(WorldMigrationError, match="both quest component families"):
        migrate_snapshot(both_families)

    invalid_participants = _schema_v1_generated_quest_snapshot()
    invalid_participants["components"].pop("GeneratedQuestComponent")
    invalid_participants["components"]["QuestComponent"] = {
        "entity_1": {
            "quest_id": "letter",
            "title": "Letter",
            "accepted_by": 7,
        }
    }
    with pytest.raises(WorldMigrationError, match="accepted_by.*sequence"):
        migrate_snapshot(invalid_participants)

    duplicate_stages = _schema_v1_generated_quest_snapshot()
    duplicate_stages["components"]["QuestStageComponent"] = {
        "entity_4": {"quest_id": "entity_1"},
        "entity_5": {"quest_id": "entity_1"},
    }
    with pytest.raises(WorldMigrationError, match="multiple lifecycle"):
        migrate_snapshot(duplicate_stages)

    conflicting_deadline = _schema_v1_generated_quest_snapshot()
    conflicting_deadline["components"]["QuestStateComponent"] = {"entity_1": {"due_at_epoch": 50}}
    with pytest.raises(WorldMigrationError, match="conflicting deadlines"):
        migrate_snapshot(conflicting_deadline)


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
    actor2, meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))

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

    actor2, _meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))
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

    loaded, meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))
    ticks = await advance_offline_life(loaded, 2 * 3600.0, max_ticks=2)
    save_world(loaded, path, meta=meta)
    reloaded, _meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))

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


async def test_offline_life_returns_zero_for_nonpositive_elapsed():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)

    # Non-positive elapsed time short-circuits before any tick runs.
    assert await advance_offline_life(actor, 0.0) == 0
    assert await advance_offline_life(actor, -5.0) == 0
    assert actor.epoch == 0


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
    actor2, meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))

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
    components, edges = type_registries(PluginRegistry(bunnyland_plugins()))
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


def test_yaml_driver_save_omits_relic_name_and_temporary_components(tmp_path):
    from dataclasses import dataclass as _dataclass

    from relics import Component
    from relics.shared import temporary_component

    @temporary_component
    @_dataclass
    class ScratchComponent(Component):
        value: int = 0

    driver = YAMLPersistenceDriver()
    world = World()
    world.register_prefab("room", {IdentityComponent: IdentityComponent(name="Room", kind="room")})
    room = world.spawn("room", {IdentityComponent: IdentityComponent(name="Source", kind="room")})
    room.add_component(ScratchComponent(value=7))

    path = tmp_path / "world.yaml"
    driver.save(world, path)  # no relic_name -> metadata branch 99->102 skipped
    snapshot = driver.read_snapshot(path)

    assert "relic_name" not in snapshot["metadata"]
    # Temporary component skipped during serialization (line 114).
    assert "ScratchComponent" not in snapshot["components"]
    assert "IdentityComponent" in snapshot["components"]


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

    (relics_dir / "_hidden.yaml").write_text('__metadata__: {"relic_name": "hidden"}\n')
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

    driver.load_relic(
        world, "smoke", relics_dir, *type_registries(PluginRegistry(bunnyland_plugins()))
    )

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
    actor2, _meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))

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
    components, edges = type_registries(PluginRegistry(bunnyland_plugins()))
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
    loaded, _meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))

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
    loaded, _meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))

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


def test_discord_room_feed_component_survives_save_load(tmp_path):
    actor = WorldActor()
    room = spawn_entity(
        actor.world,
        [
            RoomComponent(title="Feed Room"),
            DiscordRoomFeedComponent(channel_id=123456789),
        ],
    )

    path = tmp_path / "discord-room-feed.json"
    save_world(actor, path, meta=WorldMeta(seed="discord-feed"))
    loaded, _meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))

    component = loaded.world.get_entity(room.id).get_component(DiscordRoomFeedComponent)
    assert component.channel_id == 123456789


def test_yaml_module_missing_extra_raises(monkeypatch):
    from bunnyland.persistence_yaml import _yaml_module

    monkeypatch.setitem(sys.modules, "yaml", None)
    with pytest.raises(RuntimeError, match="YAML persistence requires PyYAML"):
        _yaml_module()
