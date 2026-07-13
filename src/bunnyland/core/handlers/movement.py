"""Movement verb (spec 13.3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from relics import EntityId

from ...projections.room_summary import build_room_facts, render_summary
from ..commands import SubmittedCommand
from ..components import NoiseComponent
from ..ecs import container_of, parse_entity_id
from ..edges import ContainmentMode, Contains, ExitTo
from ..events import ActorMovedEvent
from ..mutations import AddEdge, AddEntity, MutationPlan, RemoveEdge
from .base import HandlerContext, HandlerResult, planned, rejected, require_character


class MoveHandler:
    """Move a character along an ``ExitTo`` edge.

    Transfers the character's ``Contains`` parent from the current room to the
    destination room.
    """

    command_type = "move"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
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

        plan = MutationPlan(
            (
                RemoveEdge(current_room_id, character_id, Contains),
                AddEdge(
                    destination_id,
                    character_id,
                    Contains(mode=ContainmentMode.ROOM_CONTENT),
                ),
                AddEntity(
                    (
                        NoiseComponent(
                            loudness=float(payload.get("noise", 1.0)),
                            text="movement",
                            source_entity_id=str(character_id),
                            room_id=str(destination_id),
                            created_at_epoch=ctx.epoch,
                            expires_at_epoch=ctx.epoch + 60,
                        ),
                    )
                ),
            )
        )

        return planned(
            plan,
            lambda: ActorMovedEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    room_id=str(destination_id),
                    from_room_id=str(current_room_id),
                    to_room_id=str(destination_id),
                    direction=chosen_direction,
                    arrival_summary=render_summary(build_room_facts(ctx.world, destination_id)),
                )
            ),
        )


__all__ = ["MoveHandler"]
