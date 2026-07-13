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
    ContainerComponent,
    DescriptionComponent,
    DoorComponent,
    IdentityComponent,
    KeyComponent,
    LockableComponent,
    ReadableComponent,
    RoomComponent,
    WritableComponent,
)
from ..ecs import container_of, parse_entity_id, reachable_ids
from ..edges import Contains
from ..events import (
    ContainerClosedEvent,
    ContainerOpenedEvent,
    DoorClosedEvent,
    DoorOpenedEvent,
    EntityInspectedEvent,
    EntityLockedEvent,
    EntityUnlockedEvent,
    EventVisibility,
    ItemUsedEvent,
    PhysicalWriteEvent,
    RoomLookedEvent,
)
from ..mutations import MutationPlan, SetComponent
from .base import HandlerContext, HandlerResult, planned, rejected


def _reachable_target(ctx: HandlerContext, command: SubmittedCommand, key: str = "target_id"):
    payload: Mapping[str, Any] = command.payload
    character_id = parse_entity_id(command.character_id)
    target_id = parse_entity_id(payload.get(key))
    if character_id is None or target_id is None:
        return None, None, None, rejected("invalid character or target id")
    if not ctx.world.has_entity(character_id):
        return None, None, None, rejected("character does not exist")
    if not ctx.world.has_entity(target_id):
        return None, None, None, rejected("target does not exist")
    character = ctx.entity(character_id)
    if target_id not in reachable_ids(ctx.world, character):
        return None, None, None, rejected("target is not reachable")
    return character, target_id, ctx.entity(target_id), None


def _entity_label(entity) -> tuple[str, str | None]:
    if entity.has_component(IdentityComponent):
        identity = entity.get_component(IdentityComponent)
        return identity.name, identity.kind
    if entity.has_component(RoomComponent):
        return entity.get_component(RoomComponent).title, "room"
    return str(entity.id), None


def _description_text(entity) -> str:
    if not entity.has_component(DescriptionComponent):
        return ""
    description = entity.get_component(DescriptionComponent)
    return description.long or description.short or description.appearance


def _lock_state(entity) -> bool:
    if entity.has_component(LockableComponent) and entity.get_component(LockableComponent).locked:
        return True
    if entity.has_component(ContainerComponent) and entity.get_component(ContainerComponent).locked:
        return True
    return False


def _matching_key(ctx: HandlerContext, command: SubmittedCommand, lock: LockableComponent):
    if lock.key_name is None:
        return None, None
    tool_id = parse_entity_id(command.payload.get("tool_id"))
    if tool_id is None:
        return None, "matching key is required"
    character = ctx.entity(parse_entity_id(command.character_id))
    if tool_id not in reachable_ids(ctx.world, character):
        return None, "tool is not reachable"
    tool = ctx.entity(tool_id)
    if (
        not tool.has_component(KeyComponent)
        or tool.get_component(KeyComponent).key_name != lock.key_name
    ):
        return None, "matching key is required"
    return tool_id, None


def _resolved_use_payload(payload: Mapping[str, Any]):
    item_id = parse_entity_id(payload.get("item_id"))
    target_id = parse_entity_id(payload.get("target_id"))
    tool_id = parse_entity_id(payload.get("tool_id"))
    if item_id is None:
        # Legacy clients used target_id as the used object and tool_id as a helper item.
        return target_id, target_id, tool_id
    return item_id, target_id or item_id, item_id if target_id is not None else tool_id


