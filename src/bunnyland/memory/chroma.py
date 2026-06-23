"""ChromaDB-backed memory store (spec 15.3). Optional: requires the ``chroma`` extra.

Implements the same ``MemoryStore`` interface as ``InMemoryStore`` using a Chroma
collection per character for vector retrieval, while keeping recency ordering via an
inserted sequence number in the metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from .store import MemoryDocument, MemoryEntry


def _metadata_for_chroma(metadata: dict[str, Any]) -> dict[str, Any]:
    values = dict(metadata)
    raw_tags = values.get("tags")
    if isinstance(raw_tags, (list, tuple)):
        values["tags"] = ",".join(str(tag) for tag in raw_tags if str(tag))
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
        self._counter += 1
        entry = MemoryEntry(
            id=uuid4().hex,
            text=text,
            tags=tuple(tags),
            created_at_epoch=created_at_epoch,
            source=source,
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
        return entry

    def search(
        self,
        collection: str,
        *,
        query: str | None = None,
        mode: str = "recent",
        limit: int = 5,
    ) -> list[MemoryEntry]:
        col = self._collection(collection)
        if mode == "vector" and query:
            result = col.query(query_texts=[query], n_results=limit)
            return self._entries_from_query(result)
        # recent / keyword: pull everything and order by sequence (most recent first).
        got = col.get(include=["documents", "metadatas"])
        entries = self._entries_from_get(got)
        entries.sort(key=lambda e: e.created_at_epoch, reverse=True)
        if query and mode == "keyword":
            tokens = set(query.lower().split())
            entries = [e for e in entries if tokens & set(e.text.lower().split())]
        return entries[:limit]

    def delete(self, collection: str, note_id: str) -> bool:
        col = self._collection(collection)
        got = col.get(ids=[note_id])
        ids = got.get("ids", []) or []
        if note_id not in ids:
            return False
        col.delete(ids=[note_id])
        return True

    def list_documents(self, collection: str) -> list[MemoryDocument]:
        got = self._collection(collection).get(include=["documents", "metadatas"])
        return self._documents_from_get(got)

    def create_document(
        self,
        collection: str,
        *,
        document: str,
        metadata: dict[str, Any],
    ) -> MemoryDocument:
        note_id = uuid4().hex
        self._collection(collection).add(
            ids=[note_id],
            documents=[document],
            metadatas=[_metadata_for_chroma(metadata)],
        )
        return MemoryDocument(id=note_id, document=document, metadata=dict(metadata))

    def update_document(
        self,
        collection: str,
        note_id: str,
        *,
        document: str,
        metadata: dict[str, Any],
    ) -> MemoryDocument | None:
        col = self._collection(collection)
        got = col.get(ids=[note_id])
        ids = got.get("ids", []) or []
        if note_id not in ids:
            return None
        col.update(
            ids=[note_id],
            documents=[document],
            metadatas=[_metadata_for_chroma(metadata)],
        )
        return MemoryDocument(id=note_id, document=document, metadata=dict(metadata))

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
                    metadata=dict(meta or {}),
                )
            )
        return documents

    @staticmethod
    def _tags_from_metadata(meta: dict) -> tuple[str, ...]:
        raw = meta.get("tags", "")
        if isinstance(raw, str):
            return tuple(t for t in raw.split(",") if t)
        if isinstance(raw, (list, tuple)):
            return tuple(str(t) for t in raw if str(t))
        return ()

    @classmethod
    def _entries_from_get(cls, got: dict) -> list[MemoryEntry]:
        ids = got.get("ids", []) or []
        docs = got.get("documents", []) or []
        metas = got.get("metadatas", []) or []
        entries = []
        for id_, doc, meta in zip(ids, docs, metas, strict=False):
            meta = meta or {}
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
