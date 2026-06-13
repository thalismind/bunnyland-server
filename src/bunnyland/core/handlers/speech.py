"""Speech verbs: say (room-scoped) and tell (directed) (spec 13.8, 14).

Social meaning flows through dialogue, not separate verbs: an author may declare a
``SpeechIntent``; otherwise one is inferred from the text. Both author and inferred
intent are recorded so misinterpretation (and deliberately absurd tone) is visible.

Visibility (spec 14.4, 19): ``say`` is heard by active, awake characters in the room.
``tell`` is directed to one character by default; callers can mark it audible to record
same-room overhearers without changing the direct target.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from relics import EntityId

from ..commands import SpeechIntent, SubmittedCommand
from ..components import (
    CharacterComponent,
    DeadComponent,
    SleepingComponent,
    SuspendedComponent,
)
from ..ecs import container_of, contents, parse_entity_id
from ..events import EventVisibility, SpeechSaidEvent, SpeechToldEvent
from .base import HandlerContext, HandlerResult, ok, rejected


def infer_intent(text: str) -> SpeechIntent:
    """A small keyword heuristic for MVP. Replaced/augmented by LLM inference later."""
    lowered = text.lower().strip()
    if not lowered:
        return SpeechIntent.NEUTRAL
    if "?" in lowered:
        return SpeechIntent.QUESTION
    if any(word in lowered for word in ("sorry", "apolog", "forgive")):
        return SpeechIntent.APOLOGY
    if any(word in lowered for word in ("please", "could you", "would you")):
        return SpeechIntent.REQUEST
    if any(word in lowered for word in ("thank", "well done", "great job", "beautiful")):
        return SpeechIntent.PRAISE
    if any(word in lowered for word in ("i'll ", "i will ", "i promise")):
        return SpeechIntent.PROMISE
    return SpeechIntent.NEUTRAL


def _parse_intent(raw: Any) -> SpeechIntent | None:
    if raw is None:
        return None
    if isinstance(raw, SpeechIntent):
        return raw
    try:
        return SpeechIntent(str(raw))
    except ValueError:
        return None


def _is_active_awake(entity) -> bool:
    return (
        entity.has_component(CharacterComponent)
        and not entity.has_component(SuspendedComponent)
        and not entity.has_component(DeadComponent)
        and not entity.has_component(SleepingComponent)
    )


def _audience(ctx: HandlerContext, room_id: EntityId, speaker_id: EntityId) -> list[EntityId]:
    """Active, awake characters in the room other than the speaker."""
    hearers: list[EntityId] = []
    for occupant_id in contents(ctx.entity(room_id)):
        if occupant_id == speaker_id:
            continue
        occupant = ctx.entity(occupant_id)
        if _is_active_awake(occupant):
            hearers.append(occupant_id)
    return hearers


class SayHandler:
    command_type = "say"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        speaker_id = parse_entity_id(command.character_id)
        text = str(payload.get("text", "")).strip()
        if speaker_id is None:
            return rejected("invalid character id")
        if not ctx.world.has_entity(speaker_id):
            return rejected("speaker does not exist")
        if not text:
            return rejected("nothing to say")

        room_id = container_of(ctx.entity(speaker_id))
        if room_id is None:
            return rejected("speaker is not in a room")

        author = _parse_intent(payload.get("intent"))
        inferred = infer_intent(text)
        final = author or inferred
        approach = str(payload.get("approach", "")).strip() or None
        hearers = _audience(ctx, room_id, speaker_id)

        return ok(
            SpeechSaidEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(speaker_id),
                    room_id=str(room_id),
                    target_ids=tuple(str(h) for h in hearers),
                    text=text,
                    author_intent=author.value if author else None,
                    inferred_intent=inferred.value,
                    final_interpretation=final.value,
                    approach=approach,
                )
            )
        )


class TellHandler:
    command_type = "tell"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        speaker_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(payload.get("target_id"))
        text = str(payload.get("text", "")).strip()
        if speaker_id is None or target_id is None:
            return rejected("invalid speaker or target id")
        if not ctx.world.has_entity(speaker_id):
            return rejected("speaker does not exist")
        if not text:
            return rejected("nothing to say")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        room_id = container_of(ctx.entity(speaker_id))
        if room_id is None or container_of(ctx.entity(target_id)) != room_id:
            return rejected("target is not present")
        if not _is_active_awake(ctx.entity(target_id)):
            return rejected("target cannot hear you")

        author = _parse_intent(payload.get("intent"))
        inferred = infer_intent(text)
        final = author or inferred
        approach = str(payload.get("approach", "")).strip() or None
        overhearers: tuple[str, ...] = ()
        if bool(payload.get("audible", False)):
            overhearers = tuple(
                str(hearer)
                for hearer in _audience(ctx, room_id, speaker_id)
                if hearer != target_id
            )

        return ok(
            SpeechToldEvent(
                **ctx.event_base(
                    visibility=EventVisibility.DIRECTED,
                    actor_id=str(speaker_id),
                    room_id=str(room_id),
                    target_ids=(str(target_id),),
                    text=text,
                    author_intent=author.value if author else None,
                    inferred_intent=inferred.value,
                    final_interpretation=final.value,
                    approach=approach,
                    overhearer_ids=overhearers,
                )
            )
        )


__all__ = ["SayHandler", "TellHandler", "infer_intent"]