class UseHandler:
    command_type = "use"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id = parse_entity_id(command.character_id)
        item_id, target_id, tool_id = _resolved_use_payload(payload)
        has_item_payload = "item_id" in payload
        if character_id is None or item_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(character_id):
            return rejected("character does not exist")
        if not ctx.world.has_entity(item_id):
            return rejected("item does not exist" if has_item_payload else "target does not exist")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        character = ctx.entity(character_id)
        reachable = reachable_ids(ctx.world, character)
        if item_id not in reachable:
            return rejected(
                "item is not reachable" if has_item_payload else "target is not reachable"
            )
        if target_id not in reachable:
            return rejected("target is not reachable")
        if tool_id is not None and tool_id != item_id and tool_id not in reachable:
            return rejected("tool is not reachable")

        target = ctx.entity(target_id)

        # Locked things must be unlocked first with the item being used.
        if target.has_component(LockableComponent):
            lock = target.get_component(LockableComponent)
            if lock.locked:
                tool = ctx.entity(tool_id) if tool_id is not None else None
                if (
                    tool is not None
                    and tool.has_component(KeyComponent)
                    and tool.get_component(KeyComponent).key_name == lock.key_name
                ):
                    return self._event(
                        ctx,
                        command,
                        item_id,
                        target_id,
                        "unlocked",
                        tool_id,
                        MutationPlan((SetComponent(target_id, replace(lock, locked=False)),)),
                    )
                return rejected("it is locked")

        if target.has_component(DoorComponent):
            door = target.get_component(DoorComponent)
            affordance = "door_opened" if not door.open else "door_closed"
            return self._event(
                ctx,
                command,
                item_id,
                target_id,
                affordance,
                tool_id,
                MutationPlan((SetComponent(target_id, replace(door, open=not door.open)),)),
            )

        if target.has_component(ButtonComponent):
            button = target.get_component(ButtonComponent)
            if not button.active:
                return rejected("nothing happens")
            return self._event(
                ctx,
                command,
                item_id,
                target_id,
                "button_pressed",
                tool_id,
                MutationPlan(
                    (SetComponent(target_id, replace(button, pressed=not button.pressed)),)
                ),
            )

        return rejected("you can't use that")

    def _event(
        self,
        ctx,
        command,
        item_id,
        target_id,
        affordance,
        tool_id,
        plan,
    ) -> HandlerResult:
        target_ids = (str(target_id),) if item_id == target_id else (str(target_id), str(item_id))
        return planned(
            plan,
            ItemUsedEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=target_ids,
                    item_id=str(item_id),
                    affordance=affordance,
                    tool_id=str(tool_id) if tool_id is not None else None,
                )
            ),
            ctx=ctx,
        )


class LookHandler:
    command_type = "look"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        if not ctx.world.has_entity(character_id):
            return rejected("character does not exist")
        character = ctx.entity(character_id)
        room_id = container_of(character)
        if room_id is None:
            return rejected("character is not in a room")
        room = ctx.entity(room_id)
        title, _kind = _entity_label(room)
        visible = []
        for _edge, child_id in room.get_relationships(Contains):
            if child_id == character_id:
                continue
            child = ctx.entity(child_id)
            visible.append(_entity_label(child)[0])
        summary = title if not visible else f"{title}: {', '.join(sorted(visible))}"
        return planned(
            MutationPlan(),
            RoomLookedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=command.character_id,
                    room_id=str(room_id),
                    target_ids=(str(room_id),),
                    room_title=title,
                    summary=summary,
                )
            ),
            ctx=ctx,
        )


class InspectHandler:
    command_type = "inspect"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character, target_id, target, error = _reachable_target(ctx, command)
        if error is not None:
            return error
        name, kind = _entity_label(target)
        readable = (
            target.get_component(ReadableComponent)
            if target.has_component(ReadableComponent)
            else None
        )
        states: list[str] = []
        if target.has_component(ContainerComponent):
            container = target.get_component(ContainerComponent)
            states.append("open" if container.open else "closed")
            if container.locked:
                states.append("locked")
        if target.has_component(DoorComponent):
            states.append("open" if target.get_component(DoorComponent).open else "closed")
        if (
            target.has_component(LockableComponent)
            and target.get_component(LockableComponent).locked
        ):
            states.append("locked")
        facts: tuple[dict[str, object], ...] = ()
        if ctx.actor is not None:
            from ...prompts import DETAILED_DETAIL_CUTOFF

            projected = ctx.actor.project_prompt_facts(
                target,
                viewer=character,
                cutoff=DETAILED_DETAIL_CUTOFF,
            )
            facts = tuple(
                {"key": fact.key, "text": fact.text, "detail": fact.detail}
                for fact in projected
            )
        return planned(
            MutationPlan(),
            EntityInspectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    entity_id=str(target_id),
                    name=name,
                    kind=kind,
                    description=_description_text(target),
                    text=readable.text if readable else "",
                    state=", ".join(states),
                    facts=facts,
                )
            ),
            ctx=ctx,
        )


