"""Saving and reloading worlds (spec 26).

A save is a single file containing the Relics ECS snapshot *and* the bunnyland metadata
that produced it (seed, prompt, generator). JSON saves use the layout Relics' own loader
understands, so reloading is just ``relics.load``. YAML saves use Bunnyland's optional
compact Relics persistence driver, where each entity is a record and edges are written as
``EdgeType -> target_entity`` subrecords.

Relics' serializer only walks top-level component fields, so bunnyland's nested value
objects (``Meter``, ``AffectVector``) are flattened to plain dicts on save with
``_jsonable``; on load, pydantic coerces those dicts back into the value objects. The
volatile command queues are intentionally *not* persisted (spec 26): a reloaded world
resumes with empty queues.
"""

from __future__ import annotations

import importlib
import inspect
import json
from collections.abc import Sequence
from dataclasses import is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import relics
from pydantic import BaseModel
from relics import Component, Edge

from . import telemetry
from .core.world_actor import WorldActor
from .persistence_yaml import YAMLPersistenceDriver
from .plugins import PluginError, apply_plugins
from .plugins.contributions import collect_ecs_types

if TYPE_CHECKING:
    from .plugins.model import Plugin

SCHEMA_VERSION = 1
PersistenceFormat = Literal["json", "yaml"]

# Modules scanned for the component/edge types a saved world may contain. Plugin-provided
# types are added from each plugin's EcsContribution at save/load time.
_TYPE_MODULES = (
    "bunnyland.core.components",
    "bunnyland.core.edges",
    "bunnyland.core.controllers",
    "bunnyland.mechanics.needs",
    "bunnyland.mechanics.consumables",
    "bunnyland.mechanics.affect",
    "bunnyland.mechanics.environment",
    "bunnyland.mechanics.history",
    "bunnyland.mechanics.social",
    "bunnyland.mechanics.policy",
    "bunnyland.mechanics.persona",
    "bunnyland.mechanics.lifesim",
    "bunnyland.mechanics.storyteller",
    "bunnyland.mechanics.colonysim",
    "bunnyland.mechanics.barbariansim",
    "bunnyland.mechanics.gardensim",
    "bunnyland.mechanics.dinosim",
    "bunnyland.mechanics.dragonsim",
)


class WorldMeta(BaseModel):
    """The provenance of a world, saved beside the ECS data."""

    schema_version: int = SCHEMA_VERSION
    seed: str = ""
    prompt: str = ""  # the literal DM system prompt used to build the world ("" for stub)
    generator: str = ""  # which world generator produced it
    plugins: tuple[str, ...] = ()  # plugin ids loaded for this world, e.g. module_foo.bar
    saved_at_epoch: int = 0  # bunnyland game epoch at save time
    saved_at: datetime | None = None  # wall-clock save time


