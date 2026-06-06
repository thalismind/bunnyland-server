"""Compact YAML persistence driver for Relics worlds.

The document is intentionally shaped like a dump:

```
__metadata__: {"version": "1.0", "epoch": 0}
__prefabs__: {"entity": {"components": {}}}
entity_1:
  IdentityComponent: {"name": "Hazel", "kind": "character"}
  Contains -> entity_2: {"mode": "inventory"}
```

Top-level entity records are loaded in two phases: entities and components first, then
edges after every target ID exists.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel
from relics.persistence.base import PersistenceDriver, RelicInfo
from relics.persistence.serialization import _component_to_dict, _dict_to_component
from relics.prefab import prefab_to_dict
from relics.shared import is_temporary
from relics.types import Component, Edge, EntityId

if TYPE_CHECKING:
    from relics.world import World

_RESERVED_KEYS = frozenset({"__metadata__", "__prefabs__", "__bunnyland__"})
_PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def _yaml_module():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised only without optional extra
        raise RuntimeError(
            "YAML persistence requires PyYAML; install the yaml extra to use it"
        ) from exc
    return yaml


def _plain(value: Any) -> Any:
    """Convert component fields to plain YAML/JSON-safe values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return {k: _plain(v) for k, v in value.model_dump().items()}
    if is_dataclass(value) and not isinstance(value, type):
        fields = getattr(value, "__pydantic_fields__", None) or getattr(
            value, "__dataclass_fields__", {}
        )
        return {
            name: _plain(getattr(value, name))
            for name in fields
            if not name.startswith("_")
        }
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _json_hash(value: Any) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, default=str)


def _record_key(value: str) -> str:
    if _PLAIN_KEY.match(value):
        return value
    return json.dumps(value, ensure_ascii=False)


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a YAML mapping")
    return {str(key): item for key, item in value.items()}


def _snapshot_from_world(world: World, relic_name: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "version": "1.0",
        "epoch": world.epoch,
        "created_at": datetime.now(UTC).isoformat(),
        "world_id": world.id,
    }
    if relic_name is not None:
        metadata["relic_name"] = relic_name

    prefabs: dict[str, dict[str, Any]] = {}
    for prefab_name, components in world._prefabs.items():
        prefabs[prefab_name] = _plain(prefab_to_dict(prefab_name, components))

    entities: dict[str, dict[str, Any]] = {}
    for entity_id in world._entities:
        entities[str(entity_id)] = {"prefab": entity_id.prefab, "created_epoch": 0}

    components_data: dict[str, dict[str, dict[str, Any]]] = {}
    for entity_id, components in world._entities.items():
        for component_type, component in components.items():
            if is_temporary(component_type):
                continue
            components_data.setdefault(component_type.__name__, {})[str(entity_id)] = (
                _plain(_component_to_dict(component))
            )

    relationships: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for source_id, edge_types in world._relationships.items():
        for edge_type, edges in edge_types.items():
            source_edges = relationships.setdefault(edge_type.__name__, {}).setdefault(
                str(source_id), []
            )
            for target_id, edge in edges.items():
                source_edges.append(
                    {"target": str(target_id), "edge": _plain(_component_to_dict(edge))}
                )

    return {
        "metadata": metadata,
        "prefabs": prefabs,
        "entities": entities,
        "components": components_data,
        "relationships": relationships,
        "relics": [],
    }


