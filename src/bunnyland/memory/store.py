"""Memory store interface and an in-memory backend (spec 15).

Each character has a private collection of notes/memories. The store is deliberately
decoupled from the ECS: notes live in the store (with optional ECS entities only if
useful — spec 11.16). The vector backend (ChromaDB) implements the same interface.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

# Minimum difflib similarity for a query token to count as a fuzzy match. Exact matches
# always score 1.0; this only governs typo/near-miss tolerance in keyword search.
_FUZZY_CUTOFF = 0.8


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    text: str
    tags: tuple[str, ...] = ()
    created_at_epoch: int = 0
    source: str = "manual"
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryDocument:
    id: str
    document: str
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryStore(Protocol):
    def add(
        self,
        collection: str,
        *,
        text: str,
        tags: tuple[str, ...] = (),
        created_at_epoch: int = 0,
        source: str = "manual",
    ) -> MemoryEntry: ...

    def search(
        self,
        collection: str,
        *,
        query: str | None = None,
        mode: str = "recent",
        limit: int = 5,
    ) -> list[MemoryEntry]: ...

    def delete(self, collection: str, note_id: str) -> bool: ...

    def list_documents(self, collection: str) -> list[MemoryDocument]: ...

    def create_document(
        self,
        collection: str,
        *,
        document: str,
        metadata: dict[str, Any],
    ) -> MemoryDocument: ...

    def update_document(
        self,
        collection: str,
        note_id: str,
        *,
        document: str,
        metadata: dict[str, Any],
    ) -> MemoryDocument | None: ...


@dataclass(frozen=True)
class MemoryCheckpointResult:
    checkpoint_epoch: int
    quarantined: int = 0
    collections: tuple[str, ...] = ()


def quarantine_after_epoch(
    store: MemoryStore,
    collections: tuple[str, ...],
    *,
    checkpoint_epoch: int,
    world_namespace: str,
) -> MemoryCheckpointResult:
    """Move future source documents out of active collections after an older restore."""

    quarantined = 0
    for collection in collections:
        safe_namespace = re.sub(r"[^a-zA-Z0-9._-]+", "-", world_namespace).strip("-._")
        safe_collection = re.sub(r"[^a-zA-Z0-9._-]+", "-", collection).strip("-._")
        destination = f"{safe_namespace or 'world'}.quarantine.{safe_collection or 'memory'}"
        for document in tuple(store.list_documents(collection)):
            created_at = int(document.metadata.get("created_at_epoch", 0) or 0)
            if created_at <= checkpoint_epoch:
                continue
            metadata = {
                **document.metadata,
                "quarantined_from": collection,
                "quarantined_after_epoch": checkpoint_epoch,
            }
            store.create_document(destination, document=document.document, metadata=metadata)
            store.delete(collection, document.id)
            quarantined += 1
    return MemoryCheckpointResult(
        checkpoint_epoch=checkpoint_epoch,
        quarantined=quarantined,
        collections=collections,
    )


_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "at",
        "by",
        "for",
        "in",
        "is",
        "of",
        "on",
        "the",
        "to",
        "with",
    }
)


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9']+", text.lower()) if token not in _STOPWORDS}


def _fuzzy_score(query_tokens: set[str], candidates: set[str]) -> float:
    """Score query tokens against an entry's tokens, tolerating typos via difflib.

    Each query token contributes the similarity ratio of its best candidate match
    (1.0 for an exact hit), so close-but-imperfect tokens still rank, while the cutoff
    keeps unrelated tokens from matching.
    """
    pool = list(candidates)
    score = 0.0
    for token in query_tokens:
        match = difflib.get_close_matches(token, pool, n=1, cutoff=_FUZZY_CUTOFF)
        if match:
            score += difflib.SequenceMatcher(None, token, match[0]).ratio()
    return score


def _entry_metadata(
    tags: tuple[str, ...],
    created_at_epoch: int,
    source: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = dict(metadata or {})
    values["tags"] = list(normalize_tags(values.get("tags", tags)))
    values.setdefault("created_at_epoch", created_at_epoch)
    values.setdefault("source", source)
    return values


def normalize_tags(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        return tuple(tag for tag in (part.strip() for part in raw.split(",")) if tag)
    if isinstance(raw, (list, tuple)):
        values = tuple(str(tag) for tag in raw if str(tag).strip())
        if values and "," in values and all(len(tag) == 1 for tag in values):
            return normalize_tags("".join(values))
        tags: list[str] = []
        for value in values:
            tags.extend(normalize_tags(value) if "," in value else (value.strip(),))
        return tuple(tag for tag in tags if tag)
    return ()


def _entry_from_document(document: MemoryDocument) -> MemoryEntry:
    metadata = _entry_metadata(
        normalize_tags(document.metadata.get("tags", ())),
        int(document.metadata.get("created_at_epoch", 0) or 0),
        str(document.metadata.get("source", "manual")),
        document.metadata,
    )
    return MemoryEntry(
        id=document.id,
        text=document.document,
        tags=normalize_tags(metadata.get("tags", ())),
        created_at_epoch=int(metadata.get("created_at_epoch", 0) or 0),
        source=str(metadata.get("source", "manual")),
        metadata=metadata,
    )


class InMemoryStore:
    """A simple, dependency-free store. ``vector`` mode falls back to keyword scoring."""

    def __init__(self) -> None:
        self._collections: dict[str, list[MemoryEntry]] = defaultdict(list)

    def add(
        self,
        collection: str,
        *,
        text: str,
        tags: tuple[str, ...] = (),
        created_at_epoch: int = 0,
        source: str = "manual",
    ) -> MemoryEntry:
        entry = MemoryEntry(
            id=uuid4().hex,
            text=text,
            tags=tuple(tags),
            created_at_epoch=created_at_epoch,
            source=source,
            metadata=_entry_metadata(tuple(tags), created_at_epoch, source),
        )
        self._collections[collection].append(entry)
        return entry

    def search(
        self,
        collection: str,
        *,
        query: str | None = None,
        mode: str = "recent",
        limit: int = 5,
    ) -> list[MemoryEntry]:
        entries = self._collections.get(collection, [])
        if not entries:
            return []
        if mode == "recent" or not query:
            return list(reversed(entries))[:limit]
        # keyword / vector (fallback): fuzzy token score, then recency.
        query_tokens = _tokens(query)
        scored: list[MemoryEntry] = []
        for entry in entries:
            score = _fuzzy_score(query_tokens, _tokens(entry.text) | set(entry.tags))
            if score:
                scored.append(
                    MemoryEntry(
                        id=entry.id,
                        text=entry.text,
                        tags=entry.tags,
                        created_at_epoch=entry.created_at_epoch,
                        source=entry.source,
                        score=score,
                        metadata=dict(entry.metadata),
                    )
                )
        scored.sort(key=lambda e: (e.score or 0.0, e.created_at_epoch), reverse=True)
        return scored[:limit]

    def delete(self, collection: str, note_id: str) -> bool:
        entries = self._collections.get(collection, [])
        for index, entry in enumerate(entries):
            if entry.id == note_id:
                del entries[index]
                return True
        return False

    def list_documents(self, collection: str) -> list[MemoryDocument]:
        documents = []
        for entry in self._collections.get(collection, []):
            metadata = _entry_metadata(
                entry.tags,
                entry.created_at_epoch,
                entry.source,
                entry.metadata,
            )
            documents.append(MemoryDocument(id=entry.id, document=entry.text, metadata=metadata))
        return documents

    def create_document(
        self,
        collection: str,
        *,
        document: str,
        metadata: dict[str, Any],
    ) -> MemoryDocument:
        created = _entry_from_document(
            MemoryDocument(id=uuid4().hex, document=document, metadata=dict(metadata))
        )
        self._collections[collection].append(created)
        return MemoryDocument(
            id=created.id,
            document=created.text,
            metadata=_entry_metadata(
                created.tags,
                created.created_at_epoch,
                created.source,
                created.metadata,
            ),
        )

    def update_document(
        self,
        collection: str,
        note_id: str,
        *,
        document: str,
        metadata: dict[str, Any],
    ) -> MemoryDocument | None:
        entries = self._collections.get(collection, [])
        updated = _entry_from_document(
            MemoryDocument(id=note_id, document=document, metadata=dict(metadata))
        )
        for index, entry in enumerate(entries):
            if entry.id == note_id:
                entries[index] = updated
                return MemoryDocument(
                    id=updated.id,
                    document=updated.text,
                    metadata=dict(updated.metadata),
                )
        return None


__all__ = [
    "InMemoryStore",
    "MemoryDocument",
    "MemoryEntry",
    "MemoryCheckpointResult",
    "MemoryStore",
    "normalize_tags",
    "quarantine_after_epoch",
]
