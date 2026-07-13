"""Lifecycle / rest verbs: sleep, wake, wait (spec 13.1).

These change a character's participation state. ``sleep`` adds the ``SleepingComponent``
marker; ``wake`` removes it; ``wait`` yields the turn with no effect. Gating of who may
act while asleep/downed lives in the world actor, not here.
"""

from __future__ import annotations

from ..commands import SubmittedCommand
from ..components import SleepingComponent
from ..mutations import MutationPlan, RemoveComponent, SetComponent
from .base import HandlerContext, HandlerResult, planned, rejected, require_character


class SleepHandler:
    command_type = "sleep"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        if character.has_component(SleepingComponent):
            return rejected("already asleep")
        return planned(
            MutationPlan(
                (SetComponent(character.id, SleepingComponent(started_at_epoch=ctx.epoch)),)
            ),
            ctx=ctx,
        )


class WakeHandler:
    command_type = "wake"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        if not character.has_component(SleepingComponent):
            return rejected("not asleep")
        return planned(
            MutationPlan((RemoveComponent(character.id, SleepingComponent),)),
            ctx=ctx,
        )


class WaitHandler:
    """Yield the turn. No state change; the point cost (if any) is set by the submitter."""

    command_type = "wait"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _, _, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        return planned(MutationPlan(), ctx=ctx)


__all__ = ["SleepHandler", "WaitHandler", "WakeHandler"]