class OpenHandler:
    command_type = "open"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _character, target_id, target, error = _reachable_target(ctx, command)
        if error is not None:
            return error
        if _lock_state(target):
            return rejected("it is locked")
        if target.has_component(ContainerComponent):
            container = target.get_component(ContainerComponent)
            if container.open:
                return rejected("it is already open")
            component = replace(container, open=True)
            event_type = ContainerOpenedEvent
        elif target.has_component(DoorComponent):
            door = target.get_component(DoorComponent)
            if door.open:
                return rejected("it is already open")
            component = replace(door, open=True)
            event_type = DoorOpenedEvent
        else:
            return rejected("target is not openable")
        return planned(
            MutationPlan((SetComponent(target_id, component),)),
            event_type(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            ),
            ctx=ctx,
        )


class CloseHandler:
    command_type = "close"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _character, target_id, target, error = _reachable_target(ctx, command)
        if error is not None:
            return error
        if target.has_component(ContainerComponent):
            container = target.get_component(ContainerComponent)
            if not container.open:
                return rejected("it is already closed")
            component = replace(container, open=False)
            event_type = ContainerClosedEvent
        elif target.has_component(DoorComponent):
            door = target.get_component(DoorComponent)
            if not door.open:
                return rejected("it is already closed")
            component = replace(door, open=False)
            event_type = DoorClosedEvent
        else:
            return rejected("target is not closeable")
        return planned(
            MutationPlan((SetComponent(target_id, component),)),
            event_type(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            ),
            ctx=ctx,
        )


class UnlockHandler:
    command_type = "unlock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _character, target_id, target, error = _reachable_target(ctx, command)
        if error is not None:
            return error
        tool_id = None
        operations = []
        if target.has_component(LockableComponent):
            lock = target.get_component(LockableComponent)
            if not lock.locked:
                return rejected("it is already unlocked")
            tool_id, reason = _matching_key(ctx, command, lock)
            if reason is not None:
                return rejected(reason)
            operations.append(SetComponent(target_id, replace(lock, locked=False)))
        elif target.has_component(ContainerComponent):
            container = target.get_component(ContainerComponent)
            if not container.locked:
                return rejected("it is already unlocked")
        else:
            return rejected("target is not lockable")
        if target.has_component(ContainerComponent):
            container = target.get_component(ContainerComponent)
            operations.append(SetComponent(target_id, replace(container, locked=False)))
        return planned(
            MutationPlan(tuple(operations)),
            EntityUnlockedEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    tool_id=str(tool_id) if tool_id is not None else None,
                )
            ),
            ctx=ctx,
        )


class LockHandler:
    command_type = "lock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _character, target_id, target, error = _reachable_target(ctx, command)
        if error is not None:
            return error
        tool_id = None
        operations = []
        if target.has_component(LockableComponent):
            lock = target.get_component(LockableComponent)
            if lock.locked:
                return rejected("it is already locked")
            tool_id, reason = _matching_key(ctx, command, lock)
            if reason is not None:
                return rejected(reason)
            operations.append(SetComponent(target_id, replace(lock, locked=True)))
        elif target.has_component(ContainerComponent):
            container = target.get_component(ContainerComponent)
            if container.locked:
                return rejected("it is already locked")
        else:
            return rejected("target is not lockable")
        if target.has_component(ContainerComponent):
            container = target.get_component(ContainerComponent)
            operations.append(SetComponent(target_id, replace(container, locked=True)))
        return planned(
            MutationPlan(tuple(operations)),
            EntityLockedEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    tool_id=str(tool_id) if tool_id is not None else None,
                )
            ),
            ctx=ctx,
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
        if not ctx.world.has_entity(character_id):
            return rejected("character does not exist")
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
        operations = [SetComponent(target_id, replace(existing, text=new_text))]
        if writable.remaining_space is not None:
            operations.append(
                SetComponent(
                    target_id,
                    replace(
                        writable,
                        remaining_space=writable.remaining_space - len(text),
                    ),
                )
            )

        return planned(
            MutationPlan(tuple(operations)),
            PhysicalWriteEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    item_id=str(target_id),
                    text=text,
                )
            ),
            ctx=ctx,
        )


__all__ = [
    "CloseHandler",
    "InspectHandler",
    "LockHandler",
    "LookHandler",
    "OpenHandler",
    "UnlockHandler",
    "UseHandler",
    "WriteHandler",
]
