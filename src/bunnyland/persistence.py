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

import asyncio
import hashlib
import json
import os
import shutil
from dataclasses import is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from . import telemetry
from .core.queue import CommandQueues
from .core.world_actor import WorldActor
from .migrations import CURRENT_SCHEMA_VERSION, migrate_snapshot
from .persistence_yaml import YAMLPersistenceDriver
from .plugins.loader import PluginError, apply_plugins
from .plugins.model import PluginRuntimeContext
from .plugins.registry import PluginRegistry

SCHEMA_VERSION = CURRENT_SCHEMA_VERSION
PersistenceFormat = Literal["json", "yaml"]
CHECKSUM_SUFFIX = ".sha256"
DEFAULT_BACKUP_COUNT = 3
DEFAULT_JOURNAL_RECORDS = 5000


class MemoryManifest(BaseModel):
    """Versioned authority boundary between world saves and rebuildable memory indexes."""

    version: int = 1
    world_namespace: str = "main"
    backend: str = ""
    checkpoint_epoch: int = 0
    collection_namespace: str = "main"
    embedding_implementation: str = ""
    high_watermark: int = 0


class WorldMeta(BaseModel):
    """The provenance of a world, saved beside the ECS data."""

    schema_version: int = SCHEMA_VERSION
    seed: str = ""
    prompt: str = ""  # the literal DM system prompt used to build the world ("" for stub)
    generator: str = ""  # which world generator produced it
    plugins: tuple[str, ...] = ()  # plugin ids loaded for this world, e.g. module_foo.bar
    saved_at_epoch: int = 0  # bunnyland game epoch at save time
    saved_at: datetime | None = None  # wall-clock save time
    world_id: str = Field(default_factory=lambda: uuid4().hex)
    world_contract_version: int = 1
    memory: MemoryManifest = Field(default_factory=MemoryManifest)
    rng_stream_state: dict[str, Any] = Field(default_factory=dict)


