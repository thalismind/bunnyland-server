"""Lifecycle / recovery verbs: rest, sleep, wake, and wait."""

from __future__ import annotations

import math
from uuid import uuid4

from ..commands import SubmittedCommand
from ..components import RestingComponent, SleepingComponent
from ..events import EventVisibility, RestStartedEvent, SleepStartedEvent
from ..mutations import MutationPlan, SetComponent
from ..recovery import (
    RecoveryEndReason,
    end_rest_operations,
    end_sleep_operations,
    rest_ended_event,
    sleep_session_id,
    woke_event,
)
from .base import HandlerContext, HandlerResult, planned, rejected, require_character


def _duration(raw: object) -> tuple[float | None, HandlerResult | None]:
    if raw is None:
        return None, None
    if isinstance(raw, bool):
        return None, rejected("duration must be a positive finite number")
    try:
        duration = float(raw)
    except (TypeError, ValueError):
        return None, rejected("duration must be a positive finite number")
    if not math.isfinite(duration) or duration <= 0:
        return None, rejected("duration must be a positive finite number")
    return duration, None


class RestHandler:
    command_type = "rest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        if character.has_component(SleepingComponent):
            return rejected("character is asleep")
        if character.has_component(RestingComponent):
            return rejected("already resting")
        duration, error = _duration(command.payload.get("duration_seconds"))
        if error is not None:
            return error
        session_id = uuid4().hex
        rest = RestingComponent(
            started_at_epoch=ctx.epoch,
            until_epoch=ctx.epoch + duration if duration is not None else None,
            session_id=session_id,
        )
        return planned(
            MutationPlan((SetComponent(character.id, rest),)),
            RestStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character.id),
                    session_id=session_id,
                    until_epoch=rest.until_epoch,
                )
            ),
        )


class SleepHandler:
    command_type = "sleep"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        if character.has_component(SleepingComponent):
            return rejected("already asleep")
        duration, error = _duration(command.payload.get("duration_seconds"))
        if error is not None:
            return error
        sleeping = SleepingComponent(
            started_at_epoch=ctx.epoch,
            until_epoch=ctx.epoch + duration if duration is not None else None,
        )
        operations = []
        events = []
        if character.has_component(RestingComponent):
            rest = character.get_component(RestingComponent)
            operations.extend(end_rest_operations(ctx.world, character, rest, epoch=ctx.epoch))
            events.append(
                rest_ended_event(ctx.epoch, character, rest, RecoveryEndReason.ACTION)
            )
        operations.append(SetComponent(character.id, sleeping))
        events.append(
            SleepStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character.id),
                    session_id=sleep_session_id(character.id, sleeping),
                    until_epoch=sleeping.until_epoch,
                )
            )
        )
        return planned(MutationPlan(tuple(operations)), *events)


class WakeHandler:
    command_type = "wake"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        if not character.has_component(SleepingComponent):
            return rejected("not asleep")
        sleeping = character.get_component(SleepingComponent)
        return planned(
            MutationPlan(
                end_sleep_operations(ctx.world, character, sleeping, epoch=ctx.epoch)
            ),
            woke_event(ctx.epoch, character, sleeping, RecoveryEndReason.EXPLICIT),
        )


class WaitHandler:
    """Yield the turn. No state change; the point cost (if any) is set by the submitter."""

    command_type = "wait"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _, _, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        return planned(MutationPlan())


__all__ = ["RestHandler", "SleepHandler", "WaitHandler", "WakeHandler"]