class YAMLPersistenceDriver(PersistenceDriver):
    """Relics persistence driver using Bunnyland's compact YAML dump dialect."""

    def save(
        self,
        world: World,
        path: str | Path,
        relic_name: str | None = None,
    ) -> None:
        self.save_snapshot(_snapshot_from_world(world, relic_name), path)

    def load(
        self,
        world: World,
        path: str | Path,
        component_registry: dict[str, type[Component]] | None = None,
        edge_registry: dict[str, type[Edge]] | None = None,
    ) -> None:
        self.load_snapshot(world, self.read_snapshot(path), component_registry, edge_registry)

    def save_relic(
        self,
        world: World,
        name: str,
        relics_dir: str | Path,
        overwrite: bool = False,
    ) -> None:
        relics_dir = Path(relics_dir)
        relics_dir.mkdir(parents=True, exist_ok=True)

        relic_path = relics_dir / f"{name}.yaml"
        if relic_path.exists() and not overwrite:
            raise FileExistsError(f"Relic '{name}' already exists")
        self.save(world, relic_path, relic_name=name)

    def load_relic(
        self,
        world: World,
        name: str,
        relics_dir: str | Path,
        component_registry: dict[str, type[Component]] | None = None,
        edge_registry: dict[str, type[Edge]] | None = None,
    ) -> None:
        relic_path = Path(relics_dir) / f"{name}.yaml"
        if not relic_path.exists():
            relic_path = Path(relics_dir) / f"{name}.yml"
        if not relic_path.exists():
            raise FileNotFoundError(f"Relic '{name}' not found")
        self.load(world, relic_path, component_registry, edge_registry)

    def list_relics(self, relics_dir: str | Path) -> list[RelicInfo]:
        relics_dir = Path(relics_dir)
        if not relics_dir.exists():
            return []

        relics: list[RelicInfo] = []
        for relic_file in (*relics_dir.glob("*.yaml"), *relics_dir.glob("*.yml")):
            if relic_file.name.startswith("_"):
                continue
            try:
                metadata = self.read_snapshot(relic_file).get("metadata", {})
            except (OSError, ValueError):
                continue
            relics.append(
                RelicInfo(
                    name=str(metadata.get("relic_name", relic_file.stem)),
                    epoch=int(metadata.get("epoch", 0)),
                    created_at=str(metadata.get("created_at", "")),
                )
            )

        relics.sort(key=lambda r: r.created_at, reverse=True)
        return relics

    def save_snapshot(self, snapshot: Mapping[str, Any], path: str | Path) -> None:
        """Write a Relics-style snapshot using the compact YAML dump dialect."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.dumps_snapshot(snapshot))

    def read_snapshot(self, path: str | Path) -> dict[str, Any]:
        """Read either compact YAML or a regular Relics YAML mapping into a snapshot."""
        path = Path(path)
        yaml = _yaml_module()
        document = yaml.safe_load(path.read_text()) or {}
        return self.snapshot_from_document(document)

    def dumps_snapshot(self, snapshot: Mapping[str, Any]) -> str:
        lines: list[str] = []
        metadata = _mapping(snapshot.get("metadata", {}), label="metadata")
        prefabs = _mapping(snapshot.get("prefabs", {}), label="prefabs")
        bunnyland = snapshot.get("bunnyland")

        lines.append(f"__metadata__: {_json_hash(metadata)}")
        if bunnyland is not None:
            lines.append(f"__bunnyland__: {_json_hash(bunnyland)}")
        lines.append(f"__prefabs__: {_json_hash(prefabs)}")

        entities = _mapping(snapshot.get("entities", {}), label="entities")
        components = _mapping(snapshot.get("components", {}), label="components")
        relationships = _mapping(snapshot.get("relationships", {}), label="relationships")

        for entity_id in entities:
            lines.append(f"{_record_key(entity_id)}:")
            wrote_subrecord = False

            for component_name, component_table in components.items():
                fields = _mapping(component_table, label=f"{component_name} components").get(
                    entity_id
                )
                if fields is None:
                    continue
                lines.append(f"  {_record_key(component_name)}: {_json_hash(fields)}")
                wrote_subrecord = True

            for edge_name, edge_table in relationships.items():
                edge_records = _mapping(edge_table, label=f"{edge_name} edges").get(
                    entity_id, []
                )
                if not isinstance(edge_records, list):
                    raise ValueError(f"{edge_name} edges for {entity_id} must be a list")
                for edge_record in edge_records:
                    edge = _mapping(edge_record, label=f"{edge_name} edge")
                    target = str(edge["target"])
                    fields = edge.get("edge", {})
                    lines.append(
                        f"  {_record_key(f'{edge_name} -> {target}')}: {_json_hash(fields)}"
                    )
                    wrote_subrecord = True

            if not wrote_subrecord:
                lines[-1] = f"{_record_key(entity_id)}: {{}}"

        return "\n".join(lines) + "\n"

    def snapshot_from_document(self, document: Any) -> dict[str, Any]:
        data = _mapping(document, label="YAML document")
        if {"metadata", "entities"} <= set(data):
            return dict(data)

        entities: dict[str, dict[str, Any]] = {}
        components: dict[str, dict[str, Any]] = {}
        relationships: dict[str, dict[str, list[dict[str, Any]]]] = {}

        for entity_id, subrecords in data.items():
            if entity_id in _RESERVED_KEYS:
                continue
            EntityId.parse(entity_id)
            entities[entity_id] = {
                "prefab": EntityId.parse(entity_id).prefab,
                "created_epoch": 0,
            }

            for type_key, fields in _mapping(
                subrecords, label=f"{entity_id} record"
            ).items():
                fields = _mapping(fields, label=f"{entity_id}.{type_key}")
                if " -> " not in type_key:
                    components.setdefault(type_key, {})[entity_id] = fields
                    continue

                edge_name, target_id = type_key.split(" -> ", 1)
                EntityId.parse(target_id)
                relationships.setdefault(edge_name, {}).setdefault(entity_id, []).append(
                    {"target": target_id, "edge": fields}
                )

        return {
            "metadata": _mapping(data.get("__metadata__", {}), label="__metadata__"),
            "bunnyland": _mapping(data.get("__bunnyland__", {}), label="__bunnyland__"),
            "prefabs": _mapping(data.get("__prefabs__", {}), label="__prefabs__"),
            "entities": entities,
            "components": components,
            "relationships": relationships,
            "relics": [],
        }

    def load_snapshot(
        self,
        world: World,
        snapshot: Mapping[str, Any],
        component_registry: dict[str, type[Component]] | None = None,
        edge_registry: dict[str, type[Edge]] | None = None,
    ) -> None:
        if component_registry is None:
            component_registry = world._component_types
        if edge_registry is None:
            edge_registry = world._edge_types

        world._entities.clear()
        world._prefab_index.clear()
        world._relationships.clear()
        world._incoming_relationships.clear()
        world._component_index.clear()

        metadata = _mapping(snapshot.get("metadata", {}), label="metadata")
        world._epoch = int(metadata.get("epoch", 0))

        for prefab_name, prefab_info in _mapping(
            snapshot.get("prefabs", {}), label="prefabs"
        ).items():
            components_info = _mapping(prefab_info, label=f"prefab {prefab_name}").get(
                "components", {}
            )
            components: dict[type[Component], Component] = {}
            for component_name, component_fields in _mapping(
                components_info, label=f"prefab {prefab_name} components"
            ).items():
                component_type = component_registry.get(component_name)
                if component_type is None:
                    continue
                components[component_type] = cast(
                    Component,
                    _dict_to_component(
                        component_type,
                        _mapping(
                            component_fields,
                            label=f"prefab {prefab_name}.{component_name}",
                        ),
                    ),
                )
            world._prefabs[prefab_name] = components

        for entity_id_str, entity_info in _mapping(
            snapshot.get("entities", {}), label="entities"
        ).items():
            entity_id = EntityId.parse(entity_id_str)
            prefab = str(
                _mapping(entity_info, label=f"entity {entity_id_str}").get(
                    "prefab", entity_id.prefab
                )
            )
            world._entities[entity_id] = {}
            world._prefab_index.setdefault(prefab, set()).add(entity_id)

        for component_name, entity_components in _mapping(
            snapshot.get("components", {}), label="components"
        ).items():
            component_type = component_registry.get(component_name)
            if component_type is None:
                continue
            for entity_id_str, component_fields in _mapping(
                entity_components, label=f"{component_name} components"
            ).items():
                entity_id = EntityId.parse(entity_id_str)
                if entity_id not in world._entities:
                    continue
                component = cast(
                    Component,
                    _dict_to_component(
                        component_type,
                        _mapping(
                            component_fields,
                            label=f"{entity_id_str}.{component_name}",
                        ),
                    ),
                )
                world._entities[entity_id][component_type] = component
                world._component_index.setdefault(component_type, set()).add(entity_id)

        for edge_name, source_edges in _mapping(
            snapshot.get("relationships", {}), label="relationships"
        ).items():
            edge_type = edge_registry.get(edge_name)
            if edge_type is None:
                continue
            for source_id_str, edges in _mapping(
                source_edges, label=f"{edge_name} sources"
            ).items():
                source_id = EntityId.parse(source_id_str)
                if source_id not in world._entities:
                    continue
                if not isinstance(edges, list):
                    raise ValueError(f"{edge_name} edges for {source_id_str} must be a list")
                for edge_record in edges:
                    edge_info = _mapping(edge_record, label=f"{source_id_str}.{edge_name}")
                    target_id = EntityId.parse(str(edge_info["target"]))
                    if target_id not in world._entities:
                        continue
                    edge = cast(
                        Edge,
                        _dict_to_component(
                            edge_type,
                            _mapping(edge_info.get("edge", {}), label=edge_name),
                        ),
                    )
                    world._relationships.setdefault(source_id, {}).setdefault(
                        edge_type, {}
                    )[target_id] = edge
                    world._incoming_relationships.setdefault(target_id, {}).setdefault(
                        edge_type, {}
                    )[source_id] = edge


__all__ = ["YAMLPersistenceDriver"]
