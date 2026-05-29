"""Object interaction verbs: use (affordance dispatch) and write (spec 13.6, 13.11).

``use`` inspects the target's components and dispatches to the matching affordance
(unlock with a key, open/close a door, press a button). ``write`` mutates physical,
discoverable text on a writable object — distinct from private notes (spec 15.4).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ..commands import SubmittedCommand
from ..components import (
    ButtonComponent,
    DoorComponent,
    KeyComponent,
    LockableComponent,
    ReadableComponent,
    WritableComponent,
)
from ..ecs import parse_entity_id, reachable_ids, replace_component
from ..events import ItemUsedEvent, PhysicalWriteEvent
from .base import HandlerContext, HandlerResult, ok, rejected


class UseHandler:
    command_type = "use"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(payload.get("target_id"))
        tool_id = parse_entity_id(payload.get("tool_id"))
        if character_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        character = ctx.entity(character_id)
        reachable = reachable_ids(ctx.world, character)
        if target_id not in reachable:
            return rejected("target is not reachable")
        if tool_id is not None and tool_id not in reachable:
            return rejected("tool is not reachable")

        target = ctx.entity(target_id)

        # Locked things must be unlocked first (with a matching key as the tool).
        if target.has_component(LockableComponent):
            lock = target.get_component(LockableComponent)
            if lock.locked:
                tool = ctx.entity(tool_id) if tool_id is not None else None
                if (
                    tool is not None
                    and tool.has_component(KeyComponent)
                    and tool.get_component(KeyComponent).key_name == lock.key_name
                ):
                    replace_component(target, replace(lock, locked=False))
                    return self._event(ctx, command, target_id, "unlocked", tool_id)
                return rejected("it is locked")

        if target.has_component(DoorComponent):
            door = target.get_component(DoorComponent)
            replace_component(target, replace(door, open=not door.open))
            affordance = "door_opened" if not door.open else "door_closed"
            return self._event(ctx, command, target_id, affordance, tool_id)

        if target.has_component(ButtonComponent):
            button = target.get_component(ButtonComponent)
            if not button.active:
                return rejected("nothing happens")
            replace_component(target, replace(button, pressed=not button.pressed))
            return self._event(ctx, command, target_id, "button_pressed", tool_id)

        return rejected("you can't use that")

    def _event(self, ctx, command, target_id, affordance, tool_id) -> HandlerResult:
        return ok(
            ItemUsedEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    item_id=str(target_id),
                    affordance=affordance,
                    tool_id=str(tool_id) if tool_id is not None else None,
                )
            )
        )


class WriteHandler:
    command_type = "write"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(payload.get("target_id"))
        text = str(payload.get("text", ""))
        if character_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not text.strip():
            return rejected("nothing to write")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        character = ctx.entity(character_id)
        if target_id not in reachable_ids(ctx.world, character):
            return rejected("target is not reachable")

        target = ctx.entity(target_id)
        if not target.has_component(WritableComponent):
            return rejected("you can't write on that")

        writable = target.get_component(WritableComponent)
        if writable.remaining_space is not None and len(text) > writable.remaining_space:
            return rejected("not enough room to write that")

        existing = (
            target.get_component(ReadableComponent)
            if target.has_component(ReadableComponent)
            else ReadableComponent()
        )
        new_text = text if not existing.text else f"{existing.text}\n{text}"
        replace_component(target, replace(existing, text=new_text))
        if writable.remaining_space is not None:
            replace_component(
                target, replace(writable, remaining_space=writable.remaining_space - len(text))
            )

        return ok(
            PhysicalWriteEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    item_id=str(target_id),
                    text=text,
                )
            )
        )


__all__ = ["UseHandler", "WriteHandler"]
