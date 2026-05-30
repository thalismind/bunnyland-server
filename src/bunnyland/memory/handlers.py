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
from ..core.ecs import parse_entity_id, replace_component
from ..core.events import NotesSearchedEvent, NoteTakenEvent, ReflectionCreatedEvent
from ..core.handlers.base import HandlerContext, HandlerResult, ok, rejected
from .store import MemoryStore


def _collection(ctx: HandlerContext, character_id, payload: Mapping[str, Any]) -> tuple[str, str]:
    character = ctx.entity(character_id)
    if not character.has_component(MemoryProfileComponent):
        raise ValueError("character has no memory profile")
    profile = character.get_component(MemoryProfileComponent)
    scope = str(payload.get("scope", "private")).strip().lower()
    if scope == "private":
        return profile.vector_collection, "private"
    if scope != "shared":
        raise ValueError("memory scope must be private or shared")

    collection = str(payload.get("collection", "")).strip()
    if not collection and len(profile.shared_collections) == 1:
        collection = profile.shared_collections[0]
    if not collection:
        raise ValueError("shared collection is required")
    if collection not in profile.shared_collections:
        raise ValueError("shared collection is not available")
    return collection, "shared"


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
        try:
            collection, scope = _collection(ctx, character_id, payload)
        except ValueError as exc:
            return rejected(str(exc))

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
                    scope=scope,
                    collection=collection,
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
        try:
            collection, scope = _collection(ctx, character_id, payload)
        except ValueError as exc:
            return rejected(str(exc))

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
                    scope=scope,
                    collection=collection,
                )
            )
        )


class ReflectHandler:
    command_type = "reflect"

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        if not character.has_component(MemoryProfileComponent):
            return rejected("character has no memory profile")
        profile = character.get_component(MemoryProfileComponent)

        limit = int(payload.get("limit", 5))
        if limit <= 0:
            return rejected("reflection limit must be positive")
        entries = self.store.search(
            profile.vector_collection,
            query=payload.get("query"),
            mode=str(payload.get("mode", "recent")),
            limit=limit,
        )
        explicit = str(payload.get("text", "")).strip()
        if explicit:
            text = explicit
        elif entries:
            text = "Reflection: " + " ".join(entry.text for entry in entries)
        else:
            return rejected("nothing to reflect on")

        entry = self.store.add(
            profile.vector_collection,
            text=text,
            tags=("reflection",),
            created_at_epoch=ctx.epoch,
            source="reflection",
        )
        replace_component(
            character,
            MemoryProfileComponent(
                vector_collection=profile.vector_collection,
                shared_collections=profile.shared_collections,
                last_event_seen_id=profile.last_event_seen_id,
                last_reflection_epoch=ctx.epoch,
            ),
        )
        return ok(
            ReflectionCreatedEvent(
                **ctx.event_base(
                    visibility="private",
                    actor_id=command.character_id,
                    note_id=entry.id,
                    text=text,
                    source_note_ids=tuple(entry.id for entry in entries),
                )
            )
        )


__all__ = ["ReflectHandler", "RememberHandler", "TakeNoteHandler"]
