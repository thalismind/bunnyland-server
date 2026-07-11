"""Live ECS type schema for editor and DM clients."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from pydantic import TypeAdapter
from relics import Component, Edge

from ..core.world_actor import WorldActor
from ..persistence import type_registries
from .models import EcsTypeSchema, WorldSchemaResponse


def _component_registry(actor: WorldActor) -> dict[str, type[Component]]:
    if actor.plugins is None:
        raise RuntimeError("world schema requires an applied PluginRegistry")
    return type_registries(actor.plugins)[0]


def _edge_registry(actor: WorldActor) -> dict[str, type[Edge]]:
    if actor.plugins is None:
        raise RuntimeError("world schema requires an applied PluginRegistry")
    return type_registries(actor.plugins)[1]


def _type_schema(name: str, type_: type, count: int) -> EcsTypeSchema:
    schema_error = None
    try:
        json_schema = TypeAdapter(type_).json_schema()
    except Exception as exc:  # noqa: BLE001 - a plugin type should not break the endpoint.
        schema_error = str(exc)
        json_schema = {
            "title": name,
            "type": "object",
            "additionalProperties": True,
        }
    return EcsTypeSchema(
        name=name,
        module=type_.__module__,
        qualname=type_.__qualname__,
        json_schema=json_schema,
        used=count > 0,
        count=count,
        schema_error=schema_error,
    )


def _usage_counts(actor: WorldActor) -> tuple[Counter[str], Counter[str]]:
    component_counts: Counter[str] = Counter()
    edge_counts: Counter[str] = Counter()
    for entity in actor.world.query().execute_entities():
        exported: dict[str, Any] = actor.world.export_entity(entity.id)
        component_counts.update(exported.get("components", {}).keys())
        for edge_name, edges in exported.get("relationships", {}).items():
            edge_counts[edge_name] += len(edges)
    return component_counts, edge_counts


def world_schema(actor: WorldActor) -> WorldSchemaResponse:
    """Return JSON schemas for ECS component and edge types available to this actor."""

    component_counts, edge_counts = _usage_counts(actor)
    component_types = _component_registry(actor)
    edge_types = _edge_registry(actor)
    return WorldSchemaResponse(
        world_epoch=actor.epoch,
        components={
            name: _type_schema(name, type_, component_counts[name])
            for name, type_ in sorted(component_types.items())
        },
        edges={
            name: _type_schema(name, type_, edge_counts[name])
            for name, type_ in sorted(edge_types.items())
        },
    )


def dm_schema_context(actor: WorldActor) -> str:
    """Return the live schema payload in a compact form suitable for DM prompts."""

    schema = world_schema(actor)
    payload = {
        "schema_version": schema.schema_version,
        "world_epoch": schema.world_epoch,
        "components": {name: item.json_schema for name, item in schema.components.items()},
        "edges": {name: item.json_schema for name, item in schema.edges.items()},
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


__all__ = ["dm_schema_context", "world_schema"]
