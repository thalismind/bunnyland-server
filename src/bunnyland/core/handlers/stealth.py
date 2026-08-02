"""Core stealth action and reusable state transition helper."""

from __future__ import annotations

from dataclasses import replace

from relics import Entity, EntityId

from ..commands import SubmittedCommand
from ..components import StealthComponent
from ..ecs import container_of
from ..edges import DetectedStealth
from ..events import EventVisibility, StealthChangedEvent
from ..mutations import AddComponent, MutationOperation, MutationPlan, RemoveEdge, SetComponent
from ..stealth import is_hidden
from .base import HandlerContext, HandlerResult, planned, require_character


def stealth_change_operations(
    character: Entity,
    *,
    epoch: int,
    hiding: bool,
) -> tuple[MutationOperation, ...]:
    """Build one canonical hide/unhide transition and invalidate old detections."""

    if character.has_component(StealthComponent):
        current = character.get_component(StealthComponent)
        if is_hidden(character) == hiding:
            return ()
        updated = replace(
            current,
            hiding=hiding,
            visibility_level=(
                min(current.visibility_level, current.hidden_threshold) if hiding else 1.0
            ),
            since_epoch=epoch,
        )
        state_operation: MutationOperation = SetComponent(character.id, updated)
    else:
        state_operation = AddComponent(
            character.id,
            StealthComponent(
                visibility_level=0.0 if hiding else 1.0,
                hiding=hiding,
                since_epoch=epoch,
            ),
        )

    invalidations = tuple(
        RemoveEdge(observer_id, character.id, DetectedStealth)
        for observer_id, _edge in character.get_incoming_relationships(DetectedStealth)
    )
    return (state_operation, *invalidations)


def stealth_changed_event(
    ctx: HandlerContext,
    character_id: EntityId,
    *,
    hiding: bool,
) -> StealthChangedEvent:
    room_id = container_of(ctx.entity(character_id))
    return StealthChangedEvent(
        **ctx.event_base(
            visibility=EventVisibility.PRIVATE,
            actor_id=str(character_id),
            room_id=str(room_id) if room_id is not None else None,
            character_id=str(character_id),
            hiding=hiding,
        )
    )


class SneakHandler:
    command_type = "sneak"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        assert character_id is not None and character is not None
        hiding = not is_hidden(character)
        return planned(
            MutationPlan(stealth_change_operations(character, epoch=ctx.epoch, hiding=hiding)),
            stealth_changed_event(ctx, character_id, hiding=hiding),
        )


__all__ = ["SneakHandler", "stealth_change_operations", "stealth_changed_event"]
