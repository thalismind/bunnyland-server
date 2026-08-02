"""Movement verb (spec 13.3)."""

from __future__ import annotations

from collections.abc import Mapping

from relics import EntityId

from ...projections.room_summary import build_room_facts, render_summary
from ..commands import SubmittedCommand
from ..components import NoiseComponent
from ..ecs import container_of, parse_entity_id
from ..edges import ContainmentMode, Contains, ExitTo
from ..events import ActorMovedEvent
from ..mutations import AddEdge, AddEntity, MutationOperation, MutationPlan, RemoveEdge
from ..stealth import is_hidden
from .base import HandlerContext, HandlerResult, planned, rejected, require_character
from .stealth import stealth_change_operations, stealth_changed_event

QUIET_MOVEMENT_NOISE = 0.25
LOUD_REVEAL_THRESHOLD = 1.0


class MoveHandler:
    """Move a character along an ``ExitTo`` edge.

    Transfers the character's ``Contains`` parent from the current room to the
    destination room.
    """

    command_type = "move"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, object] = command.payload
        character_id, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        current_room_id = container_of(character)
        if current_room_id is None:
            return rejected("character is not in a room")

        current_room = ctx.entity(current_room_id)
        exits = current_room.get_relationships(ExitTo)

        direction = payload.get("direction")
        target_exit_id = parse_entity_id(payload.get("exit_id"))

        destination_id: EntityId | None = None
        chosen_direction: str | None = None
        for edge, target_id in exits:
            if target_exit_id is not None and target_id == target_exit_id:
                destination_id, chosen_direction = target_id, edge.direction
                break
            if direction is not None and edge.direction == direction:
                destination_id, chosen_direction = target_id, edge.direction
                break

        if destination_id is None:
            return rejected("no matching exit")
        if not ctx.world.has_entity(destination_id):
            return rejected("destination does not exist")

        hidden = is_hidden(character)
        explicit_noise = "noise" in payload
        noise = float(payload.get("noise", QUIET_MOVEMENT_NOISE if hidden else 1.0))
        reveals = hidden and explicit_noise and noise >= LOUD_REVEAL_THRESHOLD
        operations: list[MutationOperation] = [
            RemoveEdge(current_room_id, character_id, Contains),
            AddEdge(
                destination_id,
                character_id,
                Contains(mode=ContainmentMode.ROOM_CONTENT),
            ),
            AddEntity(
                (
                    NoiseComponent(
                        loudness=noise,
                        text="movement",
                        source_entity_id=str(character_id),
                        room_id=str(destination_id),
                        created_at_epoch=ctx.epoch,
                        expires_at_epoch=ctx.epoch + 60,
                    ),
                )
            ),
        ]
        if reveals:
            operations.extend(stealth_change_operations(character, epoch=ctx.epoch, hiding=False))
        plan = MutationPlan(tuple(operations))

        events = [
            lambda: ActorMovedEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    room_id=str(destination_id),
                    from_room_id=str(current_room_id),
                    to_room_id=str(destination_id),
                    direction=chosen_direction,
                    arrival_summary=render_summary(build_room_facts(ctx.world, destination_id)),
                )
            )
        ]
        if reveals:
            events.append(lambda: stealth_changed_event(ctx, character_id, hiding=False))
        return planned(plan, *events)


__all__ = ["MoveHandler"]
