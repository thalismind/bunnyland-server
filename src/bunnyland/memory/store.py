"""Memory store interface and an in-memory backend (spec 15).

Each character has a private collection of notes/memories. The store is deliberately
decoupled from the ECS: notes live in the store (with optional ECS entities only if
useful — spec 11.16). The vector backend (ChromaDB) implements the same interface.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    text: str
    tags: tuple[str, ...] = ()
    created_at_epoch: int = 0
    source: str = "manual"
    score: float | None = None


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
    return {
        token
        for token in re.findall(r"[a-z0-9']+", text.lower())
        if token not in _STOPWORDS
    }


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
        # keyword / vector (fallback): score by token overlap, then recency.
        query_tokens = _tokens(query)
        scored: list[MemoryEntry] = []
        for entry in entries:
            overlap = len(query_tokens & (_tokens(entry.text) | set(entry.tags)))
            if overlap:
                scored.append(
                    MemoryEntry(
                        id=entry.id,
                        text=entry.text,
                        tags=entry.tags,
                        created_at_epoch=entry.created_at_epoch,
                        source=entry.source,
                        score=float(overlap),
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


__all__ = ["InMemoryStore", "MemoryEntry", "MemoryStore"]
