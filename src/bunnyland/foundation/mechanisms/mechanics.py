"""Timed mechanisms: doors that swing shut, momentary buttons that pop back (spec 11.9).

The ``use`` verb opens doors and presses buttons; this consequence advances their timers
each tick — closing a door ``auto_close_after_ticks`` ticks after it opened, and releasing a
non-toggle button ``reset_after_ticks`` ticks after it was pressed. Time is counted in world
ticks (``WorldClockComponent.tick_index``). The bookkeeping lives here rather than on the
components, so the components stay simple and these transient timers reset cleanly on reload.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from relics import EntityId, World

from ...core.components import ButtonComponent, DoorComponent, WorldClockComponent
from ...core.ecs import container_of, replace_component
from ...core.events import DomainEvent, EventVisibility
from ...core.events import event_base as _event_base

if TYPE_CHECKING:
    from ...core.world_actor import WorldActor


class DoorAutoClosedEvent(DomainEvent):
    door_id: str


class ButtonResetEvent(DomainEvent):
    button_id: str


def _current_tick(world: World) -> int:
    clocks = list(world.query().with_all([WorldClockComponent]).execute_entities())
    return clocks[0].get_component(WorldClockComponent).tick_index if clocks else 0


def _room_of(world: World, entity_id: EntityId) -> str | None:
    parent = container_of(world.get_entity(entity_id))
    return str(parent) if parent is not None else None


class MechanismConsequence:
    """Advance door/button timers each tick and emit events when they fire (spec 11.9)."""

    def __init__(self) -> None:
        self._door_open_since: dict[EntityId, int] = {}
        self._button_pressed_since: dict[EntityId, int] = {}

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        tick = _current_tick(world)
        return self._close_doors(world, epoch, tick) + self._reset_buttons(world, epoch, tick)

    def _close_doors(self, world: World, epoch: int, tick: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for entity in world.query().with_all([DoorComponent]).execute_entities():
            door = entity.get_component(DoorComponent)
            if door.auto_close_after_ticks is None or not door.open:
                self._door_open_since.pop(entity.id, None)
                continue
            opened_at = self._door_open_since.setdefault(entity.id, tick)
            if tick - opened_at >= door.auto_close_after_ticks:
                replace_component(entity, replace(door, open=False))
                self._door_open_since.pop(entity.id, None)
                events.append(
                    DoorAutoClosedEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.ROOM,
                            room_id=_room_of(world, entity.id),
                            door_id=str(entity.id),
                        )
                    )
                )
        return events

    def _reset_buttons(self, world: World, epoch: int, tick: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for entity in world.query().with_all([ButtonComponent]).execute_entities():
            button = entity.get_component(ButtonComponent)
            # Toggle buttons hold their state; only momentary ones spring back.
            if button.reset_after_ticks is None or button.toggle or not button.pressed:
                self._button_pressed_since.pop(entity.id, None)
                continue
            pressed_at = self._button_pressed_since.setdefault(entity.id, tick)
            if tick - pressed_at >= button.reset_after_ticks:
                replace_component(entity, replace(button, pressed=False))
                self._button_pressed_since.pop(entity.id, None)
                events.append(
                    ButtonResetEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.ROOM,
                            room_id=_room_of(world, entity.id),
                            button_id=str(entity.id),
                        )
                    )
                )
        return events


def install_mechanisms(actor: WorldActor) -> None:
    """Register the mechanism timer consequence on an actor."""
    actor.register_consequence(MechanismConsequence())


__all__ = [
    "ButtonResetEvent",
    "DoorAutoClosedEvent",
    "MechanismConsequence",
    "install_mechanisms",
]
