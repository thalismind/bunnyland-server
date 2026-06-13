"""Lifecycle / rest verbs: sleep, wake, wait (spec 13.1).

These change a character's participation state. ``sleep`` adds the ``SleepingComponent``
marker; ``wake`` removes it; ``wait`` yields the turn with no effect. Gating of who may
act while asleep/downed lives in the world actor, not here.
"""

from __future__ import annotations

from relics import EntityId

from ..commands import SubmittedCommand
from ..components import SleepingComponent
from ..ecs import parse_entity_id, replace_component
from .base import HandlerContext, HandlerResult, ok, rejected


class SleepHandler:
    command_type = "sleep"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id: EntityId | None = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        if not ctx.world.has_entity(character_id):
            return rejected("character does not exist")
        character = ctx.entity(character_id)
        if character.has_component(SleepingComponent):
            return rejected("already asleep")
        replace_component(character, SleepingComponent(started_at_epoch=ctx.epoch))
        return ok()


class WakeHandler:
    command_type = "wake"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        if not ctx.world.has_entity(character_id):
            return rejected("character does not exist")
        character = ctx.entity(character_id)
        if not character.has_component(SleepingComponent):
            return rejected("not asleep")
        character.remove_component(SleepingComponent)
        return ok()


class WaitHandler:
    """Yield the turn. No state change; the point cost (if any) is set by the submitter."""

    command_type = "wait"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        if not ctx.world.has_entity(character_id):
            return rejected("character does not exist")
        return ok()


__all__ = ["SleepHandler", "WaitHandler", "WakeHandler"]
