"""Private notes and memory (spec 15): focus-lane verbs over a pluggable store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .handlers import (
    ConversationMemoryReactor,
    ForgetHandler,
    ReflectHandler,
    ReflectionLoopConsequence,
    RememberHandler,
    TakeNoteHandler,
)
from .store import (
    InMemoryStore,
    MemoryCheckpointResult,
    MemoryDocument,
    MemoryEntry,
    MemoryStore,
    quarantine_after_epoch,
)

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor


@dataclass(frozen=True)
class MemoryRecallPolicy:
    limit: int = 3
    min_score: float = 0.35


def configure_memory_recall(
    actor: WorldActor,
    *,
    limit: int = 3,
    min_score: float = 0.35,
) -> None:
    if limit < 0:
        raise ValueError("memory recall limit must not be negative")
    if not 0.0 <= min_score <= 1.0:
        raise ValueError("memory recall minimum score must be between 0 and 1")
    actor.memory_recall_policy = MemoryRecallPolicy(limit=limit, min_score=min_score)


def install_memory(actor: WorldActor, store: MemoryStore | None = None) -> MemoryStore:
    """Register the take-note and remember handlers on an actor (spec 21 preview).

    Returns the store so callers can inspect/share it. Defaults to an in-memory store.
    """
    store = store or InMemoryStore()
    actor.memory_store = store
    if actor.memory_recall_policy is None:
        configure_memory_recall(actor)
    actor.register_handler(TakeNoteHandler(store))
    actor.register_handler(RememberHandler(store))
    actor.register_handler(ForgetHandler(store))
    actor.register_handler(ReflectHandler(store))
    ConversationMemoryReactor(actor.world, store).subscribe(actor.bus)
    actor.register_consequence(ReflectionLoopConsequence(store))
    return store


__all__ = [
    "ConversationMemoryReactor",
    "ForgetHandler",
    "InMemoryStore",
    "MemoryDocument",
    "MemoryCheckpointResult",
    "MemoryEntry",
    "MemoryRecallPolicy",
    "MemoryStore",
    "ReflectHandler",
    "ReflectionLoopConsequence",
    "RememberHandler",
    "TakeNoteHandler",
    "install_memory",
    "configure_memory_recall",
    "quarantine_after_epoch",
]
