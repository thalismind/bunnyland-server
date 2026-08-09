"""One-way migrations for persisted Bunnyland world snapshots."""

from __future__ import annotations

from copy import deepcopy

from pydantic import JsonValue

CURRENT_SCHEMA_VERSION = 5


class WorldMigrationError(ValueError):
    """A saved world cannot be migrated without guessing at its meaning."""


def _table(snapshot: dict[str, JsonValue], section: str) -> dict[str, JsonValue]:
    value = snapshot.setdefault(section, {})
    if not isinstance(value, dict):
        raise WorldMigrationError(f"world snapshot section {section!r} must be a mapping")
    return value


def _records(table: dict[str, JsonValue], type_name: str) -> dict[str, JsonValue]:
    value = table.setdefault(type_name, {})
    if not isinstance(value, dict):
        raise WorldMigrationError(f"persisted type {type_name!r} must contain a mapping")
    return value


def _drop_empty_relationship_buckets(relationships: object) -> None:
    """Discard source buckets that contain no persisted edges.

    Older snapshots can contain these after the last edge of a type was removed from an
    entity.  They carry no graph state, but schema-v4 source validation would otherwise
    treat the source as owning an edge and require the edge's driving component.
    """

    if not isinstance(relationships, dict):
        return
    for sources in relationships.values():
        if not isinstance(sources, dict):
            continue
        for source_id, records in tuple(sources.items()):
            if isinstance(records, list) and not records:
                del sources[source_id]


def _add_edge(
    relationships: dict[str, JsonValue],
    edge_name: str,
    source_id: str,
    target_id: str,
    fields: dict[str, JsonValue] | None = None,
) -> None:
    sources = _records(relationships, edge_name)
    edges = sources.setdefault(source_id, [])
    if not isinstance(edges, list):
        raise WorldMigrationError(f"{edge_name} edges for {source_id!r} must be a list")
    record = {"target": target_id, "edge": fields or {}}
    if record not in edges:
        edges.append(record)


def _synthetic_id(entities: dict[str, JsonValue], prefab: str, ordinal: int) -> str:
    sequence = ordinal
    while f"{prefab}_{sequence}" in entities:
        sequence += 1
    return f"{prefab}_{sequence}"


def _live_target(
    entities: dict[str, JsonValue],
    target_id: JsonValue,
    *,
    owner_id: str,
    component: str,
    field: str,
) -> str:
    target = str(target_id or "")
    if target not in entities:
        raise WorldMigrationError(
            f"schema-v1 entity {owner_id!r} component {component}.{field} "
            f"refers to missing entity {target!r}"
        )
    return target