def _jsonable(value: Any) -> Any:
    """Recursively convert a value to JSON-native form (dataclasses -> dicts, enums -> values)."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return {k: _jsonable(v) for k, v in value.model_dump().items()}
    if is_dataclass(value) and not isinstance(value, type):
        fields = getattr(value, "__pydantic_fields__", None) or getattr(
            value, "__dataclass_fields__", {}
        )
        return {
            name: _jsonable(getattr(value, name))
            for name in fields
            if not name.startswith("_")
        }
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def type_registries(
    plugins: Sequence[Plugin] | None = None,
) -> tuple[dict[str, type], dict[str, type]]:
    """Build ``(component_registry, edge_registry)`` keyed by class name for ``relics.load``."""
    components: dict[str, type] = {}
    edges: dict[str, type] = {}
    for module_name in _TYPE_MODULES:
        module = importlib.import_module(module_name)
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Edge) and obj is not Edge:
                edges[obj.__name__] = obj
            elif issubclass(obj, Component) and obj is not Component:
                components[obj.__name__] = obj
    plugin_components, plugin_edges = collect_ecs_types(plugins or ())
    for component in plugin_components:
        components[component.__name__] = component
    for edge in plugin_edges:
        edges[edge.__name__] = edge
    return components, edges


def _snapshot(actor: WorldActor, meta: WorldMeta) -> dict[str, Any]:
    world = actor.world
    entities: dict[str, Any] = {}
    components: dict[str, dict[str, Any]] = {}
    relationships: dict[str, dict[str, list]] = {}

    for entity in world.query().execute_entities():
        eid = str(entity.id)
        export = world.export_entity(entity.id)
        entities[eid] = {"prefab": entity.id.prefab, "created_epoch": 0}
        for type_name, fields in export.get("components", {}).items():
            components.setdefault(type_name, {})[eid] = _jsonable(fields)
        for edge_name, edges in export.get("relationships", {}).items():
            bucket = relationships.setdefault(edge_name, {}).setdefault(eid, [])
            for edge in edges:
                bucket.append({"target": edge["target"], "edge": _jsonable(edge["edge"])})

    return {
        "metadata": {"version": "1.0", "epoch": world.epoch},
        "bunnyland": _jsonable(meta),
        "prefabs": {"entity": {"components": {}}},
        "entities": entities,
        "components": components,
        "relationships": relationships,
        "relics": [],
    }


def _format_for_path(path: Path, format: PersistenceFormat | None) -> PersistenceFormat:
    if format is not None:
        if format not in ("json", "yaml"):
            raise ValueError(f"unknown persistence format: {format}")
        return format
    if path.suffix.lower() in {".yaml", ".yml"}:
        return "yaml"
    return "json"


def save_world(
    actor: WorldActor,
    path: str | Path,
    *,
    meta: WorldMeta,
    format: PersistenceFormat | None = None,
) -> WorldMeta:
    """Write the world (ECS + provenance) to ``path``. Returns the stamped meta."""
    path = Path(path)
    resolved_format = _format_for_path(path, format)
    attrs = {"operation": "save", "format": resolved_format}
    with telemetry.record_duration(
        telemetry.record_persist, attrs
    ), telemetry.span("world.save", {**attrs, "path": str(path)}) as save_span:
        stamped = meta.model_copy(
            update={"saved_at_epoch": actor.epoch, "saved_at": datetime.now(UTC)}
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = _snapshot(actor, stamped)
        if resolved_format == "yaml":
            YAMLPersistenceDriver().save_snapshot(snapshot, path)
        else:
            path.write_text(json.dumps(snapshot, indent=2, default=str))
        if telemetry.enabled():
            save_span.set_attribute(
                "entity.count", len(list(actor.world.query().execute_entities()))
            )
        return stamped


def load_world(
    path: str | Path,
    *,
    plugins: Sequence[Plugin] | None = None,
    format: PersistenceFormat | None = None,
) -> tuple[WorldActor, WorldMeta]:
    """Reload a world from ``path``. Applies ``plugins`` (handlers/systems) before loading."""
    path = Path(path)
    selected_format = _format_for_path(path, format)
    attrs = {"operation": "load", "format": selected_format}
    with telemetry.record_duration(
        telemetry.record_persist, attrs
    ), telemetry.span("world.load", {**attrs, "path": str(path)}) as load_span:
        yaml_driver = YAMLPersistenceDriver() if selected_format == "yaml" else None
        data = (
            yaml_driver.read_snapshot(path)
            if yaml_driver is not None
            else json.loads(path.read_text())
        )
        meta = WorldMeta.model_validate(data.get("bunnyland", {}))

        actor = WorldActor()
        if plugins is not None:
            available = {plugin.id for plugin in plugins}
            missing = tuple(plugin_id for plugin_id in meta.plugins if plugin_id not in available)
            if missing:
                names = ", ".join(repr(plugin_id) for plugin_id in missing)
                raise PluginError(f"saved world depends on missing plugin(s): {names}")
            apply_plugins(plugins, actor)

        component_registry, edge_registry = type_registries(plugins)
        if yaml_driver is not None:
            yaml_driver.load_snapshot(actor.world, data, component_registry, edge_registry)
        else:
            relics.load(
                actor.world,
                path,
                component_registry=component_registry,
                edge_registry=edge_registry,
            )
        actor.bind_clock()  # the __init__ clock was cleared by load; rebind to the saved one
        if telemetry.enabled():
            load_span.set_attribute(
                "entity.count", len(list(actor.world.query().execute_entities()))
            )
        return actor, meta


__all__ = [
    "SCHEMA_VERSION",
    "PersistenceFormat",
    "WorldMeta",
    "YAMLPersistenceDriver",
    "load_world",
    "save_world",
    "type_registries",
]
