"""JSON-file-backed memory store (spec 15). No optional dependencies.

Implements the same ``MemoryStore`` interface as ``InMemoryStore`` and reuses its
keyword/recency search, but persists every character collection to a single JSON file
per world. The file is loaded on construction and rewritten after each mutation, so
notes and remembered facts survive a server restart without requiring the ``chroma``
extra.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import telemetry
from .store import (
    InMemoryStore,
    MemoryEntry,
    _entry_metadata,
    normalize_tags,
)


def _entry_to_json(entry: MemoryEntry) -> dict[str, Any]:
    # ``score`` is search-only state, so it is intentionally not persisted.
    return {
        "id": entry.id,
        "text": entry.text,
        "tags": list(entry.tags),
        "created_at_epoch": entry.created_at_epoch,
        "source": entry.source,
        "metadata": dict(entry.metadata),
    }


def _entry_from_json(data: dict[str, Any]) -> MemoryEntry:
    tags = normalize_tags(data.get("tags", ()))
    metadata = _entry_metadata(
        tags,
        int(data.get("created_at_epoch", 0) or 0),
        str(data.get("source", "manual")),
        data.get("metadata"),
    )
    return MemoryEntry(
        id=str(data["id"]),
        text=str(data.get("text", "")),
        tags=normalize_tags(metadata.get("tags", tags)),
        created_at_epoch=int(metadata.get("created_at_epoch", 0) or 0),
        source=str(metadata.get("source", "manual")),
        metadata=metadata,
    )


class JsonMemoryStore(InMemoryStore):
    """File-backed store: all character collections live in one JSON document.

    Inherits the in-memory search/list behavior and flushes the full state to disk
    after each mutating call, reloading it on construction.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path)
        self._load()

    def _load(self) -> None:
        with telemetry.span(
            "memory.backend", {"memory.backend": "json", "memory.operation": "load"}
        ) as backend_span:
            if not self._path.exists():
                backend_span.set_attribute("memory.outcome", "absent")
                backend_span.set_attribute("memory.documents.count", 0)
                telemetry.mark_span_ok(backend_span)
                return
            encoded = self._path.read_text(encoding="utf-8")
            raw = json.loads(encoded)
            for collection, entries in raw.get("collections", {}).items():
                self._collections[collection] = [_entry_from_json(item) for item in entries]
            backend_span.set_attribute("memory.outcome", "loaded")
            backend_span.set_attribute("memory.input.bytes", len(encoded.encode("utf-8")))
            backend_span.set_attribute(
                "memory.documents.count",
                sum(len(entries) for entries in self._collections.values()),
            )
            telemetry.mark_span_ok(backend_span)

    def _save(self) -> None:
        with telemetry.span(
            "memory.backend", {"memory.backend": "json", "memory.operation": "save"}
        ) as backend_span:
            data = {
                "collections": {
                    collection: [_entry_to_json(entry) for entry in entries]
                    for collection, entries in self._collections.items()
                }
            }
            encoded = json.dumps(data, indent=2, sort_keys=True)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(encoded, encoding="utf-8")
            backend_span.set_attribute("memory.output.bytes", len(encoded.encode("utf-8")))
            backend_span.set_attribute(
                "memory.documents.count",
                sum(len(entries) for entries in self._collections.values()),
            )
            telemetry.mark_span_ok(backend_span)

    def add(
        self,
        collection: str,
        *,
        text: str,
        tags: tuple[str, ...] = (),
        created_at_epoch: int = 0,
        source: str = "manual",
    ) -> MemoryEntry:
        entry = super().add(
            collection,
            text=text,
            tags=tags,
            created_at_epoch=created_at_epoch,
            source=source,
        )
        self._save()
        return entry

    def delete(self, collection: str, note_id: str) -> bool:
        removed = super().delete(collection, note_id)
        if removed:
            self._save()
        return removed

    def create_document(
        self,
        collection: str,
        *,
        document: str,
        metadata: dict[str, Any],
    ):
        created = super().create_document(collection, document=document, metadata=metadata)
        self._save()
        return created

    def update_document(
        self,
        collection: str,
        note_id: str,
        *,
        document: str,
        metadata: dict[str, Any],
    ):
        updated = super().update_document(collection, note_id, document=document, metadata=metadata)
        if updated is not None:
            self._save()
        return updated


__all__ = ["JsonMemoryStore"]
