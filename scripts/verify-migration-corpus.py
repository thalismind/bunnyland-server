#!/usr/bin/env python3
"""Verify every supported persisted schema using the imported Bunnyland package."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import JsonValue, TypeAdapter

from bunnyland.migrations import CURRENT_SCHEMA_VERSION, migrate_snapshot

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def _load(path: Path) -> dict[str, JsonValue]:
    if path.suffix == ".json":
        value = json.loads(path.read_text())
    else:
        value = yaml.safe_load(path.read_text())
    return JSON_OBJECT.validate_python(value)


def _canonical_snapshot(snapshot: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Discard semantically empty type tables added by historical migrations."""

    canonical = dict(snapshot)
    for table_name in ("components", "relationships"):
        table = canonical.get(table_name)
        if isinstance(table, dict):
            canonical[table_name] = {
                name: rows for name, rows in table.items() if rows != {}
            }
    return canonical


def main() -> None:
    corpus = Path(__file__).parents[1] / "tests" / "fixtures" / "migrations"
    for suffix in ("json", "yaml"):
        expected = _canonical_snapshot(
            migrate_snapshot(
                _load(corpus / f"schema-v{CURRENT_SCHEMA_VERSION}-minimal.{suffix}")
            )
        )
        for version in range(1, CURRENT_SCHEMA_VERSION + 1):
            source = _load(corpus / f"schema-v{version}-minimal.{suffix}")
            migrated = _canonical_snapshot(migrate_snapshot(source))
            if migrated != expected:
                raise AssertionError(
                    f"schema-v{version} {suffix} migration does not match schema-v4"
                )


if __name__ == "__main__":
    main()
