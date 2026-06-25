"""Focus-lane memory verbs: take note and remember/search (spec 13.9, 13.10, 15).

These are the first focus-lane commands: they spend Focus, are private, and never
create a room-visible event. Notes go to the character's private collection named by its
``MemoryProfileComponent``. Search results are returned on a private event for the
controller layer to deliver (by DM for humans).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from relics import World

from ..core.commands import CommandCost, Lane, SubmittedCommand, build_submitted_command
from ..core.components import CharacterComponent, MemoryProfileComponent
from ..core.ecs import entity_name, parse_entity_id, replace_component
from ..core.events import (
    ConversationLineEvent,
    DomainEvent,
    NoteForgottenEvent,
    NotesSearchedEvent,
    NoteTakenEvent,
    ReflectionCreatedEvent,
)
from ..core.handlers.base import HandlerContext, HandlerResult, ok, rejected
from .store import MemoryStore, normalize_tags

DEFAULT_REFLECTION_INTERVAL_SECONDS = 24 * 3600
DEFAULT_REFLECTION_MIN_ENTRIES = 3
DEFAULT_REFLECTION_LIMIT = 5
DEFAULT_REFLECTION_SCAN_LIMIT = 20


def _collection(ctx: HandlerContext, character_id, payload: Mapping[str, Any]) -> tuple[str, str]:
    character = ctx.entity(character_id)
    if not character.has_component(MemoryProfileComponent):
        raise ValueError("character has no memory profile")
    profile = character.get_component(MemoryProfileComponent)
    raw_scope = payload.get("scope")
    scope = str(raw_scope).strip().lower() if raw_scope is not None else ""
    if not scope:
        scope = "private"
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
        if not ctx.world.has_entity(character_id):
            return rejected("character does not exist")
        if not text:
            return rejected("nothing to note")
        try:
            collection, scope = _collection(ctx, character_id, payload)
        except ValueError as exc:
            return rejected(str(exc))

        tags = normalize_tags(payload.get("tags", ()) or ())
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
        if not ctx.world.has_entity(character_id):
            return rejected("character does not exist")
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
                    note_ids=tuple(entry.id for entry in results),
                    scope=scope,
                    collection=collection,
                )
            )
        )


class ForgetHandler:
    command_type = "forget"

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id = parse_entity_id(command.character_id)
        note_id = str(payload.get("note_id", "")).strip()
        if character_id is None:
            return rejected("invalid character id")
        if not ctx.world.has_entity(character_id):
            return rejected("character does not exist")
        if not note_id:
            return rejected("note id is required")
        try:
            collection, scope = _collection(ctx, character_id, payload)
        except ValueError as exc:
            return rejected(str(exc))
        if not self.store.delete(collection, note_id):
            return rejected("note not found")
        return ok(
            NoteForgottenEvent(
                **ctx.event_base(
                    visibility="private",
                    actor_id=command.character_id,
                    note_id=note_id,
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
        if not ctx.world.has_entity(character_id):
            return rejected("character does not exist")
        character = ctx.entity(character_id)
        if not character.has_component(MemoryProfileComponent):
            return rejected("character has no memory profile")
        profile = character.get_component(MemoryProfileComponent)

        limit = int(payload.get("limit", 5))
        if limit <= 0:
            return rejected("reflection limit must be positive")
        entries = _reflection_source_entries(
            self.store,
            profile.vector_collection,
            query=payload.get("query"),
            mode=str(payload.get("mode", "recent")),
            limit=limit,
            since_epoch=_optional_int(payload.get("since_epoch")),
            exclude_sources=tuple(payload.get("exclude_sources", ()) or ()),
            scan_limit=int(payload.get("scan_limit", limit)),
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


class ReflectionLoopConsequence:
    """Periodically synthesize recent private memories into durable reflections."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        interval_seconds: int = DEFAULT_REFLECTION_INTERVAL_SECONDS,
        min_entries: int = DEFAULT_REFLECTION_MIN_ENTRIES,
        limit: int = DEFAULT_REFLECTION_LIMIT,
        scan_limit: int = DEFAULT_REFLECTION_SCAN_LIMIT,
    ) -> None:
        self.store = store
        self.interval_seconds = max(0, interval_seconds)
        self.min_entries = max(1, min_entries)
        self.limit = max(1, limit)
        self.scan_limit = max(self.limit, scan_limit)
        self._handler = ReflectHandler(store)

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = world.query().with_all([CharacterComponent, MemoryProfileComponent])
        for character in query.execute_entities():
            profile = character.get_component(MemoryProfileComponent)
            if epoch - profile.last_reflection_epoch < self.interval_seconds:
                continue
            since_epoch = profile.last_reflection_epoch if profile.last_reflection_epoch else None
            entries = _reflection_source_entries(
                self.store,
                profile.vector_collection,
                mode="recent",
                limit=self.limit,
                since_epoch=since_epoch,
                exclude_sources=("reflection",),
                scan_limit=self.scan_limit,
            )
            if len(entries) < self.min_entries:
                continue
            command = build_submitted_command(
                character_id=str(character.id),
                controller_id=str(character.id),
                controller_generation=0,
                command_type="reflect",
                cost=CommandCost(focus=1),
                lane=Lane.FOCUS,
                payload={
                    "mode": "recent",
                    "limit": self.limit,
                    "scan_limit": self.scan_limit,
                    "since_epoch": since_epoch,
                    "exclude_sources": ("reflection",),
                },
                submitted_at_epoch=epoch,
            )
            result = self._handler.execute(HandlerContext(world, epoch), command)
            if result.ok:
                events.extend(result.events)
        return events


