"""Focus-lane memory verbs: take note and remember/search (spec 13.9, 13.10, 15).

These are the first focus-lane commands: they spend Focus, are private, and never
create a room-visible event. Notes go to the character's private collection named by its
``MemoryProfileComponent``. Search results are returned on a private event for the
controller layer to deliver (by DM for humans).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..core.commands import SubmittedCommand
from ..core.components import MemoryProfileComponent
from ..core.ecs import parse_entity_id
from ..core.events import NotesSearchedEvent, NoteTakenEvent
from ..core.handlers.base import HandlerContext, HandlerResult, ok, rejected
from .store import MemoryStore


def _collection(ctx: HandlerContext, character_id) -> str | None:
    character = ctx.entity(character_id)
    if not character.has_component(MemoryProfileComponent):
        return None
    return character.get_component(MemoryProfileComponent).vector_collection


class TakeNoteHandler:
    command_type = "take-note"

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id = parse_entity_id(command.character_id)
        text = str(payload.get("text", "")).strip()
        if character_id is None:
            return rejected("invalid character id")
        if not text:
            return rejected("nothing to note")
        collection = _collection(ctx, character_id)
        if collection is None:
            return rejected("character has no memory profile")

        tags = tuple(payload.get("tags", ()) or ())
        entry = self.store.add(
            collection, text=text, tags=tags, created_at_epoch=ctx.epoch, source="manual"
        )
        return ok(
            NoteTakenEvent(
                **ctx.event_base(
                    visibility="private",
                    actor_id=command.character_id,
                    note_id=entry.id,
                    text=text,
                )
            )
        )


class RememberHandler:
    command_type = "remember"

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        collection = _collection(ctx, character_id)
        if collection is None:
            return rejected("character has no memory profile")

        query = payload.get("query")
        mode = str(payload.get("mode", "recent"))
        limit = int(payload.get("limit", 5))
        results = self.store.search(collection, query=query, mode=mode, limit=limit)
        return ok(
            NotesSearchedEvent(
                **ctx.event_base(
                    visibility="private",
                    actor_id=command.character_id,
                    query=query,
                    mode=mode,
                    results=tuple(entry.text for entry in results),
                )
            )
        )


__all__ = ["RememberHandler", "TakeNoteHandler"]
