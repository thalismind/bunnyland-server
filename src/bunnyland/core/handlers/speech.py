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
from dataclasses import replace
from typing import Any

from relics import EntityId

from ..commands import SpeechIntent, SubmittedCommand
from ..components import (
    CharacterComponent,
    ConversationComponent,
    DeadComponent,
    IdentityComponent,
    SleepingComponent,
    SuspendedComponent,
)
from ..ecs import container_of, contents, parse_entity_id, replace_component, spawn_entity
from ..edges import ConversationParticipant
from ..events import (
    ConversationEndedEvent,
    ConversationLineEvent,
    ConversationStartedEvent,
    EventVisibility,
    SpeechSaidEvent,
    SpeechToldEvent,
)
from .base import HandlerContext, HandlerResult, ok, rejected

DEFAULT_CONVERSATION_TIMEOUT_SECONDS = 10 * 60


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


def _ordered_participants(conversation) -> tuple[EntityId, ...]:
    relationships = conversation.get_relationships(ConversationParticipant)
    ordered = sorted(relationships, key=lambda item: item[0].order)
    return tuple(target_id for _edge, target_id in ordered)


def _current_participant(
    participants: tuple[EntityId, ...],
    component: ConversationComponent,
) -> EntityId | None:
    if not participants:
        return None
    return participants[component.active_turn % len(participants)]


def _participant_payload_ids(payload: Mapping[str, Any]) -> list[Any]:
    raw = payload.get("participant_ids", payload.get("target_ids", payload.get("target_id")))
    if raw is None:
        return []
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return [raw]


def _end_conversation(
    ctx: HandlerContext,
    conversation,
    component: ConversationComponent,
    participants: tuple[EntityId, ...],
    reason: str,
) -> HandlerResult:
    replace_component(
        conversation,
        replace(component, ended=True, ended_reason=reason),
    )
    room_id = None
    if participants and ctx.world.has_entity(participants[0]):
        room_id = container_of(ctx.entity(participants[0]))
    return ok(
        ConversationEndedEvent(
            **ctx.event_base(
                visibility=EventVisibility.ROOM,
                actor_id=str(participants[0]) if participants else None,
                room_id=str(room_id) if room_id is not None else None,
                target_ids=tuple(str(participant) for participant in participants),
                conversation_id=str(conversation.id),
                participant_ids=tuple(str(participant) for participant in participants),
                reason=reason,
            )
        )
    )


def _conversation_for_command(ctx: HandlerContext, raw_id: object):
    conversation_id = parse_entity_id(raw_id)
    if conversation_id is None:
        return None, None, None, rejected("invalid conversation id")
    if not ctx.world.has_entity(conversation_id):
        return None, None, None, rejected("conversation does not exist")
    conversation = ctx.entity(conversation_id)
    if not conversation.has_component(ConversationComponent):
        return None, None, None, rejected("conversation is the wrong kind")
    return conversation_id, conversation, conversation.get_component(ConversationComponent), None


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
                str(hearer) for hearer in _audience(ctx, room_id, speaker_id) if hearer != target_id
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


class StartConversationHandler:
    command_type = "start-conversation"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        speaker_id = parse_entity_id(command.character_id)
        if speaker_id is None:
            return rejected("invalid character id")
        if not ctx.world.has_entity(speaker_id):
            return rejected("speaker does not exist")
        speaker = ctx.entity(speaker_id)
        if not _is_active_awake(speaker):
            return rejected("speaker cannot start conversation")
        room_id = container_of(speaker)
        if room_id is None:
            return rejected("speaker is not in a room")

        participant_ids = [speaker_id]
        for raw_id in _participant_payload_ids(payload):
            target_id = parse_entity_id(raw_id)
            if target_id is None:
                return rejected("invalid participant id")
            if not ctx.world.has_entity(target_id):
                return rejected("participant does not exist")
            if target_id == speaker_id or target_id in participant_ids:
                continue
            target = ctx.entity(target_id)
            if container_of(target) != room_id:
                return rejected("participant is not present")
            if not _is_active_awake(target):
                return rejected("participant cannot hear you")
            participant_ids.append(target_id)
        if len(participant_ids) < 2:
            return rejected("conversation needs another participant")

        raw_timeout = payload.get("timeout_seconds", DEFAULT_CONVERSATION_TIMEOUT_SECONDS)
        try:
            timeout_seconds = int(float(raw_timeout))
        except (TypeError, ValueError):
            timeout_seconds = DEFAULT_CONVERSATION_TIMEOUT_SECONDS
        timeout_seconds = max(1, timeout_seconds)
        topic = str(payload.get("topic", "")).strip()
        conversation = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=topic or "conversation", kind="conversation"),
                ConversationComponent(
                    topic=topic,
                    active_turn=0,
                    started_at_epoch=ctx.epoch,
                    expires_at_epoch=ctx.epoch + timeout_seconds,
                ),
            ],
        )
        for order, participant_id in enumerate(participant_ids):
            conversation.add_relationship(ConversationParticipant(order=order), participant_id)

        return ok(
            ConversationStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(speaker_id),
                    room_id=str(room_id),
                    target_ids=tuple(str(participant) for participant in participant_ids[1:]),
                    conversation_id=str(conversation.id),
                    participant_ids=tuple(str(participant) for participant in participant_ids),
                    topic=topic,
                    active_participant_id=str(speaker_id),
                    expires_at_epoch=ctx.epoch + timeout_seconds,
                )
            )
        )