class ConversationMemoryReactor:
    """Store structured conversation lines in each participant's private memory."""

    def __init__(self, world: World, store: MemoryStore) -> None:
        self.world = world
        self.store = store

    def subscribe(self, bus) -> None:
        bus.subscribe(ConversationLineEvent, self._on_conversation_line)

    def _on_conversation_line(self, event: ConversationLineEvent) -> None:
        speaker_id = parse_entity_id(event.speaker_id)
        if speaker_id is None or not self.world.has_entity(speaker_id):
            return
        # speaker_id passed the has_entity guard above, so it is always retained here —
        # `participants` therefore can never be empty and needs no further guard.
        participants = tuple(
            participant_id
            for participant_id in (
                speaker_id,
                *(parse_entity_id(raw) for raw in event.target_ids),
            )
            if participant_id is not None and self.world.has_entity(participant_id)
        )
        speaker = self.world.get_entity(speaker_id)
        speaker_name = entity_name(speaker)
        listener_names = tuple(
            entity_name(self.world.get_entity(participant_id))
            for participant_id in participants
            if participant_id != speaker_id
        )
        heard_by = ", ".join(listener_names) if listener_names else "no one else"
        interpretation = event.final_interpretation or event.inferred_intent or "neutral"
        approach = f"; approach {event.approach}" if event.approach else ""
        text = (
            f"Conversation {event.conversation_id}: {speaker_name} said to {heard_by}: "
            f'"{event.text}" (landed as {interpretation}{approach}).'
        )
        tags = tuple(
            tag
            for tag in (
                "conversation",
                event.conversation_id,
                f"speaker:{speaker_name.lower()}",
                f"intent:{interpretation}",
            )
            if tag
        )
        for participant_id in dict.fromkeys(participants):
            participant = self.world.get_entity(participant_id)
            if not participant.has_component(MemoryProfileComponent):
                continue
            profile = participant.get_component(MemoryProfileComponent)
            self.store.add(
                profile.vector_collection,
                text=text,
                tags=tags,
                created_at_epoch=event.world_epoch,
                source="conversation",
            )


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _reflection_source_entries(
    store: MemoryStore,
    collection: str,
    *,
    query: str | None = None,
    mode: str = "recent",
    limit: int = 5,
    since_epoch: int | None = None,
    exclude_sources: tuple[str, ...] = (),
    scan_limit: int | None = None,
):
    scan = max(limit, scan_limit or limit)
    excluded = set(exclude_sources)
    entries = store.search(collection, query=query, mode=mode, limit=scan)
    filtered = [
        entry
        for entry in entries
        if entry.source not in excluded
        and (since_epoch is None or entry.created_at_epoch > since_epoch)
    ]
    return filtered[:limit]


__all__ = [
    "ConversationMemoryReactor",
    "ForgetHandler",
    "ReflectHandler",
    "ReflectionLoopConsequence",
    "RememberHandler",
    "TakeNoteHandler",
]
