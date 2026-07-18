"""ChromaDB-backed memory store (spec 15.3). Optional: requires the ``chroma`` extra.

Implements the same ``MemoryStore`` interface as ``InMemoryStore`` using a Chroma
collection per character for vector retrieval, while keeping recency ordering via an
inserted sequence number in the metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from .. import telemetry
from .store import MemoryDocument, MemoryEntry, normalize_tags


def _metadata_for_chroma(metadata: dict[str, Any]) -> dict[str, Any]:
    values = dict(metadata)
    values["tags"] = ",".join(normalize_tags(values.get("tags", ())))
    return values


def _metadata_for_document(metadata: dict[str, Any]) -> dict[str, Any]:
    values = dict(metadata)
    values["tags"] = list(normalize_tags(values.get("tags", ())))
    return values


class ChromaMemoryStore:
    """Vector-backed store. ``chromadb`` is imported lazily so core stays light."""

    def __init__(
        self,
        client=None,
        embedding_function=None,
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

    def _collection(self, collection: str):
        kwargs = {}
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
        metadata: dict[str, Any],
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
        metadata: dict[str, Any],
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
    def _documents_from_get(got: dict) -> list[MemoryDocument]:
        ids = got.get("ids", []) or []
        docs = got.get("documents", []) or []
        metas = got.get("metadatas", []) or []
        documents = []
        for id_, doc, meta in zip(ids, docs, metas, strict=False):
            documents.append(
                MemoryDocument(
                    id=id_,
                    document=doc or "",
                    metadata=_metadata_for_document(meta or {}),
                )
            )
        return documents

    @staticmethod
    def _tags_from_metadata(meta: dict) -> tuple[str, ...]:
        return normalize_tags(meta.get("tags", ""))

    @classmethod
    def _entries_from_get(cls, got: dict) -> list[MemoryEntry]:
        ids = got.get("ids", []) or []
        docs = got.get("documents", []) or []
        metas = got.get("metadatas", []) or []
        entries = []
        for id_, doc, meta in zip(ids, docs, metas, strict=False):
            meta = _metadata_for_document(meta or {})
            entries.append(
                MemoryEntry(
                    id=id_,
                    text=doc,
                    tags=cls._tags_from_metadata(meta),
                    created_at_epoch=int(meta.get("created_at_epoch", 0)),
                    source=str(meta.get("source", "manual")),
                    metadata=dict(meta),
                )
            )
        return entries

    @classmethod
    def _entries_from_query(cls, result: dict) -> list[MemoryEntry]:
        # Chroma query nests results one level deeper (per query text).
        flatten = {
            "ids": (result.get("ids") or [[]])[0],
            "documents": (result.get("documents") or [[]])[0],
            "metadatas": (result.get("metadatas") or [[]])[0],
        }
        return cls._entries_from_get(flatten)


__all__ = ["ChromaMemoryStore"]