class ConversationLineHandler:
    command_type = "conversation-line"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        speaker_id = parse_entity_id(command.character_id)
        conversation_id, conversation, component, error = _conversation_for_command(
            ctx,
            payload.get("conversation_id"),
        )
        if speaker_id is None:
            return rejected("invalid character id")
        if not ctx.world.has_entity(speaker_id):
            return rejected("speaker does not exist")
        if error is not None:
            return error
        assert conversation_id is not None and conversation is not None and component is not None

        participants = _ordered_participants(conversation)
        if speaker_id not in participants:
            return rejected("speaker is not a conversation participant")
        if component.ended:
            return rejected("conversation has ended")
        if ctx.epoch >= component.expires_at_epoch:
            return _end_conversation(ctx, conversation, component, participants, "timeout")
        if _current_participant(participants, component) != speaker_id:
            return rejected("not your conversation turn")

        text = str(payload.get("text", "")).strip()
        if not text:
            return rejected("nothing to say")
        room_id = container_of(ctx.entity(speaker_id))
        if room_id is None:
            return rejected("speaker is not in a room")

        author = _parse_intent(payload.get("intent"))
        inferred = infer_intent(text)
        final = author or inferred
        approach = str(payload.get("approach", "")).strip() or None
        next_turn = component.active_turn + 1
        updated = replace(component, active_turn=next_turn)
        replace_component(conversation, updated)
        next_participant = _current_participant(participants, updated)
        targets = tuple(
            str(participant) for participant in participants if participant != speaker_id
        )

        return ok(
            ConversationLineEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(speaker_id),
                    room_id=str(room_id),
                    target_ids=targets,
                    conversation_id=str(conversation_id),
                    speaker_id=str(speaker_id),
                    text=text,
                    turn_index=component.active_turn,
                    next_participant_id=str(next_participant) if next_participant else None,
                    author_intent=author.value if author else None,
                    inferred_intent=inferred.value,
                    final_interpretation=final.value,
                    approach=approach,
                )
            ),
            SpeechSaidEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(speaker_id),
                    room_id=str(room_id),
                    target_ids=targets,
                    text=text,
                    author_intent=author.value if author else None,
                    inferred_intent=inferred.value,
                    final_interpretation=final.value,
                    approach=approach,
                )
            ),
        )


class EndConversationHandler:
    command_type = "end-conversation"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        speaker_id = parse_entity_id(command.character_id)
        _conversation_id, conversation, component, error = _conversation_for_command(
            ctx,
            payload.get("conversation_id"),
        )
        if speaker_id is None:
            return rejected("invalid character id")
        if not ctx.world.has_entity(speaker_id):
            return rejected("speaker does not exist")
        if error is not None:
            return error
        assert conversation is not None and component is not None

        participants = _ordered_participants(conversation)
        if speaker_id not in participants:
            return rejected("speaker is not a conversation participant")
        if component.ended:
            return rejected("conversation has ended")
        reason = str(payload.get("reason", "")).strip() or "ended"
        return _end_conversation(ctx, conversation, component, participants, reason)


__all__ = [
    "ConversationLineHandler",
    "EndConversationHandler",
    "SayHandler",
    "StartConversationHandler",
    "TellHandler",
    "infer_intent",
]
