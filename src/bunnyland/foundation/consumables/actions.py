"""Eat and drink verbs (spec 13.7).

Eating and drinking are separate because hunger and thirst are separate. Both relieve a
need meter and may consume the item. An item without a ``ConsumableComponent`` (e.g. a
water basin) is treated as a renewable source and is not destroyed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from bunnyland.foundation.consumables.components import (
    ConsumableComponent,
    DrinkableComponent,
    FoodComponent,
)
from bunnyland.foundation.meters.mechanics import band, changed
from bunnyland.foundation.needs.mechanics import (
    DrinkConsumedEvent,
    FoodEatenEvent,
    HungerChangedEvent,
    HungerComponent,
    ThirstChangedEvent,
    ThirstComponent,
)

from ...core.commands import SubmittedCommand
from ...core.ecs import container_of, parse_entity_id, replace_component
from ...core.edges import Contains
from ...core.handlers.base import HandlerContext, HandlerResult, ok, rejected


def _reachable(ctx: HandlerContext, character, target_id) -> bool:
    """Reachable if the target is in the actor's inventory or the current room floor."""
    holder = container_of(ctx.entity(target_id))
    if holder is None:
        return False
    return holder == character.id or holder == container_of(character)


def _consume_one_use(ctx: HandlerContext, item) -> None:
    """Spend one use; destroy the item when uses run out. No-op without ConsumableComponent."""
    if not item.has_component(ConsumableComponent):
        return
    consumable = item.get_component(ConsumableComponent)
    remaining = consumable.current_uses - 1
    if remaining <= 0:
        holder = container_of(item)
        if holder is not None:
            ctx.entity(holder).remove_relationship(Contains, item.id)
        ctx.world.remove(item.id)
    else:
        replace_component(item, replace(consumable, current_uses=remaining))


class EatHandler:
    command_type = "eat"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id = parse_entity_id(command.character_id)
        item_id = parse_entity_id(payload.get("item_id"))
        if character_id is None or item_id is None or not ctx.world.has_entity(item_id):
            return rejected("invalid or missing item")

        character = ctx.entity(character_id)
        item = ctx.entity(item_id)
        if not item.has_component(FoodComponent):
            return rejected("item is not food")
        if not character.has_component(HungerComponent):
            return rejected("character cannot eat")
        if not _reachable(ctx, character, item_id):
            return rejected("food is not reachable")

        food = item.get_component(FoodComponent)
        hunger = character.get_component(HungerComponent)
        new_meter = changed(hunger.meter, -food.satiety)
        replace_component(character, replace(hunger, meter=new_meter, last_ate_epoch=ctx.epoch))

        events = (
            FoodEatenEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    room_id=str(container_of(character)),
                    target_ids=(str(item_id),),
                    item_id=str(item_id),
                    satiety=food.satiety,
                )
            ),
            HungerChangedEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    value=new_meter.value,
                    band=band(new_meter),
                )
            ),
        )
        _consume_one_use(ctx, item)
        return ok(*events)


class DrinkHandler:
    command_type = "drink"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id = parse_entity_id(command.character_id)
        source_id = parse_entity_id(payload.get("source_id"))
        if character_id is None or source_id is None or not ctx.world.has_entity(source_id):
            return rejected("invalid or missing source")

        character = ctx.entity(character_id)
        source = ctx.entity(source_id)
        if not source.has_component(DrinkableComponent):
            return rejected("source is not drinkable")
        if not character.has_component(ThirstComponent):
            return rejected("character cannot drink")
        if not _reachable(ctx, character, source_id):
            return rejected("source is not reachable")

        drinkable = source.get_component(DrinkableComponent)
        thirst = character.get_component(ThirstComponent)
        new_meter = changed(thirst.meter, -drinkable.hydration)
        replace_component(character, replace(thirst, meter=new_meter, last_drank_epoch=ctx.epoch))

        events = (
            DrinkConsumedEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    room_id=str(container_of(character)),
                    target_ids=(str(source_id),),
                    source_id=str(source_id),
                    hydration=drinkable.hydration,
                )
            ),
            ThirstChangedEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    value=new_meter.value,
                    band=band(new_meter),
                )
            ),
        )
        _consume_one_use(ctx, source)
        return ok(*events)


__all__ = ["DrinkHandler", "EatHandler"]
