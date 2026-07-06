#!/usr/bin/env python3
"""Rename legacy Toon component keys in persisted world snapshots.

The server no longer registers the legacy ``Sprite*`` component names. Run this script
against saved JSON/YAML worlds before loading them with the renamed components.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

RENAMES = {
    "SpritePosition": "SpritePositionComponent",
    "SpriteImage": "SpriteImageComponent",
    "SpriteLayer": "SpriteLayerComponent",
    "SpriteScale": "SpriteScaleComponent",
    "SpriteBounds": "SpriteBoundsComponent",
}

SUPPORTED_SUFFIXES = frozenset({".json", ".yaml", ".yml"})


def _merge_values(old_value: Any, new_value: Any, *, key: str) -> Any:
    if isinstance(old_value, dict) and isinstance(new_value, dict):
        merged = dict(new_value)
        for child_key, child_value in old_value.items():
            if child_key in merged:
                merged[child_key] = _merge_values(
                    child_value,
                    merged[child_key],
                    key=f"{key}.{child_key}",
                )
            else:
                merged[child_key] = child_value
        return merged
    if old_value == new_value:
        return new_value
    raise ValueError(f"cannot merge conflicting values for {key}")


def rename_keys(value: Any) -> tuple[Any, int]:
    """Return ``value`` with legacy Toon component mapping keys renamed."""
    if isinstance(value, list):
        changed = 0
        renamed_items = []
        for item in value:
            renamed_item, item_changed = rename_keys(item)
            changed += item_changed
            renamed_items.append(renamed_item)
        return renamed_items, changed

    if not isinstance(value, dict):
        return value, 0

    changed = 0
    renamed: dict[Any, Any] = {}
    for raw_key, raw_item in value.items():
        item, item_changed = rename_keys(raw_item)
        changed += item_changed
        key = RENAMES.get(raw_key, raw_key)
        if key != raw_key:
            changed += 1
        if key in renamed:
            renamed[key] = _merge_values(item, renamed[key], key=str(key))
        else:
            renamed[key] = item
    return renamed, changed


def _paths(inputs: list[Path], *, recursive: bool) -> list[Path]:
    paths: list[Path] = []
    for input_path in inputs:
        if input_path.is_dir():
            glob = input_path.rglob if recursive else input_path.glob
            paths.extend(path for path in glob("*") if path.suffix.lower() in SUPPORTED_SUFFIXES)
        elif input_path.suffix.lower() in SUPPORTED_SUFFIXES:
            paths.append(input_path)
    return sorted(set(paths))


def migrate_file(path: Path, *, dry_run: bool) -> int:
    suffix = path.suffix.lower()
    text = path.read_text()
    if suffix == ".json":
        data = json.loads(text)
        migrated, changed = rename_keys(data)
        if changed and not dry_run:
            path.write_text(json.dumps(migrated, indent=2, sort_keys=True) + "\n")
        return changed

    data = yaml.safe_load(text) or {}
    migrated, changed = rename_keys(data)
    if changed and not dry_run:
        path.write_text(yaml.safe_dump(migrated, sort_keys=False))
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rename legacy Toon Sprite* component keys in saved worlds."
    )
    parser.add_argument("paths", nargs="+", type=Path, help="world files or directories")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="walk directories recursively instead of checking only direct children",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report files that would change without writing them",
    )
    args = parser.parse_args()

    total_files = 0
    total_changes = 0
    for path in _paths(args.paths, recursive=args.recursive):
        changes = migrate_file(path, dry_run=args.dry_run)
        if changes:
            total_files += 1
            total_changes += changes
            action = "would update" if args.dry_run else "updated"
            print(f"{action} {path}: {changes} renamed keys")

    print(f"{total_files} file(s), {total_changes} renamed key(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
