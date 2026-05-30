"""Saving and reloading worlds (spec 26).

A save is a single JSON file containing the Relics ECS snapshot *and* the bunnyland
metadata that produced it (seed, prompt, generator). It is written in the layout Relics'
own loader understands, so reloading is just ``relics.load`` — which preserves entity ids
(so edges survive) and restores the clock.

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
from typing import TYPE_CHECKING, Any

import relics
from pydantic import BaseModel
from relics import Component, Edge

from .core.world_actor import WorldActor
from .plugins import apply_plugins

if TYPE_CHECKING:
    from .plugins.model import Plugin

SCHEMA_VERSION = 1

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
    "bunnyland.mechanics.social",
    "bunnyland.mechanics.policy",
    "bunnyland.mechanics.persona",
    "bunnyland.mechanics.lifesim",
    "bunnyland.mechanics.colonysim",
    "bunnyland.mechanics.barbariansim",
    "bunnyland.mechanics.gardensim",
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
    for plugin in plugins or ():
        for component in plugin.ecs.components:
            components[component.__name__] = component
        for edge in plugin.ecs.edges:
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


def save_world(actor: WorldActor, path: str | Path, *, meta: WorldMeta) -> WorldMeta:
    """Write the world (ECS + provenance) to ``path`` as JSON. Returns the stamped meta."""
    stamped = meta.model_copy(
        update={"saved_at_epoch": actor.epoch, "saved_at": datetime.now(UTC)}
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_snapshot(actor, stamped), indent=2, default=str))
    return stamped


def load_world(
    path: str | Path, *, plugins: Sequence[Plugin] | None = None
) -> tuple[WorldActor, WorldMeta]:
    """Reload a world from ``path``. Applies ``plugins`` (handlers/systems) before loading."""
    path = Path(path)
    data = json.loads(path.read_text())
    meta = WorldMeta.model_validate(data.get("bunnyland", {}))

    actor = WorldActor()
    if plugins is not None:
        apply_plugins(plugins, actor)

    component_registry, edge_registry = type_registries(plugins)
    relics.load(
        actor.world, path, component_registry=component_registry, edge_registry=edge_registry
    )
    actor.bind_clock()  # the __init__ clock was cleared by the load; rebind to the saved one
    return actor, meta


__all__ = ["SCHEMA_VERSION", "WorldMeta", "load_world", "save_world", "type_registries"]
