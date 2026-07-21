#!/usr/bin/env python3
"""Regenerate the reviewed v1 OpenAPI and JSON Schema baselines."""

from __future__ import annotations

import json
from pathlib import Path

from bunnyland.core import WorldActor
from bunnyland.plugins import apply_plugins, bunnyland_plugins
from bunnyland.server.app import create_app


def _standalone_schema(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _standalone_schema(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_standalone_schema(item) for item in value]
    if isinstance(value, str) and value.startswith("#/components/schemas/"):
        return value.replace("#/components/schemas/", "#/$defs/", 1)
    return value


def main() -> None:
    actor = WorldActor()
    plugins = bunnyland_plugins()
    apply_plugins(plugins, actor)
    schema = create_app(
        actor,
        plugins=plugins,
        allow_unauthenticated_embedding=True,
    ).openapi()
    root = Path(__file__).parents[1] / "contracts"
    root.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    (root / "openapi-v1.json").write_text(rendered)
    json_schemas = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": _standalone_schema(schema.get("components", {}).get("schemas", {})),
    }
    (root / "json-schema-v1.json").write_text(
        json.dumps(json_schemas, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