def _live_target_or_label(
    entities: dict[str, JsonValue],
    components: dict[str, JsonValue],
    target_id: JsonValue,
    *,
    owner_id: str,
    component: str,
    field: str,
    target_component: str,
    label_field: str,
) -> str:
    target = str(target_id or "")
    typed_targets = _records(components, target_component)
    if target in entities:
        if target not in typed_targets:
            raise WorldMigrationError(
                f"schema-v1 entity {owner_id!r} component {component}.{field} "
                f"refers to entity {target!r} without {target_component}"
            )
        return target
    matches = [
        entity_id
        for entity_id, fields in typed_targets.items()
        if isinstance(fields, dict) and str(fields.get(label_field, "")) == target
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise WorldMigrationError(
            f"schema-v1 entity {owner_id!r} component {component}.{field} "
            f"has ambiguous {target_component}.{label_field} label {target!r}"
        )
    return _live_target(
        entities,
        target,
        owner_id=owner_id,
        component=component,
        field=field,
    )


def _score_map(
    fields: JsonValue, *, owner_id: str, component: str, field: str
) -> dict[str, int]:
    if not isinstance(fields, dict):
        raise WorldMigrationError(f"{component} fields for {owner_id!r} must be a mapping")
    scores = fields.get(field, {})
    if not isinstance(scores, dict):
        raise WorldMigrationError(f"{component}.{field} for {owner_id!r} must be a mapping")
    normalized: dict[str, int] = {}
    for target, value in scores.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise WorldMigrationError(
                f"{component}.{field} for {owner_id!r} must contain integer values"
            )
        normalized[str(target)] = value
    return normalized


def _canonical_decoration_role(
    value: JsonValue, *, owner_id: str, persisted_type: str
) -> str:
    role = str(value or "")
    if "/" in role:
        return role
    if role in {"flora", "detail", "light", "particles"}:
        return f"bunnyland.3d/{role}"
    raise WorldMigrationError(
        f"schema-v1 entity {owner_id!r} persisted type {persisted_type}.role "
        f"contains unknown decoration role {role!r}"
    )


def _quest_index(components: dict[str, JsonValue]) -> dict[str, str]:
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


def _resolve_quest(index: dict[str, str], quest_key: JsonValue, owner_id: str) -> str:
    key = str(quest_key or "")
    try:
        return index[key]
    except KeyError as exc:
        raise WorldMigrationError(
            f"schema-v1 record {owner_id!r} refers to unknown quest {key!r}"
        ) from exc


def _migrate_v1(snapshot: dict[str, JsonValue]) -> dict[str, JsonValue]:
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

    if "DecorationSource3DComponent" in components:
        decoration_sources = _records(components, "DecorationSource3DComponent")
        for entity_id, fields in decoration_sources.items():
            if not isinstance(fields, dict):
                raise WorldMigrationError(
                    f"DecorationSource3DComponent fields for {entity_id!r} must be a mapping"
                )
            fields["role"] = _canonical_decoration_role(
                fields.get("role"),
                owner_id=entity_id,
                persisted_type="DecorationSource3DComponent",
            )

    if "HasDecoration3D" in relationships:
        decoration_edges = _records(relationships, "HasDecoration3D")
        for source_id, edges in decoration_edges.items():
            if not isinstance(edges, list):
                raise WorldMigrationError(f"HasDecoration3D edges for {source_id!r} must be a list")
            for record in edges:
                if not isinstance(record, dict) or not isinstance(record.get("edge"), dict):
                    raise WorldMigrationError(
                        f"HasDecoration3D edge for {source_id!r} must be a mapping"
                    )
                fields = record["edge"]
                fields["role"] = _canonical_decoration_role(
                    fields.get("role"),
                    owner_id=source_id,
                    persisted_type="HasDecoration3D",
                )

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

    guard_records = components.pop("GuardComponent", {})
    if not isinstance(guard_records, dict):
        raise WorldMigrationError("persisted type 'GuardComponent' must contain a mapping")
    for guard_id, fields in sorted(guard_records.items()):
        if not isinstance(fields, dict):
            raise WorldMigrationError(f"GuardComponent fields for {guard_id!r} must be a mapping")
        faction_id = _live_target_or_label(
            entities,
            components,
            fields.get("faction_id"),
            owner_id=guard_id,
            component="GuardComponent",
            field="faction_id",
            target_component="FactionComponent",
            label_field="name",
        )
        bribe_amount = fields.get("bribe_amount", 10)
        if not isinstance(bribe_amount, int) or isinstance(bribe_amount, bool):
            raise WorldMigrationError(
                f"GuardComponent.bribe_amount for {guard_id!r} must be an integer"
            )
        _add_edge(
            relationships,
            "GuardsForFaction",
            guard_id,
            faction_id,
            {"bribe_amount": bribe_amount},
        )

    jail_records = components.pop("JailComponent", {})
    if not isinstance(jail_records, dict):
        raise WorldMigrationError("persisted type 'JailComponent' must contain a mapping")
    for character_id, fields in sorted(jail_records.items()):
        if not isinstance(fields, dict):
            raise WorldMigrationError(
                f"JailComponent fields for {character_id!r} must be a mapping"
            )
        faction_id = _live_target_or_label(
            entities,
            components,
            fields.get("faction_id"),
            owner_id=character_id,
            component="JailComponent",
            field="faction_id",
            target_component="FactionComponent",
            label_field="name",
        )
        release_epoch = fields.get("release_epoch")
        if not isinstance(release_epoch, int) or isinstance(release_epoch, bool):
            raise WorldMigrationError(
                f"JailComponent.release_epoch for {character_id!r} must be an integer"
            )
        _add_edge(
            relationships,
            "JailedByFaction",
            character_id,
            faction_id,
            {
                "release_epoch": release_epoch,
                "reason": str(fields.get("reason", "sentence")),
            },
        )

    travel_plans = components.pop("TravelPlanComponent", {})
    if not isinstance(travel_plans, dict):
        raise WorldMigrationError("persisted type 'TravelPlanComponent' must contain a mapping")
    for character_id, fields in sorted(travel_plans.items()):
        if not isinstance(fields, dict):
            raise WorldMigrationError(
                f"TravelPlanComponent fields for {character_id!r} must be a mapping"
            )
        destination_id = _live_target_or_label(
            entities,
            components,
            fields.get("destination_id"),
            owner_id=character_id,
            component="TravelPlanComponent",
            field="destination_id",
            target_component="TravelHubComponent",
            label_field="name",
        )
        edge_fields = {
            "started_at_epoch": fields.get("started_at_epoch"),
            "arrive_at_epoch": fields.get("arrive_at_epoch"),
            "mode": str(fields.get("mode", "foot")),
            "route_label": str(fields.get("route_label", "")),
        }
        for field_name in ("started_at_epoch", "arrive_at_epoch"):
            value = edge_fields[field_name]
            if not isinstance(value, int) or isinstance(value, bool):
                raise WorldMigrationError(
                    f"TravelPlanComponent.{field_name} for {character_id!r} must be an integer"
                )
        _add_edge(
            relationships,
            "TravelingToDestination",
            character_id,
            destination_id,
            edge_fields,
        )

    recall_anchors = components.pop("RecallAnchorComponent", {})
    if not isinstance(recall_anchors, dict):
        raise WorldMigrationError("persisted type 'RecallAnchorComponent' must contain a mapping")
    for character_id, fields in sorted(recall_anchors.items()):
        if not isinstance(fields, dict):
            raise WorldMigrationError(
                f"RecallAnchorComponent fields for {character_id!r} must be a mapping"
            )
        room_id = _live_target(
            entities,
            fields.get("room_id"),
            owner_id=character_id,
            component="RecallAnchorComponent",
            field="room_id",
        )
        if room_id not in _records(components, "RoomComponent"):
            raise WorldMigrationError(
                f"schema-v1 entity {character_id!r} component RecallAnchorComponent.room_id "
                f"refers to entity {room_id!r} without RoomComponent"
            )
        _add_edge(relationships, "AnchoredToRoom", character_id, room_id)

    secret_doors = _records(components, "SecretDoorComponent")
    for door_id, fields in sorted(secret_doors.items()):
        if not isinstance(fields, dict):
            raise WorldMigrationError(
                f"SecretDoorComponent fields for {door_id!r} must be a mapping"
            )
        fields = dict(fields)
        target = fields.pop("target_room_id", None)
        secret_doors[door_id] = fields
        target_room_id = _live_target(
            entities,
            target,
            owner_id=door_id,
            component="SecretDoorComponent",
            field="target_room_id",
        )
        if target_room_id not in _records(components, "RoomComponent"):
            raise WorldMigrationError(
                f"schema-v1 entity {door_id!r} component SecretDoorComponent.target_room_id "
                f"refers to entity {target_room_id!r} without RoomComponent"
            )
        _add_edge(relationships, "OpensIntoRoom", door_id, target_room_id)

    dungeons = _records(components, "DungeonComponent")
    for dungeon_id, fields in sorted(dungeons.items()):
        if not isinstance(fields, dict):
            raise WorldMigrationError(
                f"DungeonComponent fields for {dungeon_id!r} must be a mapping"
            )
        fields = dict(fields)
        entry = fields.pop("entry_room_id", None)
        dungeons[dungeon_id] = fields
        if entry is None:
            continue
        entry_room_id = _live_target(
            entities,
            entry,
            owner_id=dungeon_id,
            component="DungeonComponent",
            field="entry_room_id",
        )
        if entry_room_id not in _records(components, "DungeonRoomComponent"):
            raise WorldMigrationError(
                f"schema-v1 entity {dungeon_id!r} component DungeonComponent.entry_room_id "
                f"refers to entity {entry_room_id!r} without DungeonRoomComponent"
            )
        _add_edge(relationships, "EnteredThroughRoom", dungeon_id, entry_room_id)

    standing_maps = (
        (
            "FactionReputationComponent",
            "HasStandingWithFaction",
            "FactionComponent",
            "name",
        ),
        (
            "InstitutionReputationComponent",
            "HasStandingWithInstitution",
            "InstitutionComponent",
            "name",
        ),
        (
            "RegionalReputationComponent",
            "HasStandingInRegion",
            "LawRegionComponent",
            "region_id",
        ),
        (
            "LegalReputationComponent",
            "HasLegalStandingInRegion",
            "LawRegionComponent",
            "region_id",
        ),
    )
    for component_name, edge_name, target_component, label_field in standing_maps:
        records = components.pop(component_name, {})
        if not isinstance(records, dict):
            raise WorldMigrationError(f"persisted type {component_name!r} must contain a mapping")
        for owner_id, fields in sorted(records.items()):
            for target, score in _score_map(
                fields,
                owner_id=owner_id,
                component=component_name,
                field="scores",
            ).items():
                target_id = _live_target_or_label(
                    entities,
                    components,
                    target,
                    owner_id=owner_id,
                    component=component_name,
                    field="scores",
                    target_component=target_component,
                    label_field=label_field,
                )
                _add_edge(relationships, edge_name, owner_id, target_id, {"score": score})

    wanted = components.pop("WantedComponent", {})
    if not isinstance(wanted, dict):
        raise WorldMigrationError("persisted type 'WantedComponent' must contain a mapping")
    for character_id, fields in sorted(wanted.items()):
        for faction, amount in _score_map(
            fields,
            owner_id=character_id,
            component="WantedComponent",
            field="amounts",
        ).items():
            faction_id = _live_target_or_label(
                entities,
                components,
                faction,
                owner_id=character_id,
                component="WantedComponent",
                field="amounts",
                target_component="FactionComponent",
                label_field="name",
            )
            _add_edge(
                relationships,
                "WantedByFaction",
                character_id,
                faction_id,
                {"amount": amount},
            )

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
    bunnyland["schema_version"] = 2
    return snapshot


def _v2_live_target(
    entities: dict[str, JsonValue],
    target_id: JsonValue,
    *,
    owner_id: str,
    component: str,
    field: str,
) -> str:
    target = str(target_id or "")
    if target not in entities:
        raise WorldMigrationError(
            f"schema-v2 entity {owner_id!r} component {component}.{field} "
            f"refers to missing entity {target!r}"
        )
    return target


def _migrate_v2(snapshot: dict[str, JsonValue]) -> dict[str, JsonValue]:
    components = _table(snapshot, "components")
    relationships = _table(snapshot, "relationships")
    entities = _table(snapshot, "entities")
    characters = _records(components, "CharacterComponent")
    rooms = _records(components, "RoomComponent")

    homes = components.pop("HomeComponent", {})
    if not isinstance(homes, dict):
        raise WorldMigrationError("persisted type 'HomeComponent' must contain a mapping")
    for room_id, raw_fields in sorted(homes.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(f"HomeComponent fields for {room_id!r} must be a mapping")
        _v2_live_target(
            entities,
            room_id,
            owner_id=room_id,
            component="HomeComponent",
            field="entity",
        )
        if room_id not in rooms:
            raise WorldMigrationError(
                f"schema-v2 entity {room_id!r} component HomeComponent.entity "
                "does not have RoomComponent"
            )
        owner_id = _v2_live_target(
            entities,
            raw_fields.get("owner_id"),
            owner_id=room_id,
            component="HomeComponent",
            field="owner_id",
        )
        if owner_id not in characters:
            raise WorldMigrationError(
                f"schema-v2 entity {room_id!r} component HomeComponent.owner_id "
                f"refers to entity {owner_id!r} without CharacterComponent"
            )
        _add_edge(
            relationships,
            "OwnsHome",
            owner_id,
            room_id,
            {"household_id": raw_fields.get("household_id")},
        )

    claims = components.pop("RoomClaimComponent", {})
    if not isinstance(claims, dict):
        raise WorldMigrationError("persisted type 'RoomClaimComponent' must contain a mapping")
    for room_id, raw_fields in sorted(claims.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"RoomClaimComponent fields for {room_id!r} must be a mapping"
            )
        _v2_live_target(
            entities,
            room_id,
            owner_id=room_id,
            component="RoomClaimComponent",
            field="entity",
        )
        if room_id not in rooms:
            raise WorldMigrationError(
                f"schema-v2 entity {room_id!r} component RoomClaimComponent.entity "
                "does not have RoomComponent"
            )
        claimant_id = _v2_live_target(
            entities,
            raw_fields.get("claimed_by_id"),
            owner_id=room_id,
            component="RoomClaimComponent",
            field="claimed_by_id",
        )
        if claimant_id not in characters:
            raise WorldMigrationError(
                f"schema-v2 entity {room_id!r} component RoomClaimComponent.claimed_by_id "
                f"refers to entity {claimant_id!r} without CharacterComponent"
            )
        claimed_at_epoch = raw_fields.get("claimed_at_epoch")
        if not isinstance(claimed_at_epoch, int) or isinstance(claimed_at_epoch, bool):
            raise WorldMigrationError(
                f"RoomClaimComponent.claimed_at_epoch for {room_id!r} must be an integer"
            )
        _add_edge(
            relationships,
            "ClaimsRoom",
            claimant_id,
            room_id,
            {"claimed_at_epoch": claimed_at_epoch},
        )

    pregnancies = _records(components, "PregnancyComponent")
    for pregnant_id, raw_fields in sorted(pregnancies.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"PregnancyComponent fields for {pregnant_id!r} must be a mapping"
            )
        fields = dict(raw_fields)
        co_parent_ids = fields.pop("co_parent_ids", ()) or ()
        if not isinstance(co_parent_ids, (list, tuple)):
            raise WorldMigrationError(
                f"PregnancyComponent.co_parent_ids for {pregnant_id!r} must be a sequence"
            )
        pregnancies[pregnant_id] = fields
        for co_parent_id in co_parent_ids:
            target_id = _v2_live_target(
                entities,
                co_parent_id,
                owner_id=pregnant_id,
                component="PregnancyComponent",
                field="co_parent_ids",
            )
            if target_id not in characters:
                raise WorldMigrationError(
                    f"schema-v2 entity {pregnant_id!r} component "
                    f"PregnancyComponent.co_parent_ids refers to entity {target_id!r} "
                    "without CharacterComponent"
                )
            _add_edge(relationships, "PregnancyCoParent", pregnant_id, target_id)

    _table(snapshot, "bunnyland")["schema_version"] = 3
    _validate_v3(snapshot)
    return snapshot


def _validate_v3(snapshot: dict[str, JsonValue]) -> None:
    components = _table(snapshot, "components")
    relationships = _table(snapshot, "relationships")
    entities = _table(snapshot, "entities")

    def read_records(table: dict[str, JsonValue], type_name: str) -> dict[str, JsonValue]:
        value = table.get(type_name, {})
        if not isinstance(value, dict):
            raise WorldMigrationError(f"persisted type {type_name!r} must contain a mapping")
        return value

    characters = read_records(components, "CharacterComponent")
    rooms = read_records(components, "RoomComponent")
    pregnancies = read_records(components, "PregnancyComponent")
    for pregnant_id, fields in pregnancies.items():
        if not isinstance(fields, dict):
            raise WorldMigrationError(
                f"PregnancyComponent fields for {pregnant_id!r} must be a mapping"
            )
        if "co_parent_ids" in fields:
            raise WorldMigrationError(
                f"schema-v3 entity {pregnant_id!r} contains legacy PregnancyComponent.co_parent_ids"
            )
    for legacy in ("HomeComponent", "RoomClaimComponent"):
        if read_records(components, legacy):
            raise WorldMigrationError(f"schema-v3 snapshot contains legacy {legacy}")

    incoming: dict[tuple[str, str], str] = {}
    for edge_name in ("OwnsHome", "ClaimsRoom", "PregnancyCoParent"):
        sources = read_records(relationships, edge_name)
        seen_edges: set[tuple[str, str]] = set()
        for source_id, records in sorted(sources.items()):
            if source_id not in entities:
                raise WorldMigrationError(
                    f"schema-v3 {edge_name} source {source_id!r} does not exist"
                )
            if not isinstance(records, list):
                raise WorldMigrationError(f"{edge_name} edges for {source_id!r} must be a list")
            for record in records:
                if not isinstance(record, dict) or not isinstance(record.get("edge", {}), dict):
                    raise WorldMigrationError(
                        f"{edge_name} edge for {source_id!r} must be a mapping"
                    )
                target_id = str(record.get("target") or "")
                if target_id not in entities:
                    raise WorldMigrationError(
                        f"schema-v3 {edge_name} edge owned by {source_id!r} "
                        f"refers to missing target {target_id!r}"
                    )
                pair = (source_id, target_id)
                if pair in seen_edges:
                    raise WorldMigrationError(
                        f"schema-v3 contains duplicate {edge_name} edge "
                        f"{source_id!r} -> {target_id!r}"
                    )
                seen_edges.add(pair)
                if source_id not in characters:
                    raise WorldMigrationError(
                        f"schema-v3 {edge_name} source {source_id!r} is not a character"
                    )
                if edge_name in {"OwnsHome", "ClaimsRoom"}:
                    if target_id not in rooms:
                        raise WorldMigrationError(
                            f"schema-v3 {edge_name} target {target_id!r} is not a room"
                        )
                    key = (edge_name, target_id)
                    previous = incoming.get(key)
                    if previous is not None and previous != source_id:
                        raise WorldMigrationError(
                            f"schema-v3 room {target_id!r} has multiple incoming {edge_name} edges"
                        )
                    incoming[key] = source_id
                    edge_fields = record.get("edge", {})
                    if edge_name == "OwnsHome":
                        household_id = edge_fields.get("household_id")
                        if household_id is not None and not isinstance(household_id, str):
                            raise WorldMigrationError(
                                f"schema-v3 OwnsHome.household_id for {source_id!r} "
                                "must be a string or null"
                            )
                    else:
                        claimed_at_epoch = edge_fields.get("claimed_at_epoch")
                        if not isinstance(claimed_at_epoch, int) or isinstance(
                            claimed_at_epoch, bool
                        ):
                            raise WorldMigrationError(
                                f"schema-v3 ClaimsRoom.claimed_at_epoch for {source_id!r} "
                                "must be an integer"
                            )
                else:
                    if source_id not in pregnancies:
                        raise WorldMigrationError(
                            f"schema-v3 PregnancyCoParent source {source_id!r} "
                            "does not have PregnancyComponent"
                        )
                    if target_id not in characters:
                        raise WorldMigrationError(
                            f"schema-v3 PregnancyCoParent target {target_id!r} is not a character"
                        )
                    if record.get("edge"):
                        raise WorldMigrationError(
                            f"schema-v3 PregnancyCoParent edge for {source_id!r} "
                            "must not contain properties"
                        )


def _v3_live_target(
    entities: dict[str, JsonValue],
    target_id: JsonValue,
    *,
    owner_id: str,
    component: str,
    field: str,
) -> str:
    target = str(target_id or "")
    if target not in entities:
        raise WorldMigrationError(
            f"schema-v3 entity {owner_id!r} component {component}.{field} "
            f"refers to missing entity {target!r}"
        )
    return target


def _migrate_live_field(
    components: dict[str, JsonValue],
    relationships: dict[str, JsonValue],
    entities: dict[str, JsonValue],
    *,
    component: str,
    field: str,
    edge: str,
    optional: bool = False,
    many: bool = False,
) -> None:
    for owner_id, raw_fields in sorted(_records(components, component).items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(f"{component} fields for {owner_id!r} must be a mapping")
        if field not in raw_fields:
            continue
        raw_targets = raw_fields.pop(field)
        if many:
            if not isinstance(raw_targets, (list, tuple)):
                raise WorldMigrationError(
                    f"schema-v3 entity {owner_id!r} component {component}.{field} "
                    "must be a sequence"
                )
            targets = raw_targets
        else:
            targets = (raw_targets,)
        for raw_target in targets:
            if optional and raw_target in (None, ""):
                continue
            target_id = _v3_live_target(
                entities,
                raw_target,
                owner_id=owner_id,
                component=component,
                field=field,
            )
            _add_edge(relationships, edge, owner_id, target_id)


def _migrate_v3(snapshot: dict[str, JsonValue]) -> dict[str, JsonValue]:
    components = _table(snapshot, "components")
    relationships = _table(snapshot, "relationships")
    entities = _table(snapshot, "entities")

    incidents = _records(components, "IncidentComponent")
    contains = _records(relationships, "Contains")
    rooms = _records(components, "RoomComponent")
    for incident_id, raw_fields in sorted(incidents.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"IncidentComponent fields for {incident_id!r} must be a mapping"
            )
        raw_room_id = raw_fields.pop("room_id", None)
        if raw_room_id in (None, ""):
            continue
        room_id = _v3_live_target(
            entities,
            raw_room_id,
            owner_id=incident_id,
            component="IncidentComponent",
            field="room_id",
        )
        if room_id not in rooms:
            raise WorldMigrationError(
                f"schema-v3 entity {incident_id!r} component IncidentComponent.room_id "
                f"refers to entity {room_id!r} without RoomComponent"
            )
        incoming = []
        for source_id, records in contains.items():
            if not isinstance(records, list):
                raise WorldMigrationError(f"Contains edges for {source_id!r} must be a list")
            if any(
                isinstance(record, dict) and record.get("target") == incident_id
                for record in records
            ):
                incoming.append(source_id)
        if incoming and incoming != [room_id]:
            raise WorldMigrationError(
                f"schema-v3 entity {incident_id!r} component IncidentComponent.room_id "
                f"conflicts with incoming Contains edge from {incoming[0]!r}"
            )
        if not incoming:
            _add_edge(
                relationships,
                "Contains",
                room_id,
                incident_id,
                {"mode": "room_content"},
            )

    mappings = (
        ("FossilSurveyComponent", "surveyed_by", "SurveyedBy", False, True),
        ("AncientSampleComponent", "source_fossil_id", "SampledFromFossil", True, False),
        ("CloneCandidateComponent", "source_sample_id", "ClonedFromSample", False, False),
        ("IncubationComponent", "brooded_by", "BroodedBy", True, False),
        ("EggInspectionComponent", "inspected_by", "InspectedBy", False, False),
        ("ImprintComponent", "imprinted_by", "ImprintedBy", False, False),
        ("JuvenileCareComponent", "cared_by", "CaredForBy", False, False),
        ("WaterStudyComponent", "studied_by", "StudiedBy", False, True),
        ("BroodingComponent", "brooder_id", "BroodedBy", False, False),
        ("TrackComponent", "room_id", "TrackedAt", False, False),
        ("TerritoryComponent", "marked_by", "MarkedBy", True, False),
        ("NestComponent", "prepared_by", "PreparedBy", True, False),
        ("BaitComponent", "set_by_id", "SetBy", True, False),
        ("TamingComponent", "tamer_id", "TamedBy", True, False),
        ("MountComponent", "rider_id", "MountedBy", True, False),
        ("GuardBehaviorComponent", "location_id", "GuardsLocation", True, False),
        ("RecallComponent", "home_room_id", "RecallHome", True, False),
        ("EnclosureComponent", "built_by_id", "BuiltBy", True, False),
        ("KaijuComponent", "target_room_id", "KaijuTargets", True, False),
        ("GrappleComponent", "target_id", "Grappling", True, False),
        (
            "CreatureProductComponent",
            "source_creature_id",
            "ProductFromCreature",
            True,
            False,
        ),
        ("RanchLaborComponent", "assigned_by_id", "AssignedBy", True, False),
        ("RanchLaborComponent", "target_id", "RanchWorkTarget", True, False),
        ("GuardAnimalComponent", "assigned_by_id", "AssignedBy", True, False),
        ("GuardAnimalComponent", "location_id", "GuardsLocation", True, False),
        ("RecordedEvidenceComponent", "subject_id", "EvidenceSubject", False, False),
        ("RecordedEvidenceComponent", "device_id", "RecordedByDevice", False, False),
        ("OrbitComponent", "body_id", "OrbitsBody", False, False),
    )
    for component, field, edge, optional, many in mappings:
        _migrate_live_field(
            components,
            relationships,
            entities,
            component=component,
            field=field,
            edge=edge,
            optional=optional,
            many=many,
        )

    eggs = _records(components, "EggComponent")
    dinosaurs = _records(components, "DinosaurComponent")
    characters = _records(components, "CharacterComponent")
    identities = _records(components, "IdentityComponent")
    for hatchling_id, raw_fields in sorted(_records(components, "HatchlingComponent").items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"HatchlingComponent fields for {hatchling_id!r} must be a mapping"
            )
        if "egg_id" not in raw_fields:
            continue
        egg_id = _v3_live_target(
            entities,
            raw_fields.pop("egg_id"),
            owner_id=hatchling_id,
            component="HatchlingComponent",
            field="egg_id",
        )
        egg_fields = eggs.get(egg_id)
        if egg_fields is None:
            dinosaur = dinosaurs.get(hatchling_id, {})
            character = characters.get(hatchling_id, {})
            identity = identities.get(hatchling_id, {})
            species_name = (
                dinosaur.get("species_name") if isinstance(dinosaur, dict) else None
            ) or (character.get("species") if isinstance(character, dict) else None)
            if not species_name and isinstance(identity, dict):
                species_name = str(identity.get("name") or "unknown").removesuffix(" hatchling")
            egg_fields = {
                "species_name": species_name or "unknown",
                "laid_at_epoch": 0,
                "fertilized": True,
                "source": "legacy",
            }
            eggs[egg_id] = egg_fields
        if not isinstance(egg_fields, dict):
            raise WorldMigrationError(f"EggComponent fields for {egg_id!r} must be a mapping")
        egg_fields["hatched"] = True
        _add_edge(relationships, "HatchedFromEgg", hatchling_id, egg_id)

    companions = _records(components, "CompanionComponent")
    for owner_id, raw_fields in sorted(companions.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"CompanionComponent fields for {owner_id!r} must be a mapping"
            )
        target_id = _v3_live_target(
            entities,
            raw_fields.pop("owner_id", None),
            owner_id=owner_id,
            component="CompanionComponent",
            field="owner_id",
        )
        role = raw_fields.pop("role", "companion")
        if not isinstance(role, str) or not role:
            raise WorldMigrationError(
                f"CompanionComponent.role for {owner_id!r} must be a non-empty string"
            )
        _add_edge(relationships, "CompanionOf", owner_id, target_id, {"role": role})

    commands = _records(components, "CommandComponent")
    for owner_id, raw_fields in sorted(commands.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(f"CommandComponent fields for {owner_id!r} must be a mapping")
        commanded_by = raw_fields.pop("commanded_by_id", None)
        if commanded_by not in (None, ""):
            target_id = _v3_live_target(
                entities,
                commanded_by,
                owner_id=owner_id,
                component="CommandComponent",
                field="commanded_by_id",
            )
            _add_edge(relationships, "CommandedBy", owner_id, target_id)
        raw_target = raw_fields.pop("target_id", "")
        if raw_target not in (None, ""):
            target = str(raw_target)
            if target in entities:
                _add_edge(relationships, "CommandTarget", owner_id, target)
            elif raw_fields.get("command_name") == "hunt":
                raw_fields["target_key"] = target
            else:
                _v3_live_target(
                    entities,
                    target,
                    owner_id=owner_id,
                    component="CommandComponent",
                    field="target_id",
                )

    routes = _records(components, "NavigationRouteComponent")
    for owner_id, raw_fields in sorted(routes.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"NavigationRouteComponent fields for {owner_id!r} must be a mapping"
            )
        raw_target = raw_fields.pop("destination_id", "")
        if raw_target in (None, ""):
            continue
        target = str(raw_target)
        if target in entities:
            _add_edge(relationships, "NavigatesTo", owner_id, target)
        elif target.startswith("entity_"):
            _v3_live_target(
                entities,
                target,
                owner_id=owner_id,
                component="NavigationRouteComponent",
                field="destination_id",
            )
        else:
            raw_fields["destination_key"] = target

    _table(snapshot, "bunnyland")["schema_version"] = 4
    _validate_v4(snapshot)
    return snapshot


def _validate_v4(snapshot: dict[str, JsonValue]) -> None:
    _validate_v3(snapshot)
    components = _table(snapshot, "components")
    relationships = _table(snapshot, "relationships")
    entities = _table(snapshot, "entities")

    legacy_fields = {
        "IncidentComponent": ("room_id",),
        "FossilSurveyComponent": ("surveyed_by",),
        "AncientSampleComponent": ("source_fossil_id",),
        "CloneCandidateComponent": ("source_sample_id",),
        "IncubationComponent": ("brooded_by",),
        "HatchlingComponent": ("egg_id",),
        "EggInspectionComponent": ("inspected_by",),
        "ImprintComponent": ("imprinted_by",),
        "JuvenileCareComponent": ("cared_by",),
        "WaterStudyComponent": ("studied_by",),
        "BroodingComponent": ("brooder_id",),
        "TrackComponent": ("room_id",),
        "TerritoryComponent": ("marked_by",),
        "NestComponent": ("prepared_by",),
        "BaitComponent": ("set_by_id",),
        "TamingComponent": ("tamer_id",),
        "CommandComponent": ("commanded_by_id", "target_id"),
        "MountComponent": ("rider_id",),
        "CompanionComponent": ("owner_id", "role"),
        "GuardBehaviorComponent": ("location_id",),
        "RecallComponent": ("home_room_id",),
        "EnclosureComponent": ("built_by_id",),
        "KaijuComponent": ("target_room_id",),
        "GrappleComponent": ("target_id",),
        "CreatureProductComponent": ("source_creature_id",),
        "RanchLaborComponent": ("target_id", "assigned_by_id"),
        "GuardAnimalComponent": ("location_id", "assigned_by_id"),
        "RecordedEvidenceComponent": ("subject_id", "device_id"),
        "OrbitComponent": ("body_id",),
        "NavigationRouteComponent": ("destination_id",),
    }
    for component, fields in legacy_fields.items():
        for owner_id, values in _records(components, component).items():
            if not isinstance(values, dict):
                raise WorldMigrationError(f"{component} fields for {owner_id!r} must be a mapping")
            present = next((field for field in fields if field in values), None)
            if present is not None:
                raise WorldMigrationError(
                    f"schema-v4 entity {owner_id!r} contains legacy {component}.{present}"
                )

    edge_names = (
        "SurveyedBy",
        "SampledFromFossil",
        "ClonedFromSample",
        "HatchedFromEgg",
        "InspectedBy",
        "ImprintedBy",
        "CaredForBy",
        "StudiedBy",
        "BroodedBy",
        "TrackedAt",
        "MarkedBy",
        "PreparedBy",
        "SetBy",
        "TamedBy",
        "CommandedBy",
        "CommandTarget",
        "MountedBy",
        "CompanionOf",
        "GuardsLocation",
        "RecallHome",
        "BuiltBy",
        "KaijuTargets",
        "Grappling",
        "ProductFromCreature",
        "AssignedBy",
        "RanchWorkTarget",
        "EvidenceSubject",
        "RecordedByDevice",
        "OrbitsBody",
        "NavigatesTo",
    )
    character_targets = {
        "SurveyedBy",
        "InspectedBy",
        "ImprintedBy",
        "CaredForBy",
        "StudiedBy",
        "BroodedBy",
        "MarkedBy",
        "PreparedBy",
        "SetBy",
        "TamedBy",
        "CommandedBy",
        "MountedBy",
        "CompanionOf",
        "BuiltBy",
        "AssignedBy",
        "EvidenceSubject",
        "Grappling",
    }
    room_targets = {"TrackedAt", "GuardsLocation", "RecallHome", "KaijuTargets"}
    characters = _records(components, "CharacterComponent")
    rooms = _records(components, "RoomComponent")
    fossils = _records(components, "FossilFragmentComponent")
    samples = _records(components, "AncientSampleComponent")
    devices = _records(components, "DeviceComponent")
    bodies = _records(components, "OrbitalBodyComponent")
    systems = _records(components, "StarSystemComponent")
    eggs = _records(components, "EggComponent")
    creatures = {
        *(_records(components, "DinosaurComponent")),
        *(_records(components, "SpeciesComponent")),
        *(_records(components, "ReptileProcreationComponent")),
        *(_records(components, "KaijuComponent")),
    }
    source_components = {
        "SurveyedBy": ("FossilSurveyComponent",),
        "SampledFromFossil": ("AncientSampleComponent",),
        "ClonedFromSample": ("CloneCandidateComponent",),
        "HatchedFromEgg": ("HatchlingComponent",),
        "InspectedBy": ("EggInspectionComponent",),
        "ImprintedBy": ("ImprintComponent",),
        "CaredForBy": ("JuvenileCareComponent",),
        "StudiedBy": (
            "WaterStudyComponent",
            "SampleComponent",
            "AlienArtifactComponent",
            "XenobiologySampleComponent",
            "VoiceInscriptionComponent",
        ),
        "BroodedBy": ("IncubationComponent", "BroodingComponent"),
        "TrackedAt": ("TrackComponent",),
        "MarkedBy": ("TerritoryComponent",),
        "PreparedBy": ("NestComponent",),
        "SetBy": ("BaitComponent",),
        "TamedBy": ("TamingComponent",),
        "CommandedBy": ("CommandComponent",),
        "CommandTarget": ("CommandComponent",),
        "MountedBy": ("MountComponent",),
        "CompanionOf": ("CompanionComponent",),
        "GuardsLocation": ("GuardBehaviorComponent", "GuardAnimalComponent"),
        "RecallHome": ("RecallComponent",),
        "BuiltBy": ("EnclosureComponent",),
        "KaijuTargets": ("KaijuComponent",),
        "Grappling": ("GrappleComponent",),
        "ProductFromCreature": ("CreatureProductComponent",),
        "AssignedBy": ("RanchLaborComponent", "GuardAnimalComponent"),
        "RanchWorkTarget": ("RanchLaborComponent",),
        "EvidenceSubject": ("RecordedEvidenceComponent",),
        "RecordedByDevice": ("RecordedEvidenceComponent",),
        "OrbitsBody": ("OrbitComponent",),
        "NavigatesTo": ("NavigationRouteComponent",),
    }
    component_owners = {
        name: set(_records(components, name))
        for names in source_components.values()
        for name in names
    }
    typed_targets = {
        "SampledFromFossil": fossils,
        "ClonedFromSample": samples,
        "HatchedFromEgg": eggs,
        "RecordedByDevice": devices,
        "OrbitsBody": bodies,
        "NavigatesTo": systems,
    }
    pairs_by_edge: dict[str, dict[str, list[str]]] = {}
    for edge_name in edge_names:
        pairs_by_edge[edge_name] = {}
        seen: set[tuple[str, str]] = set()
        for source_id, records in sorted(_records(relationships, edge_name).items()):
            if source_id not in entities:
                raise WorldMigrationError(
                    f"schema-v4 {edge_name} source {source_id!r} does not exist"
                )
            required = source_components[edge_name]
            if not any(source_id in component_owners[name] for name in required):
                expected = " or ".join(required)
                raise WorldMigrationError(
                    f"schema-v4 {edge_name} source {source_id!r} lacks {expected}"
                )
            if not isinstance(records, list):
                raise WorldMigrationError(f"{edge_name} edges for {source_id!r} must be a list")
            targets: list[str] = []
            for record in records:
                if not isinstance(record, dict) or not isinstance(record.get("edge", {}), dict):
                    raise WorldMigrationError(
                        f"schema-v4 {edge_name} edge for {source_id!r} must be a mapping"
                    )
                target_id = str(record.get("target") or "")
                if target_id not in entities:
                    raise WorldMigrationError(
                        f"schema-v4 {edge_name} edge owned by {source_id!r} "
                        f"refers to missing target {target_id!r}"
                    )
                pair = (source_id, target_id)
                if pair in seen:
                    raise WorldMigrationError(
                        f"schema-v4 contains duplicate {edge_name} edge "
                        f"{source_id!r} -> {target_id!r}"
                    )
                seen.add(pair)
                targets.append(target_id)
                if edge_name in character_targets and target_id not in characters:
                    raise WorldMigrationError(
                        f"schema-v4 {edge_name} target {target_id!r} is not a character"
                    )
                if edge_name in room_targets and target_id not in rooms:
                    raise WorldMigrationError(
                        f"schema-v4 {edge_name} target {target_id!r} is not a room"
                    )
                if edge_name in typed_targets and target_id not in typed_targets[edge_name]:
                    raise WorldMigrationError(
                        f"schema-v4 {edge_name} target {target_id!r} has the wrong type"
                    )
                if edge_name == "HatchedFromEgg":
                    egg_fields = eggs[target_id]
                    if not isinstance(egg_fields, dict) or not egg_fields.get("hatched"):
                        raise WorldMigrationError(
                            f"schema-v4 HatchedFromEgg target {target_id!r} is not hatched"
                        )
                if edge_name == "ProductFromCreature" and target_id not in creatures:
                    raise WorldMigrationError(
                        f"schema-v4 ProductFromCreature target {target_id!r} is not a creature"
                    )
                edge_fields = record.get("edge", {})
                if edge_name == "CompanionOf":
                    if set(edge_fields) != {"role"} or not isinstance(edge_fields.get("role"), str):
                        raise WorldMigrationError(
                            f"schema-v4 CompanionOf edge for {source_id!r} requires role"
                        )
                elif edge_fields:
                    raise WorldMigrationError(
                        f"schema-v4 {edge_name} edge for {source_id!r} must not contain properties"
                    )
            pairs_by_edge[edge_name][source_id] = targets

    repeatable = {"SurveyedBy", "StudiedBy"}
    for edge_name, sources in pairs_by_edge.items():
        if edge_name in repeatable:
            continue
        for source_id, targets in sources.items():
            if len(targets) > 1:
                raise WorldMigrationError(
                    f"schema-v4 entity {source_id!r} has multiple {edge_name} targets"
                )
    for evidence_id in _records(components, "RecordedEvidenceComponent"):
        if len(pairs_by_edge["EvidenceSubject"].get(evidence_id, [])) != 1:
            raise WorldMigrationError(
                f"schema-v4 recorded evidence {evidence_id!r} requires one EvidenceSubject"
            )
        if len(pairs_by_edge["RecordedByDevice"].get(evidence_id, [])) != 1:
            raise WorldMigrationError(
                f"schema-v4 recorded evidence {evidence_id!r} requires one RecordedByDevice"
            )
    for owner_id in _records(components, "OrbitComponent"):
        if len(pairs_by_edge["OrbitsBody"].get(owner_id, [])) != 1:
            raise WorldMigrationError(
                f"schema-v4 OrbitComponent owner {owner_id!r} requires one OrbitsBody edge"
            )
    for owner_id, fields in _records(components, "NavigationRouteComponent").items():
        destinations = pairs_by_edge["NavigatesTo"].get(owner_id, [])
        semantic = isinstance(fields, dict) and bool(fields.get("destination_key"))
        if len(destinations) != (0 if semantic else 1):
            raise WorldMigrationError(
                f"schema-v4 NavigationRouteComponent owner {owner_id!r} has invalid destination"
            )


def _migrate_v4(snapshot: dict[str, JsonValue]) -> dict[str, JsonValue]:
    _validate_v4(snapshot)
    entities = _table(snapshot, "entities")
    components = _table(snapshot, "components")
    relationships = _table(snapshot, "relationships")
    traveling = _records(components, "TravelingComponent")
    if traveling:
        raise WorldMigrationError("schema-v4 snapshot already contains TravelingComponent")

    travel_hubs = _records(components, "TravelHubComponent")
    for source_id, records in sorted(
        _records(relationships, "TravelingToDestination").items()
    ):
        if source_id not in entities:
            raise WorldMigrationError(
                f"schema-v4 TravelingToDestination source {source_id!r} does not exist"
            )
        if not isinstance(records, list) or len(records) != 1:
            raise WorldMigrationError(
                f"schema-v4 TravelingToDestination source {source_id!r} requires one destination"
            )
        record = records[0]
        if not isinstance(record, dict) or not isinstance(record.get("edge", {}), dict):
            raise WorldMigrationError(
                f"schema-v4 TravelingToDestination edge for {source_id!r} must be a mapping"
            )
        target_id = str(record.get("target") or "")
        if target_id not in entities:
            raise WorldMigrationError(
                f"schema-v4 TravelingToDestination edge owned by {source_id!r} "
                f"refers to missing target {target_id!r}"
            )
        if target_id not in travel_hubs:
            raise WorldMigrationError(
                f"schema-v4 TravelingToDestination target {target_id!r} is not a travel hub"
            )
        edge_fields = record.get("edge", {})
        started_at_epoch = edge_fields.get("started_at_epoch")
        arrive_at_epoch = edge_fields.get("arrive_at_epoch")
        for field_name, value in (
            ("started_at_epoch", started_at_epoch),
            ("arrive_at_epoch", arrive_at_epoch),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise WorldMigrationError(
                    f"schema-v4 TravelingToDestination.{field_name} for {source_id!r} "
                    "must be an integer"
                )
        mode = edge_fields.get("mode", "foot")
        route_label = edge_fields.get("route_label", "")
        if not isinstance(mode, str) or not isinstance(route_label, str):
            raise WorldMigrationError(
                f"schema-v4 TravelingToDestination text fields for {source_id!r} "
                "must be strings"
            )
        traveling[source_id] = {
            "started_at_epoch": started_at_epoch,
            "arrive_at_epoch": arrive_at_epoch,
            "mode": mode,
            "route_label": route_label,
        }
        record["edge"] = {}

    characters = _records(components, "CharacterComponent")
    rooms = _records(components, "RoomComponent")
    history_records = _records(components, "WorldHistoryRecordComponent")
    physical_marks = _records(components, "PhysicalMarkComponent")
    signatures = _records(components, "CreatorSignatureComponent")

    def live_typed_target(raw_target: JsonValue, typed: dict[str, JsonValue]) -> str | None:
        target_id = str(raw_target or "")
        return target_id if target_id in entities and target_id in typed else None

    def clear_edges(edge_name: str, source_id: str) -> None:
        _records(relationships, edge_name).pop(source_id, None)

    def provenance_fields(
        raw_fields: dict[str, JsonValue], *, owner_id: str, circumstance: str
    ) -> dict[str, JsonValue]:
        source_event_id = raw_fields.get("source_event_id", "")
        created_at_epoch = raw_fields.get("created_at_epoch", 0)
        if not isinstance(source_event_id, str):
            raise WorldMigrationError(
                f"schema-v4 creator provenance source_event_id for {owner_id!r} "
                "must be a string"
            )
        if not isinstance(created_at_epoch, int) or isinstance(created_at_epoch, bool):
            raise WorldMigrationError(
                f"schema-v4 creator provenance created_at_epoch for {owner_id!r} "
                "must be an integer"
            )
        return {
            "source_event_id": source_event_id,
            "created_at_epoch": created_at_epoch,
            "circumstance": circumstance,
        }

    for record_id, raw_fields in sorted(history_records.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"WorldHistoryRecordComponent fields for {record_id!r} must be a mapping"
            )
        location_id = live_typed_target(raw_fields.pop("location_id", ""), rooms)
        clear_edges("HistoryLocation", record_id)
        if location_id is not None:
            _add_edge(relationships, "HistoryLocation", record_id, location_id)

    for mark_id, raw_fields in sorted(physical_marks.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"PhysicalMarkComponent fields for {mark_id!r} must be a mapping"
            )
        author_id = live_typed_target(raw_fields.pop("author_id", ""), characters)
        signature_fields = signatures.pop(mark_id, None)
        circumstance = ""
        if signature_fields is not None:
            if not isinstance(signature_fields, dict):
                raise WorldMigrationError(
                    f"CreatorSignatureComponent fields for {mark_id!r} must be a mapping"
                )
            signature_creator = live_typed_target(
                signature_fields.pop("creator_id", ""), characters
            )
            author_id = author_id or signature_creator
            circumstance = str(signature_fields.get("circumstance") or "")
        clear_edges("CreatedBy", mark_id)
        if author_id is not None:
            _add_edge(
                relationships,
                "CreatedBy",
                mark_id,
                author_id,
                provenance_fields(
                    raw_fields,
                    owner_id=mark_id,
                    circumstance=circumstance,
                ),
            )

    for artifact_id, raw_fields in sorted(signatures.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"CreatorSignatureComponent fields for {artifact_id!r} must be a mapping"
            )
        creator_id = live_typed_target(raw_fields.pop("creator_id", ""), characters)
        clear_edges("CreatedBy", artifact_id)
        if creator_id is not None:
            _add_edge(
                relationships,
                "CreatedBy",
                artifact_id,
                creator_id,
                provenance_fields(
                    raw_fields,
                    owner_id=artifact_id,
                    circumstance=str(raw_fields.get("circumstance") or ""),
                ),
            )

    reputations = _records(components, "DeedReputationComponent")
    for character_id, raw_fields in sorted(reputations.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"DeedReputationComponent fields for {character_id!r} must be a mapping"
            )
        raw_deed_ids = raw_fields.pop("deed_ids", ()) or ()
        if not isinstance(raw_deed_ids, (list, tuple)):
            raise WorldMigrationError(
                f"schema-v4 entity {character_id!r} component "
                "DeedReputationComponent.deed_ids must be a sequence"
            )
        clear_edges("CreditedDeed", character_id)
        for raw_deed_id in dict.fromkeys(str(value) for value in raw_deed_ids):
            deed_id = live_typed_target(raw_deed_id, history_records)
            if deed_id is None:
                continue
            deed_fields = history_records[deed_id]
            score = (
                float(deed_fields.get("salience", 0.0))
                if isinstance(deed_fields, dict)
                else 0.0
            )
            _add_edge(
                relationships,
                "CreditedDeed",
                character_id,
                deed_id,
                {"score": score},
            )

    death_records = _records(components, "DeathConsequenceComponent")
    for death_id, raw_fields in sorted(death_records.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"DeathConsequenceComponent fields for {death_id!r} must be a mapping"
            )
        character_id = live_typed_target(raw_fields.pop("character_id", ""), characters)
        location_id = live_typed_target(raw_fields.pop("location_id", ""), rooms)
        clear_edges("DeathOf", death_id)
        clear_edges("DeathAt", death_id)
        if character_id is not None:
            _add_edge(relationships, "DeathOf", death_id, character_id)
        if location_id is not None:
            _add_edge(relationships, "DeathAt", death_id, location_id)

    study_components = (
        "SampleComponent",
        "AlienArtifactComponent",
        "XenobiologySampleComponent",
        "VoiceInscriptionComponent",
    )
    for component_name in study_components:
        for source_id, raw_fields in sorted(_records(components, component_name).items()):
            if not isinstance(raw_fields, dict):
                raise WorldMigrationError(
                    f"{component_name} fields for {source_id!r} must be a mapping"
                )
            raw_character_ids = raw_fields.pop("studied_by", ()) or ()
            if not isinstance(raw_character_ids, (list, tuple)):
                raise WorldMigrationError(
                    f"schema-v4 entity {source_id!r} component "
                    f"{component_name}.studied_by must be a sequence"
                )
            for raw_character_id in dict.fromkeys(str(value) for value in raw_character_ids):
                character_id = live_typed_target(raw_character_id, characters)
                if character_id is not None:
                    _add_edge(relationships, "StudiedBy", source_id, character_id)

    decoration_sources = _records(components, "DecorationSource3DComponent")
    decoration_edges = _records(relationships, "HasDecoration3D")
    for decoration_id, raw_fields in sorted(decoration_sources.items()):
        if not isinstance(raw_fields, dict):
            raise WorldMigrationError(
                f"DecorationSource3DComponent fields for {decoration_id!r} must be a mapping"
            )
        raw_room_id = raw_fields.pop("room_id", "")
        room_id = live_typed_target(raw_room_id, rooms)
        owners: list[str] = []
        for candidate_id, records in decoration_edges.items():
            if not isinstance(records, list):
                raise WorldMigrationError(
                    f"HasDecoration3D edges for {candidate_id!r} must be a list"
                )
            if any(
                isinstance(record, dict) and record.get("target") == decoration_id
                for record in records
            ):
                owners.append(candidate_id)
        if len(owners) > 1 or (owners and room_id is not None and owners[0] != room_id):
            raise WorldMigrationError(
                f"schema-v4 DecorationSource3DComponent owner {decoration_id!r} "
                "conflicts with HasDecoration3D"
            )
        if not owners and room_id is not None:
            _add_edge(
                relationships,
                "HasDecoration3D",
                room_id,
                decoration_id,
                {"role": str(raw_fields.get("role") or "")},
            )

    _table(snapshot, "bunnyland")["schema_version"] = 5
    _validate_v5(snapshot)
    return snapshot


def _validate_v5(snapshot: dict[str, JsonValue]) -> None:
    _validate_v4(snapshot)
    entities = _table(snapshot, "entities")
    components = _table(snapshot, "components")
    relationships = _table(snapshot, "relationships")
    travel_hubs = _records(components, "TravelHubComponent")
    traveling = _records(components, "TravelingComponent")
    travel_edges = _records(relationships, "TravelingToDestination")

    for source_id, fields in traveling.items():
        if source_id not in entities:
            raise WorldMigrationError(
                f"schema-v5 TravelingComponent owner {source_id!r} does not exist"
            )
        if not isinstance(fields, dict):
            raise WorldMigrationError(
                f"TravelingComponent fields for {source_id!r} must be a mapping"
            )
        if set(fields) != {"started_at_epoch", "arrive_at_epoch", "mode", "route_label"}:
            raise WorldMigrationError(
                f"schema-v5 TravelingComponent fields for {source_id!r} are invalid"
            )
        for field_name in ("started_at_epoch", "arrive_at_epoch"):
            value = fields[field_name]
            if not isinstance(value, int) or isinstance(value, bool):
                raise WorldMigrationError(
                    f"schema-v5 TravelingComponent.{field_name} for {source_id!r} "
                    "must be an integer"
                )
        if not isinstance(fields["mode"], str) or not isinstance(fields["route_label"], str):
            raise WorldMigrationError(
                f"schema-v5 TravelingComponent text fields for {source_id!r} must be strings"
            )

    for source_id, records in travel_edges.items():
        if source_id not in traveling:
            raise WorldMigrationError(
                f"schema-v5 TravelingToDestination source {source_id!r} lacks "
                "TravelingComponent"
            )
        if not isinstance(records, list) or len(records) != 1:
            raise WorldMigrationError(
                f"schema-v5 TravelingToDestination source {source_id!r} requires one destination"
            )
        record = records[0]
        if not isinstance(record, dict) or not isinstance(record.get("edge", {}), dict):
            raise WorldMigrationError(
                f"schema-v5 TravelingToDestination edge for {source_id!r} must be a mapping"
            )
        if record.get("edge", {}):
            raise WorldMigrationError(
                f"schema-v5 TravelingToDestination edge for {source_id!r} "
                "must not contain properties"
            )
        target_id = str(record.get("target") or "")
        if target_id not in entities:
            raise WorldMigrationError(
                f"schema-v5 TravelingToDestination edge owned by {source_id!r} "
                f"refers to missing target {target_id!r}"
            )
        if target_id not in travel_hubs:
            raise WorldMigrationError(
                f"schema-v5 TravelingToDestination target {target_id!r} is not a travel hub"
            )

    for source_id in traveling:
        if source_id not in travel_edges:
            raise WorldMigrationError(
                f"schema-v5 TravelingComponent owner {source_id!r} requires one "
                "TravelingToDestination edge"
            )

    legacy_fields = {
        "WorldHistoryRecordComponent": ("location_id",),
        "PhysicalMarkComponent": ("author_id",),
        "CreatorSignatureComponent": ("creator_id",),
        "DeedReputationComponent": ("deed_ids",),
        "DeathConsequenceComponent": ("character_id", "location_id"),
        "SampleComponent": ("studied_by",),
        "AlienArtifactComponent": ("studied_by",),
        "XenobiologySampleComponent": ("studied_by",),
        "VoiceInscriptionComponent": ("studied_by",),
        "DecorationSource3DComponent": ("room_id",),
    }
    for component_name, field_names in legacy_fields.items():
        for owner_id, fields in _records(components, component_name).items():
            if not isinstance(fields, dict):
                raise WorldMigrationError(
                    f"{component_name} fields for {owner_id!r} must be a mapping"
                )
            field_name = next((name for name in field_names if name in fields), None)
            if field_name is not None:
                raise WorldMigrationError(
                    f"schema-v5 entity {owner_id!r} contains legacy "
                    f"{component_name}.{field_name}"
                )

    physical_marks = _records(components, "PhysicalMarkComponent")
    signatures = _records(components, "CreatorSignatureComponent")
    duplicate_signature = next(
        (owner_id for owner_id in physical_marks if owner_id in signatures), None
    )
    if duplicate_signature is not None:
        raise WorldMigrationError(
            f"schema-v5 physical mark {duplicate_signature!r} must not contain "
            "CreatorSignatureComponent"
        )

    characters = _records(components, "CharacterComponent")
    rooms = _records(components, "RoomComponent")
    history_records = _records(components, "WorldHistoryRecordComponent")
    reputations = _records(components, "DeedReputationComponent")
    death_records = _records(components, "DeathConsequenceComponent")

    def relationship_records(edge_name: str) -> dict[str, list[tuple[str, dict[str, JsonValue]]]]:
        parsed: dict[str, list[tuple[str, dict[str, JsonValue]]]] = {}
        seen: set[tuple[str, str]] = set()
        for source_id, records in sorted(_records(relationships, edge_name).items()):
            if source_id not in entities:
                raise WorldMigrationError(
                    f"schema-v5 {edge_name} source {source_id!r} does not exist"
                )
            if not isinstance(records, list):
                raise WorldMigrationError(f"{edge_name} edges for {source_id!r} must be a list")
            parsed[source_id] = []
            for record in records:
                if not isinstance(record, dict) or not isinstance(record.get("edge", {}), dict):
                    raise WorldMigrationError(
                        f"schema-v5 {edge_name} edge for {source_id!r} must be a mapping"
                    )
                target_id = str(record.get("target") or "")
                if target_id not in entities:
                    raise WorldMigrationError(
                        f"schema-v5 {edge_name} edge owned by {source_id!r} "
                        f"refers to missing target {target_id!r}"
                    )
                pair = (source_id, target_id)
                if pair in seen:
                    raise WorldMigrationError(
                        f"schema-v5 contains duplicate {edge_name} edge "
                        f"{source_id!r} -> {target_id!r}"
                    )
                seen.add(pair)
                parsed[source_id].append((target_id, record.get("edge", {})))
        return parsed

    created_by = relationship_records("CreatedBy")
    for source_id, records in created_by.items():
        if source_id not in signatures and source_id not in physical_marks:
            raise WorldMigrationError(
                f"schema-v5 CreatedBy source {source_id!r} lacks creator provenance"
            )
        if len(records) > 1:
            raise WorldMigrationError(
                f"schema-v5 entity {source_id!r} has multiple CreatedBy targets"
            )
        for target_id, fields in records:
            if target_id not in characters:
                raise WorldMigrationError(
                    f"schema-v5 CreatedBy target {target_id!r} is not a character"
                )
            if set(fields) != {"source_event_id", "created_at_epoch", "circumstance"}:
                raise WorldMigrationError(
                    f"schema-v5 CreatedBy fields for {source_id!r} are invalid"
                )
            if (
                not isinstance(fields["source_event_id"], str)
                or not isinstance(fields["created_at_epoch"], int)
                or isinstance(fields["created_at_epoch"], bool)
                or not isinstance(fields["circumstance"], str)
            ):
                raise WorldMigrationError(
                    f"schema-v5 CreatedBy fields for {source_id!r} have invalid types"
                )

    history_locations = relationship_records("HistoryLocation")
    for source_id, records in history_locations.items():
        if source_id not in history_records:
            raise WorldMigrationError(
                f"schema-v5 HistoryLocation source {source_id!r} lacks "
                "WorldHistoryRecordComponent"
            )
        if len(records) > 1:
            raise WorldMigrationError(
                f"schema-v5 entity {source_id!r} has multiple HistoryLocation targets"
            )
        for target_id, fields in records:
            if target_id not in rooms:
                raise WorldMigrationError(
                    f"schema-v5 HistoryLocation target {target_id!r} is not a room"
                )
            if fields:
                raise WorldMigrationError(
                    f"schema-v5 HistoryLocation edge for {source_id!r} "
                    "must not contain properties"
                )

    credited_deeds = relationship_records("CreditedDeed")
    for source_id, records in credited_deeds.items():
        if source_id not in reputations or source_id not in characters:
            raise WorldMigrationError(
                f"schema-v5 CreditedDeed source {source_id!r} lacks character reputation"
            )
        for target_id, fields in records:
            if target_id not in history_records:
                raise WorldMigrationError(
                    f"schema-v5 CreditedDeed target {target_id!r} is not a history record"
                )
            score = fields.get("score")
            if set(fields) != {"score"} or not isinstance(score, (int, float)) or isinstance(
                score, bool
            ):
                raise WorldMigrationError(
                    f"schema-v5 CreditedDeed score for {source_id!r} must be numeric"
                )

    for edge_name, source_components, target_components in (
        ("DeathOf", death_records, characters),
        ("DeathAt", death_records, rooms),
    ):
        parsed = relationship_records(edge_name)
        for source_id, records in parsed.items():
            if source_id not in source_components:
                raise WorldMigrationError(
                    f"schema-v5 {edge_name} source {source_id!r} lacks "
                    "DeathConsequenceComponent"
                )
            if len(records) > 1:
                raise WorldMigrationError(
                    f"schema-v5 entity {source_id!r} has multiple {edge_name} targets"
                )
            for target_id, fields in records:
                if target_id not in target_components:
                    expected = "character" if edge_name == "DeathOf" else "room"
                    raise WorldMigrationError(
                        f"schema-v5 {edge_name} target {target_id!r} is not a {expected}"
                    )
                if fields:
                    raise WorldMigrationError(
                        f"schema-v5 {edge_name} edge for {source_id!r} "
                        "must not contain properties"
                    )


def migrate_snapshot(snapshot: object) -> dict[str, JsonValue]:
    """Return a validated schema-v5 copy of a raw JSON/YAML snapshot."""

    if not isinstance(snapshot, dict):
        raise WorldMigrationError("world snapshot must be a mapping")
    migrated: dict[str, JsonValue] = deepcopy(snapshot)
    bunnyland = _table(migrated, "bunnyland")
    _drop_empty_relationship_buckets(migrated.get("relationships"))
    version = bunnyland.get("schema_version", 1)
    if not isinstance(version, int):
        raise WorldMigrationError("bunnyland.schema_version must be an integer")
    if version > CURRENT_SCHEMA_VERSION:
        raise WorldMigrationError(
            f"world schema {version} is newer than supported schema {CURRENT_SCHEMA_VERSION}"
        )
    if version < 1:
        raise WorldMigrationError(f"unsupported world schema {version}")
    if version == 1:
        migrated = _migrate_v1(migrated)
        version = 2
    if version == 2:
        migrated = _migrate_v2(migrated)
        version = 3
    if version == 3:
        migrated = _migrate_v3(migrated)
        version = 4
    if version == 4:
        return _migrate_v4(migrated)
    for section in ("entities", "components", "relationships"):
        _table(migrated, section)
    _validate_v5(migrated)
    return migrated


__all__ = ["CURRENT_SCHEMA_VERSION", "WorldMigrationError", "migrate_snapshot"]
