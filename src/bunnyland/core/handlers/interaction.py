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
    BleedingComponent,
    ButtonComponent,
    CharacterComponent,
    ContainerComponent,
    DescriptionComponent,
    DoorComponent,
    HealthComponent,
    IdentityComponent,
    KeyComponent,
    LockableComponent,
    ReadableComponent,
    RoomComponent,
    StealthComponent,
    WritableComponent,
)
from ..ecs import container_of, parse_entity_id, reachable_ids, replace_component
from ..edges import Contains, Holding, Wearing
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
from .base import HandlerContext, HandlerResult, ok, rejected


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


def _condition_states(entity) -> list[str]:
    """Qualitative, observable condition for a living target.

    Inspect is a fourth-wall-safe ``look++``: it reports how something *appears* to a
    bystander, never raw stats. Health is mapped to coarse tiers and bleeding is binary;
    no numbers ever reach the player.
    """
    states: list[str] = []
    if entity.has_component(HealthComponent):
        health = entity.get_component(HealthComponent)
        ratio = health.current / health.maximum if health.maximum > 0 else 0.0
        if ratio <= 0:
            states.append("gravely injured")
        elif ratio < 0.33:
            states.append("badly wounded")
        elif ratio < 0.66:
            states.append("wounded")
        elif ratio < 0.99:
            states.append("hurt")
    if (
        entity.has_component(BleedingComponent)
        and entity.get_component(BleedingComponent).rate > 0
    ):
        states.append("bleeding")
    return states


def _is_hidden(entity) -> bool:
    return entity.has_component(StealthComponent) and entity.get_component(StealthComponent).hiding


def _equipped_names(ctx: HandlerContext, entity, edge_type) -> list[str]:
    names: list[str] = []
    for _edge, child_id in entity.get_relationships(edge_type):
        if not ctx.world.has_entity(child_id):
            continue
        child = ctx.entity(child_id)
        if _is_hidden(child):
            continue
        names.append(_entity_label(child)[0])
    return sorted(names)


def _visible_contents(ctx: HandlerContext, entity) -> list[str]:
    names: list[str] = []
    for edge, child_id in entity.get_relationships(Contains):
        if not (edge.visible and edge.discovered):
            continue
        if not ctx.world.has_entity(child_id):
            continue
        child = ctx.entity(child_id)
        if _is_hidden(child):
            continue
        names.append(_entity_label(child)[0])
    return sorted(names)


def _observable_specifics(ctx: HandlerContext, entity) -> list[str]:
    """Visible, in-world specifics a bystander could note: species, worn/held gear, and
    the contents of anything they can actually see into."""
    specifics: list[str] = []
    if entity.has_component(CharacterComponent):
        species = entity.get_component(CharacterComponent).species
        if species:
            specifics.append(f"a {species}")
    holding = _equipped_names(ctx, entity, Holding)
    if holding:
        specifics.append(f"holding {', '.join(holding)}")
    wearing = _equipped_names(ctx, entity, Wearing)
    if wearing:
        specifics.append(f"wearing {', '.join(wearing)}")
    if entity.has_component(ContainerComponent):
        container = entity.get_component(ContainerComponent)
        if container.open or container.transparent:
            contents = _visible_contents(ctx, entity)
            if contents:
                specifics.append(f"containing {', '.join(contents)}")
    return specifics


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
                    replace_component(target, replace(lock, locked=False))
                    return self._event(ctx, command, item_id, target_id, "unlocked", tool_id)
                return rejected("it is locked")

        if target.has_component(DoorComponent):
            door = target.get_component(DoorComponent)
            replace_component(target, replace(door, open=not door.open))
            affordance = "door_opened" if not door.open else "door_closed"
            return self._event(ctx, command, item_id, target_id, affordance, tool_id)

        if target.has_component(ButtonComponent):
            button = target.get_component(ButtonComponent)
            if not button.active:
                return rejected("nothing happens")
            replace_component(target, replace(button, pressed=not button.pressed))
            return self._event(ctx, command, item_id, target_id, "button_pressed", tool_id)

        return rejected("you can't use that")

    def _event(self, ctx, command, item_id, target_id, affordance, tool_id) -> HandlerResult:
        target_ids = (str(target_id),) if item_id == target_id else (str(target_id), str(item_id))
        return ok(
            ItemUsedEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=target_ids,
                    item_id=str(item_id),
                    affordance=affordance,
                    tool_id=str(tool_id) if tool_id is not None else None,
                )
            )
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
        return ok(
            RoomLookedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=command.character_id,
                    room_id=str(room_id),
                    target_ids=(str(room_id),),
                    room_title=title,
                    summary=summary,
                )
            )
        )


class InspectHandler:
    command_type = "inspect"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _character, target_id, target, error = _reachable_target(ctx, command)
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
        states.extend(_condition_states(target))
        return ok(
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
                    details=", ".join(_observable_specifics(ctx, target)),
                )
            )
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
            replace_component(target, replace(container, open=True))
            event_type = ContainerOpenedEvent
        elif target.has_component(DoorComponent):
            door = target.get_component(DoorComponent)
            if door.open:
                return rejected("it is already open")
            replace_component(target, replace(door, open=True))
            event_type = DoorOpenedEvent
        else:
            return rejected("target is not openable")
        return ok(
            event_type(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            )
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
            replace_component(target, replace(container, open=False))
            event_type = ContainerClosedEvent
        elif target.has_component(DoorComponent):
            door = target.get_component(DoorComponent)
            if not door.open:
                return rejected("it is already closed")
            replace_component(target, replace(door, open=False))
            event_type = DoorClosedEvent
        else:
            return rejected("target is not closeable")
        return ok(
            event_type(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            )
        )


class UnlockHandler:
    command_type = "unlock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _character, target_id, target, error = _reachable_target(ctx, command)
        if error is not None:
            return error
        tool_id = None
        if target.has_component(LockableComponent):
            lock = target.get_component(LockableComponent)
            if not lock.locked:
                return rejected("it is already unlocked")
            tool_id, reason = _matching_key(ctx, command, lock)
            if reason is not None:
                return rejected(reason)
            replace_component(target, replace(lock, locked=False))
        elif target.has_component(ContainerComponent):
            container = target.get_component(ContainerComponent)
            if not container.locked:
                return rejected("it is already unlocked")
        else:
            return rejected("target is not lockable")
        if target.has_component(ContainerComponent):
            container = target.get_component(ContainerComponent)
            replace_component(target, replace(container, locked=False))
        return ok(
            EntityUnlockedEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    tool_id=str(tool_id) if tool_id is not None else None,
                )
            )
        )


class LockHandler:
    command_type = "lock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        _character, target_id, target, error = _reachable_target(ctx, command)
        if error is not None:
            return error
        tool_id = None
        if target.has_component(LockableComponent):
            lock = target.get_component(LockableComponent)
            if lock.locked:
                return rejected("it is already locked")
            tool_id, reason = _matching_key(ctx, command, lock)
            if reason is not None:
                return rejected(reason)
            replace_component(target, replace(lock, locked=True))
        elif target.has_component(ContainerComponent):
            container = target.get_component(ContainerComponent)
            if container.locked:
                return rejected("it is already locked")
        else:
            return rejected("target is not lockable")
        if target.has_component(ContainerComponent):
            container = target.get_component(ContainerComponent)
            replace_component(target, replace(container, locked=True))
        return ok(
            EntityLockedEvent(
                **ctx.event_base(
                    actor_id=command.character_id,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
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