class OperationalJournal:
    """Bounded append-only JSONL audit trail adjacent to a canonical snapshot."""

    def __init__(self, save_path: str | Path, *, max_records: int = DEFAULT_JOURNAL_RECORDS):
        save_path = Path(save_path)
        self.path = save_path.with_name(f"{save_path.name}.journal.jsonl")
        self.max_records = max_records

    def append(self, record_type: str, **fields: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "journal_version": 1,
            "record_type": record_type,
            "recorded_at": datetime.now(UTC).isoformat(),
            **_jsonable(fields),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._bound()

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line]

    def _bound(self) -> None:
        lines = self.path.read_text().splitlines(keepends=True)
        if len(lines) <= self.max_records:
            return
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text("".join(lines[-self.max_records :]))
        _fsync_file(temporary)
        os.replace(temporary, self.path)
        _fsync_directory(self.path.parent)


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
            name: _jsonable(getattr(value, name)) for name in fields if not name.startswith("_")
        }
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def type_registries(
    registry: PluginRegistry,
) -> tuple[dict[str, type], dict[str, type]]:
    """Build ``(component_registry, edge_registry)`` keyed by class name for ``relics.load``."""
    return (
        {name: component for name, (_owner, component) in registry.components.items()},
        {name: edge for name, (_owner, edge) in registry.edges.items()},
    )


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
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> WorldMeta:
    """Write the world (ECS + provenance) to ``path``. Returns the stamped meta."""
    path = Path(path)
    resolved_format = _format_for_path(path, format)
    attrs = {"operation": "save", "format": resolved_format}
    with (
        telemetry.record_duration(telemetry.record_persist, attrs),
        telemetry.span("world.save", {**attrs, "path": str(path)}) as save_span,
    ):
        try:
            memory = meta.memory.model_copy(
                update={
                    "checkpoint_epoch": actor.epoch,
                    "high_watermark": max(meta.memory.high_watermark, actor.epoch),
                }
            )
            stamped = meta.model_copy(
                update={
                    "saved_at_epoch": actor.epoch,
                    "saved_at": datetime.now(UTC),
                    "memory": memory,
                    "rng_stream_state": {"command_order": _jsonable(actor._rng.getstate())},
                }
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            snapshot = _snapshot(actor, stamped)
            temporary = path.with_name(f".{path.name}.tmp")
            if resolved_format == "yaml":
                YAMLPersistenceDriver().save_snapshot(snapshot, temporary)
            else:
                temporary.write_text(json.dumps(snapshot, indent=2, default=str))
            _fsync_file(temporary)
            checksum = _checksum(temporary)
            checksum_path = _checksum_path(path)
            checksum_temporary = checksum_path.with_name(f".{checksum_path.name}.tmp")
            checksum_temporary.write_text(f"{checksum}  {path.name}\n")
            _fsync_file(checksum_temporary)
            _rotate_backups(path, backup_count)
            _rotate_backups(checksum_path, backup_count)
            os.replace(temporary, path)
            os.replace(checksum_temporary, checksum_path)
            _fsync_directory(path.parent)
            OperationalJournal(path).append(
                "checkpoint",
                world_epoch=actor.epoch,
                checksum=checksum,
                rng_stream_state=stamped.rng_stream_state,
                memory_checkpoint_epoch=stamped.memory.checkpoint_epoch,
            )
            if telemetry.enabled():
                save_span.set_attribute(
                    "entity.count", len(list(actor.world.query().execute_entities()))
                )
            telemetry.mark_span_ok(save_span)
            return stamped
        except Exception as exc:
            save_span.record_exception(exc)
            telemetry.mark_span_error(str(exc), save_span)
            raise


def load_world(
    path: str | Path,
    *,
    registry: PluginRegistry,
    plugin_context: PluginRuntimeContext | None = None,
    format: PersistenceFormat | None = None,
) -> tuple[WorldActor, WorldMeta]:
    """Reload a world from ``path``. Applies ``plugins`` (handlers/systems) before loading."""
    path = Path(path)
    selected_format = _format_for_path(path, format)
    attrs = {"operation": "load", "format": selected_format}
    with (
        telemetry.record_duration(telemetry.record_persist, attrs),
        telemetry.span("world.load", {**attrs, "path": str(path)}) as load_span,
    ):
        try:
            _verify_checksum(path)
            yaml_driver = YAMLPersistenceDriver() if selected_format == "yaml" else None
            data = (
                yaml_driver.read_snapshot(path)
                if yaml_driver is not None
                else json.loads(path.read_text())
            )
            data = migrate_snapshot(data)
            meta = WorldMeta.model_validate(data.get("bunnyland", {}))

            actor = WorldActor()
            available = set(registry.plugins)
            missing = tuple(plugin_id for plugin_id in meta.plugins if plugin_id not in available)
            if missing:
                names = ", ".join(repr(plugin_id) for plugin_id in missing)
                raise PluginError(f"saved world depends on missing plugin(s): {names}")
            plugins = tuple(registry.plugins.values())
            apply_plugins(plugins, actor, plugin_context)

            component_registry, edge_registry = type_registries(registry)
            (yaml_driver or YAMLPersistenceDriver()).load_snapshot(
                actor.world,
                data,
                component_registry,
                edge_registry,
            )
            actor.bind_clock()  # the __init__ clock was cleared by load; rebind to the saved one
            actor.world_id = meta.world_id
            state = meta.rng_stream_state.get("command_order")
            if state:
                actor._rng.setstate(_tuples(state))
            if telemetry.enabled():
                load_span.set_attribute(
                    "entity.count", len(list(actor.world.query().execute_entities()))
                )
            telemetry.mark_span_ok(load_span)
            return actor, meta
        except Exception as exc:
            load_span.record_exception(exc)
            telemetry.mark_span_error(str(exc), load_span)
            raise


def reload_world(
    actor: WorldActor,
    path: str | Path,
    *,
    meta: WorldMeta,
    registry: PluginRegistry,
    plugin_context: PluginRuntimeContext | None = None,
    format: PersistenceFormat | None = None,
) -> WorldMeta:
    """Reload ``path`` into a live actor, preserving actor services and plugin wiring.

    The caller must already own ``actor._lock`` when needed. Tick after-hooks run while
    the lock is held, so this helper intentionally does not acquire it itself.
    """

    replacement, loaded_meta = load_world(
        path,
        registry=registry,
        plugin_context=plugin_context,
        format=format,
    )
    actor.world = replacement.world
    actor.world_id = loaded_meta.world_id
    actor.bind_clock()
    actor.queues = CommandQueues()
    actor._inbox = asyncio.Queue()

    updates = loaded_meta.model_dump()
    for key, value in updates.items():
        setattr(meta, key, value)
    actor.configure_persistence(
        save_path=path,
        meta=meta,
        plugins=tuple(registry.plugins.values()),
        plugin_context=plugin_context,
    )
    return meta


def _checksum_path(path: Path) -> Path:
    return path.with_name(f"{path.name}{CHECKSUM_SUFFIX}")


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rotate_backups(path: Path, count: int) -> None:
    if count <= 0 or not path.exists():
        return
    oldest = path.with_name(f"{path.name}.bak.{count}")
    oldest.unlink(missing_ok=True)
    for index in range(count - 1, 0, -1):
        source = path.with_name(f"{path.name}.bak.{index}")
        if source.exists():
            os.replace(source, path.with_name(f"{path.name}.bak.{index + 1}"))
    shutil.copy2(path, path.with_name(f"{path.name}.bak.1"))


def _verify_checksum(path: Path) -> None:
    checksum_path = _checksum_path(path)
    if not checksum_path.exists():
        return  # Backward compatibility for schema-v2 saves made before checksums.
    expected = checksum_path.read_text().split(maxsplit=1)[0]
    actual = _checksum(path)
    if actual != expected:
        raise ValueError(f"checksum mismatch for {path}")


def _tuples(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuples(item) for item in value)
    return value


__all__ = [
    "SCHEMA_VERSION",
    "PersistenceFormat",
    "MemoryManifest",
    "OperationalJournal",
    "WorldMeta",
    "YAMLPersistenceDriver",
    "load_world",
    "reload_world",
    "save_world",
    "type_registries",
]
