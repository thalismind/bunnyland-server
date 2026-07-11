"""One-way migrations for persisted Bunnyland world snapshots."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

CURRENT_SCHEMA_VERSION = 2


class WorldMigrationError(ValueError):
    """A saved world cannot be migrated without guessing at its meaning."""


def _table(snapshot: dict[str, Any], section: str) -> dict[str, Any]:
    value = snapshot.setdefault(section, {})
    if not isinstance(value, dict):
        raise WorldMigrationError(f"world snapshot section {section!r} must be a mapping")
    return value


def _records(table: dict[str, Any], type_name: str) -> dict[str, dict[str, Any]]:
    value = table.setdefault(type_name, {})
    if not isinstance(value, dict):
        raise WorldMigrationError(f"persisted type {type_name!r} must contain a mapping")
    return value


def _add_edge(
    relationships: dict[str, Any],
    edge_name: str,
    source_id: str,
    target_id: str,
    fields: dict[str, Any] | None = None,
) -> None:
    sources = _records(relationships, edge_name)
    edges = sources.setdefault(source_id, [])
    if not isinstance(edges, list):
        raise WorldMigrationError(f"{edge_name} edges for {source_id!r} must be a list")
    record = {"target": target_id, "edge": fields or {}}
    if record not in edges:
        edges.append(record)


def _synthetic_id(entities: dict[str, Any], prefab: str, ordinal: int) -> str:
    sequence = ordinal
    while f"{prefab}_{sequence}" in entities:
        sequence += 1
    return f"{prefab}_{sequence}"


def _live_target(
    entities: dict[str, Any], target_id: Any, *, owner_id: str, component: str, field: str
) -> str:
    target = str(target_id or "")
    if target not in entities:
        raise WorldMigrationError(
            f"schema-v1 entity {owner_id!r} component {component}.{field} "
            f"refers to missing entity {target!r}"
        )
    return target


def _quest_index(components: dict[str, Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    for type_name in ("QuestComponent", "GeneratedQuestComponent"):
        for entity_id, fields in _records(components, type_name).items():
            if not isinstance(fields, dict):
                raise WorldMigrationError(f"{type_name} fields for {entity_id!r} must be a mapping")
            quest_key = str(fields.get("quest_id") or entity_id)
            previous = index.get(quest_key)
            if previous is not None and previous != entity_id:
                raise WorldMigrationError(
                    f"schema-v1 quest key {quest_key!r} refers to both "
                    f"{previous!r} and {entity_id!r}"
                )
            index[quest_key] = entity_id
            index.setdefault(entity_id, entity_id)
    return index


def _resolve_quest(index: dict[str, str], quest_key: Any, owner_id: str) -> str:
    key = str(quest_key or "")
    try:
        return index[key]
    except KeyError as exc:
        raise WorldMigrationError(
            f"schema-v1 record {owner_id!r} refers to unknown quest {key!r}"
        ) from exc


def _migrate_v1(snapshot: dict[str, Any]) -> dict[str, Any]:
    components = _table(snapshot, "components")
    relationships = _table(snapshot, "relationships")
    entities = _table(snapshot, "entities")
    legacy_stealth = components.get("StealthComponent", {})
    if isinstance(legacy_stealth, dict) and any(
        isinstance(fields, dict) and ("sneaking" in fields or "since_epoch" in fields)
        for fields in legacy_stealth.values()
    ):
        if "SneakingComponent" in components:
            raise WorldMigrationError(
                "schema-v1 snapshot contains both StealthComponent and SneakingComponent"
            )
        components["SneakingComponent"] = components.pop("StealthComponent")
    legacy_cure_request = components.pop("CureQuestHookComponent", None)
    if legacy_cure_request is not None:
        if "CureRequestComponent" in components:
            raise WorldMigrationError(
                "schema-v1 snapshot contains both CureQuestHookComponent and CureRequestComponent"
            )
        components["CureRequestComponent"] = legacy_cure_request
    quest_index = _quest_index(components)
    states = _records(components, "QuestStateComponent")
    quests = _records(components, "QuestComponent")

    recipes = _records(components, "PotionRecipeComponent")
    for recipe_id, fields in sorted(recipes.items()):
        fields = dict(fields)
        ingredient_ids = fields.pop("ingredient_ids", ()) or ()
        if not isinstance(ingredient_ids, (list, tuple)):
            raise WorldMigrationError(
                f"PotionRecipeComponent.ingredient_ids for {recipe_id!r} must be a sequence"
            )
        recipes[recipe_id] = fields
        for order, ingredient_id in enumerate(ingredient_ids):
            target_id = _live_target(
                entities,
                ingredient_id,
                owner_id=recipe_id,
                component="PotionRecipeComponent",
                field="ingredient_ids",
            )
            _add_edge(
                relationships,
                "DependsOnIngredient",
                recipe_id,
                target_id,
                {"order": order},
            )

    eggs = _records(components, "EggComponent")
    for egg_id, fields in sorted(eggs.items()):
        fields = dict(fields)
        parent_ids = fields.pop("parent_ids", ()) or ()
        if not isinstance(parent_ids, (list, tuple)):
            raise WorldMigrationError(f"EggComponent.parent_ids for {egg_id!r} must be a sequence")
        eggs[egg_id] = fields
        for order, parent_id in enumerate(parent_ids):
            target_id = _live_target(
                entities,
                parent_id,
                owner_id=egg_id,
                component="EggComponent",
                field="parent_ids",
            )
            _add_edge(
                relationships,
                "DescendsFromParent",
                egg_id,
                target_id,
                {"order": order},
            )

    allowed_areas = components.pop("AllowedAreaComponent", {})
    if not isinstance(allowed_areas, dict):
        raise WorldMigrationError("persisted type 'AllowedAreaComponent' must be a mapping")
    for character_id, fields in sorted(allowed_areas.items()):
        fields = dict(fields)
        room_ids = fields.pop("room_ids", ()) or ()
        if not isinstance(room_ids, (list, tuple)):
            raise WorldMigrationError(
                f"AllowedAreaComponent.room_ids for {character_id!r} must be a sequence"
            )
        for room_id in room_ids:
            target_id = _live_target(
                entities,
                room_id,
                owner_id=character_id,
                component="AllowedAreaComponent",
                field="room_ids",
            )
            _add_edge(relationships, "AllowedIn", character_id, target_id)

    caravans = _records(components, "CaravanComponent")
    for caravan_id, fields in sorted(caravans.items()):
        fields = dict(fields)
        member_ids = fields.pop("member_ids", ()) or ()
        if not isinstance(member_ids, (list, tuple)):
            raise WorldMigrationError(
                f"CaravanComponent.member_ids for {caravan_id!r} must be a sequence"
            )
        caravans[caravan_id] = fields
        for member_id in member_ids:
            target_id = _live_target(
                entities,
                member_id,
                owner_id=caravan_id,
                component="CaravanComponent",
                field="member_ids",
            )
            _add_edge(relationships, "MemberOfCaravan", target_id, caravan_id)

    safe_storages = _records(components, "SafeStorageComponent")
    for storage_id, fields in sorted(safe_storages.items()):
        fields = dict(fields)
        item_ids = fields.pop("item_ids", ()) or ()
        if not isinstance(item_ids, (list, tuple)):
            raise WorldMigrationError(
                f"SafeStorageComponent.item_ids for {storage_id!r} must be a sequence"
            )
        safe_storages[storage_id] = fields
        for item_id in item_ids:
            target_id = _live_target(
                entities,
                item_id,
                owner_id=storage_id,
                component="SafeStorageComponent",
                field="item_ids",
            )
            _add_edge(relationships, "StoredIn", target_id, storage_id)

    service_access = components.pop("ServiceAccessComponent", {})
    if not isinstance(service_access, dict):
        raise WorldMigrationError("persisted type 'ServiceAccessComponent' must be a mapping")
    for character_id, fields in sorted(service_access.items()):
        fields = dict(fields)
        service_ids = fields.pop("service_ids", ()) or ()
        if not isinstance(service_ids, (list, tuple)):
            raise WorldMigrationError(
                f"ServiceAccessComponent.service_ids for {character_id!r} must be a sequence"
            )
        for service_id in service_ids:
            target_id = _live_target(
                entities,
                service_id,
                owner_id=character_id,
                component="ServiceAccessComponent",
                field="service_ids",
            )
            _add_edge(relationships, "HasAccessToService", character_id, target_id)

    festivals = _records(components, "FestivalComponent")
    for festival_id, fields in sorted(festivals.items()):
        fields = dict(fields)
        participant_ids = fields.pop("joined_character_ids", ()) or ()
        if not isinstance(participant_ids, (list, tuple)):
            raise WorldMigrationError(
                f"FestivalComponent.joined_character_ids for {festival_id!r} must be a sequence"
            )
        festivals[festival_id] = fields
        for character_id in participant_ids:
            target_id = _live_target(
                entities,
                character_id,
                owner_id=festival_id,
                component="FestivalComponent",
                field="joined_character_ids",
            )
            _add_edge(relationships, "MemberOfFestival", target_id, festival_id)

    away_teams = _records(components, "AwayTeamComponent")
    for team_id, fields in sorted(away_teams.items()):
        fields = dict(fields)
        member_ids = fields.pop("member_ids", ()) or ()
        if not isinstance(member_ids, (list, tuple)):
            raise WorldMigrationError(
                f"AwayTeamComponent.member_ids for {team_id!r} must be a sequence"
            )
        away_teams[team_id] = fields
        for member_id in member_ids:
            target_id = _live_target(
                entities,
                member_id,
                owner_id=team_id,
                component="AwayTeamComponent",
                field="member_ids",
            )
            _add_edge(relationships, "MemberOfAwayTeam", target_id, team_id)

    rumors = _records(components, "RumorComponent")
    for rumor_id, fields in sorted(rumors.items()):
        fields = dict(fields)
        listener_ids = fields.pop("heard_by", ()) or ()
        if not isinstance(listener_ids, (list, tuple)):
            raise WorldMigrationError(
                f"RumorComponent.heard_by for {rumor_id!r} must be a sequence"
            )
        rumors[rumor_id] = fields
        for listener_id in listener_ids:
            target_id = _live_target(
                entities,
                listener_id,
                owner_id=rumor_id,
                component="RumorComponent",
                field="heard_by",
            )
            _add_edge(relationships, "RumorHeardBy", rumor_id, target_id)

    rumor_sources = components.pop("RumorSourceComponent", {})
    if not isinstance(rumor_sources, dict):
        raise WorldMigrationError("persisted type 'RumorSourceComponent' must be a mapping")
    for rumor_id, fields in sorted(rumor_sources.items()):
        source_id = dict(fields).get("source_id")
        if source_id is None:
            continue
        target_id = _live_target(
            entities,
            source_id,
            owner_id=rumor_id,
            component="RumorSourceComponent",
            field="source_id",
        )
        _add_edge(relationships, "OriginatesFromSource", rumor_id, target_id)

    rumor_targets = components.pop("RumorTargetComponent", {})
    if not isinstance(rumor_targets, dict):
        raise WorldMigrationError("persisted type 'RumorTargetComponent' must be a mapping")
    for rumor_id, fields in sorted(rumor_targets.items()):
        target_id = _live_target(
            entities,
            dict(fields).get("target_id"),
            owner_id=rumor_id,
            component="RumorTargetComponent",
            field="target_id",
        )
        _add_edge(relationships, "RefersToSubject", rumor_id, target_id)

    generated = components.pop("GeneratedQuestComponent", {})
    for order, (entity_id, fields) in enumerate(sorted(generated.items()), start=1):
        if entity_id in quests:
            raise WorldMigrationError(
                f"schema-v1 entity {entity_id!r} has both quest component families"
            )
        fields = dict(fields)
        status = str(fields.pop("status", "offered"))
        accepted_by = fields.pop("accepted_by", None)
        title = str(fields.pop("title", entity_id))
        description = str(fields.pop("objective", ""))
        quests[entity_id] = {
            "quest_id": entity_id,
            "title": title,
            "description": description,
        }
        states.setdefault(entity_id, {}).setdefault("status", status)
        _records(components, "QuestProvenanceComponent")[entity_id] = {
            "generator": "bunnyland.dragonsim",
            "source_id": "",
            "generated_at_epoch": 0,
        }
        objective_id = _synthetic_id(entities, "quest_objective", order)
        entities[objective_id] = {"prefab": "quest_objective", "created_epoch": 0}
        _records(components, "QuestObjectiveComponent")[objective_id] = {
            "quest_id": entity_id,
            "description": description,
            "completed": status == "completed",
            "completed_by": accepted_by if status == "completed" else None,
        }
        _add_edge(
            relationships,
            "QuestHasObjective",
            entity_id,
            objective_id,
            {"order": 0},
        )
        if accepted_by:
            _add_edge(relationships, "QuestAcceptedBy", entity_id, str(accepted_by))

    for entity_id, fields in sorted(quests.items()):
        fields = dict(fields)
        status = str(fields.pop("status", "offered"))
        accepted_by = fields.pop("accepted_by", ()) or ()
        completed_at = fields.pop("completed_at_epoch", None)
        fields.setdefault("description", "")
        quests[entity_id] = fields
        state = states.setdefault(entity_id, {})
        state.setdefault("status", status)
        if completed_at is not None:
            state["completed_at_epoch"] = completed_at
        if isinstance(accepted_by, str):
            accepted_by = (accepted_by,)
        if not isinstance(accepted_by, (list, tuple)):
            raise WorldMigrationError(
                f"QuestComponent.accepted_by for {entity_id!r} must be a sequence"
            )
        for participant_id in accepted_by:
            _add_edge(relationships, "QuestAcceptedBy", entity_id, str(participant_id))

    stages = components.pop("QuestStageComponent", {})
    if not isinstance(stages, dict):
        raise WorldMigrationError("persisted type 'QuestStageComponent' must be a mapping")
    seen_stages: set[str] = set()
    for stage_id, fields in sorted(stages.items()):
        fields = dict(fields)
        quest_id = _resolve_quest(quest_index, fields.pop("quest_id", None), stage_id)
        if quest_id in seen_stages:
            raise WorldMigrationError(
                f"schema-v1 quest {quest_id!r} has multiple lifecycle components"
            )
        seen_stages.add(quest_id)
        tracked_by = fields.pop("tracked_by", ()) or ()
        states.setdefault(quest_id, {}).update(fields)
        for character_id in tracked_by:
            _add_edge(relationships, "TracksQuest", str(character_id), quest_id)

    deadlines = components.pop("QuestDeadlineComponent", {})
    if not isinstance(deadlines, dict):
        raise WorldMigrationError("persisted type 'QuestDeadlineComponent' must be a mapping")
    for owner_id, fields in sorted(deadlines.items()):
        quest_id = _resolve_quest(quest_index, owner_id, owner_id)
        state = states.setdefault(quest_id, {})
        if state.get("due_at_epoch") not in (None, fields.get("due_at_epoch")):
            raise WorldMigrationError(f"schema-v1 quest {quest_id!r} has conflicting deadlines")
        state["due_at_epoch"] = fields.get("due_at_epoch")

    objectives = _records(components, "QuestObjectiveComponent")
    for order, (objective_id, fields) in enumerate(sorted(objectives.items())):
        fields = dict(fields)
        quest_id = _resolve_quest(quest_index, fields.pop("quest_id", None), objective_id)
        objectives[objective_id] = fields
        _add_edge(
            relationships,
            "QuestHasObjective",
            quest_id,
            objective_id,
            {"order": order},
        )

    rewards = _records(components, "QuestRewardComponent")
    for order, (reward_id, fields) in enumerate(sorted(rewards.items())):
        fields = dict(fields)
        quest_id = _resolve_quest(quest_index, fields.pop("quest_id", None), reward_id)
        item_ids = fields.pop("item_ids", ()) or ()
        rewards[reward_id] = fields
        _add_edge(
            relationships,
            "QuestHasReward",
            quest_id,
            reward_id,
            {"order": order},
        )
        for item_order, item_id in enumerate(item_ids):
            _add_edge(
                relationships,
                "QuestRewardGrants",
                reward_id,
                str(item_id),
                {"order": item_order},
            )

    dagger_rewards = components.pop("DaggerQuestRewardComponent", {})
    if not isinstance(dagger_rewards, dict):
        raise WorldMigrationError("persisted type 'DaggerQuestRewardComponent' must be a mapping")
    for order, (quest_id, fields) in enumerate(sorted(dagger_rewards.items()), start=1):
        quest_id = _resolve_quest(quest_index, quest_id, quest_id)
        reward_id = _synthetic_id(entities, "quest_reward", order)
        entities[reward_id] = {"prefab": "quest_reward", "created_epoch": 0}
        fields = dict(fields)
        rewards[reward_id] = {
            "description": str(fields.pop("item_name", "")),
            "claimed": bool(fields.pop("claimed", False)),
            "claimed_by": fields.pop("claimed_by", None),
        }
        _add_edge(
            relationships,
            "QuestHasReward",
            quest_id,
            reward_id,
            {"order": order},
        )

    bunnyland = _table(snapshot, "bunnyland")
    bunnyland["schema_version"] = CURRENT_SCHEMA_VERSION
    return snapshot


def migrate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a validated schema-v2 copy of a raw JSON/YAML snapshot."""

    if not isinstance(snapshot, dict):
        raise WorldMigrationError("world snapshot must be a mapping")
    migrated = deepcopy(snapshot)
    bunnyland = _table(migrated, "bunnyland")
    version = bunnyland.get("schema_version", 1)
    if not isinstance(version, int):
        raise WorldMigrationError("bunnyland.schema_version must be an integer")
    if version > CURRENT_SCHEMA_VERSION:
        raise WorldMigrationError(
            f"world schema {version} is newer than supported schema {CURRENT_SCHEMA_VERSION}"
        )
    if version < 1:
        raise WorldMigrationError(f"unsupported world schema {version}")
    if version == CURRENT_SCHEMA_VERSION:
        for section in ("entities", "components", "relationships"):
            _table(migrated, section)
        return migrated
    return _migrate_v1(migrated)


__all__ = ["CURRENT_SCHEMA_VERSION", "WorldMigrationError", "migrate_snapshot"]
