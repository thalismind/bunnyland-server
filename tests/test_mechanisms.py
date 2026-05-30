"""Tests for timed mechanisms: door auto-close and momentary button reset (spec 11.9)."""

from __future__ import annotations

from bunnyland.core import (
    ButtonComponent,
    ContainmentMode,
    Contains,
    DoorComponent,
    IdentityComponent,
    RoomComponent,
    WorldActor,
    spawn_entity,
)
from bunnyland.mechanics.mechanisms import (
    ButtonResetEvent,
    DoorAutoClosedEvent,
    install_mechanisms,
)
from bunnyland.projections import RoomSummaryProjection

HOUR = 3600.0


def _actor_with_room():
    actor = WorldActor()
    install_mechanisms(actor)
    room = spawn_entity(actor.world, [RoomComponent(title="Vault")])
    return actor, room


def _place(actor, room, components):
    obj = spawn_entity(actor.world, components)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), obj.id)
    return obj


async def test_door_auto_closes_after_its_timer():
    actor, room = _actor_with_room()
    closed: list[DoorAutoClosedEvent] = []
    actor.bus.subscribe(DoorAutoClosedEvent, closed.append)
    door = _place(
        actor,
        room,
        [
            IdentityComponent(name="gate", kind="door"),
            DoorComponent(open=True, auto_close_after_ticks=2),
        ],
    )

    await actor.tick(HOUR)
    assert door.get_component(DoorComponent).open is True  # timer still running

    await actor.tick(HOUR)
    await actor.tick(HOUR)
    assert door.get_component(DoorComponent).open is False  # swung shut
    assert len(closed) == 1
    assert closed[0].door_id == str(door.id)
    assert closed[0].room_id == str(room.id)


async def test_door_without_timer_stays_open():
    actor, room = _actor_with_room()
    door = _place(
        actor,
        room,
        [IdentityComponent(name="archway", kind="door"), DoorComponent(open=True)],
    )
    for _ in range(4):
        await actor.tick(HOUR)
    assert door.get_component(DoorComponent).open is True


async def test_momentary_button_resets_but_toggle_holds():
    actor, room = _actor_with_room()
    resets: list[ButtonResetEvent] = []
    actor.bus.subscribe(ButtonResetEvent, resets.append)
    momentary = _place(actor, room, [ButtonComponent(pressed=True, reset_after_ticks=1)])
    toggle = _place(actor, room, [ButtonComponent(pressed=True, toggle=True, reset_after_ticks=1)])

    await actor.tick(HOUR)
    await actor.tick(HOUR)

    assert momentary.get_component(ButtonComponent).pressed is False  # sprang back
    assert toggle.get_component(ButtonComponent).pressed is True  # toggle holds
    assert any(event.button_id == str(momentary.id) for event in resets)
    assert all(event.button_id != str(toggle.id) for event in resets)


async def test_auto_closing_door_refreshes_the_room_summary():
    actor, room = _actor_with_room()
    _place(
        actor,
        room,
        [
            IdentityComponent(name="gate", kind="door"),
            DoorComponent(open=True, auto_close_after_ticks=1),
        ],
    )
    projection = RoomSummaryProjection(actor.world).attach()
    assert "open" in projection.summary(room.id, actor.epoch).visible_summary

    await actor.tick(HOUR)  # door open
    await actor.tick(HOUR)  # door auto-closes; the DoorComponent change is queued
    await actor.tick(HOUR)  # observer drains -> room marked dirty

    assert "closed" in projection.summary(room.id, actor.epoch).visible_summary
