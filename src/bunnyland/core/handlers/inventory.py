"""Inventory verbs: take, drop, put (spec 13.4, 13.5).

``Contains`` is the single canonical containment edge; these handlers move it. ``drop``
is ``put`` with no explicit target (the current room). Reachability for MVP: an item is
reachable if it sits directly in the actor's current room, in the actor's inventory, or
in a container that is itself in the current room.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from relics import EntityId

from ..commands import SubmittedCommand
from ..components import (
    CharacterComponent,
    ContainerComponent,
    DeadComponent,
    HoldableComponent,
    InventoryComponent,
    PortableComponent,
    WearableComponent,
)
from ..ecs import container_of, contents, parse_entity_id
from ..edges import ContainmentMode, Contains, Holding, Wearing
from ..events import (
    ItemDroppedEvent,
    ItemHeldEvent,
    ItemPutEvent,
    ItemRemovedEvent,
    ItemTakenEvent,
    ItemUnheldEvent,
    ItemWornEvent,
)
from .base import HandlerContext, HandlerResult, ok, rejected, require_entity


def _reachable_container_ids(ctx: HandlerContext, character) -> set[EntityId]:
    """Containers the actor can reach: the current room, its contents, and the actor."""
    reachable: set[EntityId] = {character.id}
    room_id = container_of(character)
    if room_id is None:
        return reachable
    reachable.add(room_id)
    room = ctx.entity(room_id)
    reachable.update(contents(room))
    return reachable


class TakeHandler:
    """Pick an item up into the actor's inventory."""

    command_type = "take"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id, character, error = require_entity(
            ctx,
            command.character_id,
            invalid_reason="invalid character or item id",
            missing_reason="character does not exist",
        )
        if error is not None:
            return error
        item_id, item, error = require_entity(
            ctx,
            payload.get("item_id"),
            invalid_reason="invalid character or item id",
            missing_reason="item does not exist",
        )
        if error is not None:
            return error

        source_id = container_of(item)
        if source_id is None:
            return rejected("item is nowhere")
        if source_id == character_id:
            return rejected("already holding item")
        source = ctx.entity(source_id) if ctx.world.has_entity(source_id) else None
        if source is not None:
            if source.has_component(CharacterComponent) and not source.has_component(
                DeadComponent
            ):
                return rejected("item is not reachable")
        if source_id not in _reachable_container_ids(ctx, character):
            return rejected("item is not reachable")

        if not item.has_component(PortableComponent) or not item.get_component(
            PortableComponent
        ).can_pick_up:
            return rejected("item cannot be picked up")

        if source is not None and source.has_component(ContainerComponent):
            container = source.get_component(ContainerComponent)
            if not container.allow_remove:
                return rejected("container does not allow removal")
            if not container.open:
                return rejected("container is closed")

        if character.has_component(InventoryComponent):
            inventory = character.get_component(InventoryComponent)
            if inventory.max_slots is not None and len(contents(character)) >= inventory.max_slots:
                return rejected("inventory is full")

        source.remove_relationship(Contains, item_id)
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item_id)

        return ok(
            ItemTakenEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    room_id=str(container_of(character)),
                    target_ids=(str(item_id),),
                    item_id=str(item_id),
                    from_container_id=str(source_id),
                )
            )
        )


class PutHandler:
    """Put an inventory item into a container, or drop it into the current room."""

    command_type = "put"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id, character, error = require_entity(
            ctx,
            command.character_id,
            invalid_reason="invalid character or item id",
            missing_reason="character does not exist",
        )
        if error is not None:
            return error
        item_id, item, error = require_entity(
            ctx,
            payload.get("item_id"),
            invalid_reason="invalid character or item id",
            missing_reason="item does not exist",
        )
        if error is not None:
            return error
        if container_of(item) != character_id:
            return rejected("item is not in inventory")
        # A fixed-in-place item (e.g. an installed implant) can be carried but not
        # set down or stashed; if you cannot pick it up, you cannot drop it either.
        if item.has_component(PortableComponent) and not item.get_component(
            PortableComponent
        ).can_pick_up:
            return rejected("item is fixed in place and cannot be moved")

        room_id = container_of(character)
        target_id = parse_entity_id(payload.get("target_container_id"))
        is_drop = target_id is None
        if is_drop:
            if room_id is None:
                return rejected("character is not in a room")
            target_id = room_id
            mode = ContainmentMode.ROOM_CONTENT
        else:
            if target_id not in _reachable_container_ids(ctx, character) or target_id == item_id:
                return rejected("target is not reachable")
            target = ctx.entity(target_id)
            if not target.has_component(ContainerComponent):
                return rejected("target is not a container")
            container = target.get_component(ContainerComponent)
            if not container.allow_add:
                return rejected("container does not allow adding")
            if not container.open:
                return rejected("container is closed")
            if (
                container.max_slots is not None
                and len(contents(target)) >= container.max_slots
            ):
                return rejected("container is full")
            mode = ContainmentMode.CONTAINER

        # Drop equipment overlays before relocating the item.
        if character.has_relationship(Holding, item_id):
            character.remove_relationship(Holding, item_id)
        if character.has_relationship(Wearing, item_id):
            character.remove_relationship(Wearing, item_id)

        character.remove_relationship(Contains, item_id)
        ctx.entity(target_id).add_relationship(Contains(mode=mode), item_id)

        if is_drop:
            event = ItemDroppedEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    room_id=str(room_id),
                    target_ids=(str(item_id),),
                    item_id=str(item_id),
                    room_id_dropped=str(room_id),
                )
            )
        else:
            event = ItemPutEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    room_id=str(room_id) if room_id else None,
                    target_ids=(str(item_id),),
                    item_id=str(item_id),
                    to_container_id=str(target_id),
                )
            )
        return ok(event)


