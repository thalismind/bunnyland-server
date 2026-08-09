"""ChromaDB-backed memory store (spec 15.3). Optional: requires the ``chroma`` extra.

Implements the same ``MemoryStore`` interface as ``InMemoryStore`` using a Chroma
collection per character for vector retrieval, while keeping recency ordering via an
inserted sequence number in the metadata.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pydantic import JsonValue, TypeAdapter

from .. import telemetry
from .store import MemoryDocument, MemoryEntry, normalize_tags

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class _ChromaCollection(Protocol):
    def add(
        self,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, JsonValue]],
    ) -> None: ...

    def query(self, *, query_texts: list[str], n_results: int) -> dict[str, object]: ...

    def get(
        self,
        ids: list[str] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, object]: ...

    def delete(self, *, ids: list[str]) -> None: ...

    def update(
        self,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, JsonValue]],
    ) -> None: ...


class _ChromaClient(Protocol):
    def get_or_create_collection(
        self, *, name: str, **kwargs: object
    ) -> _ChromaCollection: ...


def _flat_list(result: dict[str, object], key: str) -> list[object]:
    value = result.get(key)
    return value if isinstance(value, list) else []


def _nested_list(result: dict[str, object], key: str) -> list[object]:
    outer = _flat_list(result, key)
    if not outer or not isinstance(outer[0], list):
        return []
    return outer[0]


def _json_object(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        return {}
    return _JSON_OBJECT.validate_python(value)


def _metadata_for_chroma(metadata: dict[str, JsonValue]) -> dict[str, JsonValue]:
    values = dict(metadata)
    values["tags"] = ",".join(normalize_tags(values.get("tags", ())))
    return values


def _metadata_for_document(metadata: dict[str, JsonValue]) -> dict[str, JsonValue]:
    values = dict(metadata)
    values["tags"] = list(normalize_tags(values.get("tags", ())))
    return values


class ChromaMemoryStore:
    """Vector-backed store. ``chromadb`` is imported lazily so core stays light."""

    def __init__(
        self,
        client: _ChromaClient | None = None,
        embedding_function: object | None = None,
        persist_path: str | Path | None = None,
    ) -> None:
        if client is None:
            try:
                import chromadb
            except ImportError as exc:
                raise RuntimeError(
                    "ChromaMemoryStore requires the 'chroma' extra: pip install bunnyland[chroma]"
                ) from exc
            client = (
                chromadb.PersistentClient(path=str(persist_path))
                if persist_path is not None
                else chromadb.EphemeralClient()
            )
        self._client = client
        self._embedding_function = embedding_function
        self._counter = 0

    def _collection(self, collection: str) -> _ChromaCollection:
        kwargs: dict[str, object] = {}
        if self._embedding_function is not None:
            kwargs["embedding_function"] = self._embedding_function
        return self._client.get_or_create_collection(name=collection, **kwargs)

    def add(
        self,
        collection: str,
        *,
        text: str,
        tags: tuple[str, ...] = (),
        created_at_epoch: int = 0,
        source: str = "manual",
    ) -> MemoryEntry:
        with telemetry.span(
            "memory.backend", {"memory.backend": "chroma", "memory.operation": "add"}
        ) as backend_span:
            self._counter += 1
            metadata = {
                "tags": list(normalize_tags(tags)),
                "created_at_epoch": created_at_epoch,
                "source": source,
            }
            entry = MemoryEntry(
                id=uuid4().hex,
                text=text,
                tags=normalize_tags(tags),
                created_at_epoch=created_at_epoch,
                source=source,
                metadata=metadata,
            )
            self._collection(collection).add(
                ids=[entry.id],
                documents=[text],
                metadatas=[
                    {
                        "tags": ",".join(tags),
                        "created_at_epoch": created_at_epoch,
                        "source": source,
                        "seq": self._counter,
                    }
                ],
            )
            backend_span.set_attribute("memory.documents.count", 1)
            telemetry.mark_span_ok(backend_span)
            return entry

    def search(
        self,
        collection: str,
        *,
        query: str | None = None,
        mode: str = "recent",
        limit: int = 5,
    ) -> list[MemoryEntry]:
        with telemetry.span(
            "memory.backend",
            {
                "memory.backend": "chroma",
                "memory.operation": "search",
                "memory.search.mode": mode,
                "memory.limit": limit,
                "memory.query.present": bool(query),
            },
        ) as backend_span:
            col = self._collection(collection)
            if mode == "vector" and query:
                result = self._entries_from_query(col.query(query_texts=[query], n_results=limit))
            else:
                # recent / keyword: pull everything and order by sequence (most recent first).
                got = col.get(include=["documents", "metadatas"])
                entries = self._entries_from_get(got)
                entries.sort(key=lambda e: e.created_at_epoch, reverse=True)
                if query and mode == "keyword":
                    tokens = set(query.lower().split())
                    entries = [e for e in entries if tokens & set(e.text.lower().split())]
                result = entries[:limit]
            backend_span.set_attribute("memory.results.count", len(result))
            telemetry.mark_span_ok(backend_span)
            return result

    def delete(self, collection: str, note_id: str) -> bool:
        with telemetry.span(
            "memory.backend", {"memory.backend": "chroma", "memory.operation": "delete"}
        ) as backend_span:
            col = self._collection(collection)
            got = col.get(ids=[note_id])
            ids = got.get("ids", []) or []
            if note_id not in ids:
                backend_span.set_attribute("memory.outcome", "not_found")
                backend_span.set_attribute("memory.documents.count", 0)
                telemetry.mark_span_ok(backend_span)
                return False
            col.delete(ids=[note_id])
            backend_span.set_attribute("memory.outcome", "deleted")
            backend_span.set_attribute("memory.documents.count", 1)
            telemetry.mark_span_ok(backend_span)
            return True

    def list_documents(self, collection: str) -> list[MemoryDocument]:
        with telemetry.span(
            "memory.backend", {"memory.backend": "chroma", "memory.operation": "list"}
        ) as backend_span:
            got = self._collection(collection).get(include=["documents", "metadatas"])
            documents = self._documents_from_get(got)
            backend_span.set_attribute("memory.results.count", len(documents))
            telemetry.mark_span_ok(backend_span)
            return documents

    def create_document(
        self,
        collection: str,
        *,
        document: str,
        metadata: dict[str, JsonValue],
    ) -> MemoryDocument:
        with telemetry.span(
            "memory.backend", {"memory.backend": "chroma", "memory.operation": "create"}
        ) as backend_span:
            note_id = uuid4().hex
            self._collection(collection).add(
                ids=[note_id],
                documents=[document],
                metadatas=[_metadata_for_chroma(metadata)],
            )
            result = MemoryDocument(
                id=note_id,
                document=document,
                metadata=_metadata_for_document(metadata),
            )
            backend_span.set_attribute("memory.documents.count", 1)
            telemetry.mark_span_ok(backend_span)
            return result

    def update_document(
        self,
        collection: str,
        note_id: str,
        *,
        document: str,
        metadata: dict[str, JsonValue],
    ) -> MemoryDocument | None:
        with telemetry.span(
            "memory.backend", {"memory.backend": "chroma", "memory.operation": "update"}
        ) as backend_span:
            col = self._collection(collection)
            got = col.get(ids=[note_id])
            ids = got.get("ids", []) or []
            if note_id not in ids:
                backend_span.set_attribute("memory.outcome", "not_found")
                backend_span.set_attribute("memory.documents.count", 0)
                telemetry.mark_span_ok(backend_span)
                return None
            col.update(
                ids=[note_id],
                documents=[document],
                metadatas=[_metadata_for_chroma(metadata)],
            )
            result = MemoryDocument(
                id=note_id,
                document=document,
                metadata=_metadata_for_document(metadata),
            )
            backend_span.set_attribute("memory.outcome", "updated")
            backend_span.set_attribute("memory.documents.count", 1)
            telemetry.mark_span_ok(backend_span)
            return result

    @staticmethod
    def _documents_from_get(got: dict[str, object]) -> list[MemoryDocument]:
        ids = _flat_list(got, "ids")
        docs = _flat_list(got, "documents")
        metas = _flat_list(got, "metadatas")
        documents = []
        for id_, doc, meta in zip(ids, docs, metas, strict=False):
            documents.append(
                MemoryDocument(
                    id=str(id_),
                    document=str(doc or ""),
                    metadata=_metadata_for_document(_json_object(meta)),
                )
            )
        return documents

    @staticmethod
    def _tags_from_metadata(meta: dict[str, JsonValue]) -> tuple[str, ...]:
        return normalize_tags(meta.get("tags", ""))

    @classmethod
    def _entries_from_get(cls, got: dict[str, object]) -> list[MemoryEntry]:
        ids = _flat_list(got, "ids")
        docs = _flat_list(got, "documents")
        metas = _flat_list(got, "metadatas")
        entries = []
        for id_, doc, meta in zip(ids, docs, metas, strict=False):
            decoded_meta = _metadata_for_document(_json_object(meta))
            entries.append(
                MemoryEntry(
                    id=str(id_),
                    text=str(doc or ""),
                    tags=cls._tags_from_metadata(decoded_meta),
                    created_at_epoch=int(decoded_meta.get("created_at_epoch", 0)),
                    source=str(decoded_meta.get("source", "manual")),
                    metadata=dict(decoded_meta),
                )
            )
        return entries

    @classmethod
    def _entries_from_query(cls, result: dict[str, object]) -> list[MemoryEntry]:
        # Chroma query nests results one level deeper (per query text).
        flatten = {
            "ids": _nested_list(result, "ids"),
            "documents": _nested_list(result, "documents"),
            "metadatas": _nested_list(result, "metadatas"),
        }
        entries = cls._entries_from_get(flatten)
        distances = _nested_list(result, "distances")
        return [
            replace(
                entry,
                score=(
                    1.0 / (1.0 + max(0.0, float(distance)))
                    if index < len(distances)
                    and isinstance((distance := distances[index]), (int, float))
                    else None
                ),
            )
            for index, entry in enumerate(entries)
        ]


__all__ = ["ChromaMemoryStore"]
