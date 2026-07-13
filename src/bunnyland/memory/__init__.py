"""Private notes and memory (spec 15): focus-lane verbs over a pluggable store."""

from __future__ import annotations

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


def install_memory(actor: WorldActor, store: MemoryStore | None = None) -> MemoryStore:
    """Register the take-note and remember handlers on an actor (spec 21 preview).

    Returns the store so callers can inspect/share it. Defaults to an in-memory store.
    """
    store = store or InMemoryStore()
    actor.memory_store = store
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
    "MemoryStore",
    "ReflectHandler",
    "ReflectionLoopConsequence",
    "RememberHandler",
    "TakeNoteHandler",
    "install_memory",
    "quarantine_after_epoch",
]