class DropHandler(PutHandler):
    """Drop an inventory item into the current room."""

    command_type = "drop"


def _inventory_item(ctx: HandlerContext, command: SubmittedCommand):
    payload: Mapping[str, Any] = command.payload
    character_id, character, error = require_entity(
        ctx,
        command.character_id,
        invalid_reason="invalid character or item id",
        missing_reason="character does not exist",
    )
    if error is not None:
        return None, None, error
    item_id, item, error = require_entity(
        ctx,
        payload.get("item_id"),
        invalid_reason="invalid character or item id",
        missing_reason="item does not exist",
    )
    if error is not None:
        return None, None, error
    if container_of(item) != character_id:
        return None, None, rejected("item is not in inventory")
    return character, item, None


class HoldHandler:
    command_type = "hold"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character, item, error = _inventory_item(ctx, command)
        if error is not None:
            return error
        if not item.has_component(HoldableComponent):
            return rejected("item cannot be held")
        holdable = item.get_component(HoldableComponent)
        if character.has_relationship(Holding, item.id):
            return rejected("already holding item")
        character.add_relationship(Holding(slot=holdable.slot), item.id)
        return ok(
            ItemHeldEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    room_id=str(container_of(character)),
                    target_ids=(str(item.id),),
                    item_id=str(item.id),
                    slot=holdable.slot,
                )
            )
        )


class UnholdHandler:
    command_type = "unhold"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character, item, error = _inventory_item(ctx, command)
        if error is not None:
            return error
        held = [
            edge
            for edge, target_id in character.get_relationships(Holding)
            if target_id == item.id
        ]
        if not held:
            return rejected("item is not held")
        character.remove_relationship(Holding, item.id)
        return ok(
            ItemUnheldEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    room_id=str(container_of(character)),
                    target_ids=(str(item.id),),
                    item_id=str(item.id),
                    slot=held[0].slot,
                )
            )
        )


class WearHandler:
    command_type = "wear"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character, item, error = _inventory_item(ctx, command)
        if error is not None:
            return error
        if not item.has_component(WearableComponent):
            return rejected("item cannot be worn")
        wearable = item.get_component(WearableComponent)
        if character.has_relationship(Wearing, item.id):
            return rejected("already wearing item")
        character.add_relationship(Wearing(slot=wearable.slot), item.id)
        return ok(
            ItemWornEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    room_id=str(container_of(character)),
                    target_ids=(str(item.id),),
                    item_id=str(item.id),
                    slot=wearable.slot,
                )
            )
        )


class RemoveHandler:
    command_type = "remove"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character, item, error = _inventory_item(ctx, command)
        if error is not None:
            return error
        worn = [
            edge
            for edge, target_id in character.get_relationships(Wearing)
            if target_id == item.id
        ]
        if not worn:
            return rejected("item is not worn")
        character.remove_relationship(Wearing, item.id)
        return ok(
            ItemRemovedEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    room_id=str(container_of(character)),
                    target_ids=(str(item.id),),
                    item_id=str(item.id),
                    slot=worn[0].slot,
                )
            )
        )


__all__ = [
    "DropHandler",
    "HoldHandler",
    "PutHandler",
    "RemoveHandler",
    "TakeHandler",
    "UnholdHandler",
    "WearHandler",
]
