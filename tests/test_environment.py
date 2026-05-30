"""Tests for the time-of-day / day-night environment mechanic (spec 11.2, 11.13)."""

from __future__ import annotations

from bunnyland.core import (
    LightComponent,
    RoomComponent,
    WorldActor,
    spawn_entity,
)
from bunnyland.mechanics.environment import (
    CalendarComponent,
    TimeOfDayChangedEvent,
    TimeOfDayComponent,
    environment_fragments,
    install_environment,
    time_of_day,
)

HOUR = 3600.0
DAY = HOUR * 24


def _world():
    actor = WorldActor()
    install_environment(actor)
    return actor


def test_time_of_day_derivation():
    assert time_of_day(0) == (1, 0, "night", "spring")
    assert time_of_day(int(8 * HOUR)) == (1, 8, "day", "spring")
    assert time_of_day(int(19 * HOUR)) == (1, 19, "dusk", "spring")
    # a day-and-a-bit later, at 02:00 on day 2
    assert time_of_day(int(DAY + 2 * HOUR)) == (2, 2, "night", "spring")
    # seasons advance every 28 days
    assert time_of_day(int(30 * DAY))[3] == "summer"


async def test_phase_change_emits_event_and_updates_singletons():
    actor = _world()
    events: list[TimeOfDayChangedEvent] = []
    actor.bus.subscribe(TimeOfDayChangedEvent, events.append)

    # Start of day -> night, then advance to mid-morning (day).
    await actor.tick(0.0)
    assert events[-1].phase == "night"
    clock = list(
        actor.world.query().with_all([TimeOfDayComponent]).execute_entities()
    )[0]
    assert clock.get_component(TimeOfDayComponent).phase == "night"

    await actor.tick(9 * HOUR)  # now 09:00 -> day
    assert clock.get_component(TimeOfDayComponent).phase == "day"
    assert events[-1].phase == "day"
    assert clock.get_component(CalendarComponent).hour == 9


async def test_phase_event_only_on_change():
    actor = _world()
    events: list[TimeOfDayChangedEvent] = []
    actor.bus.subscribe(TimeOfDayChangedEvent, events.append)

    await actor.tick(8 * HOUR)  # -> day
    await actor.tick(1 * HOUR)  # 09:00, still day: no new event
    assert [e.phase for e in events] == ["day"]


async def test_outdoor_light_follows_the_sky_indoor_does_not():
    actor = _world()
    world = actor.world
    outdoor = spawn_entity(
        world, [RoomComponent(title="Meadow", indoor=False), LightComponent(level=1.0)]
    )
    indoor = spawn_entity(
        world, [RoomComponent(title="Burrow", indoor=True), LightComponent(level=0.3)]
    )
    lamp = spawn_entity(
        world,
        [
            RoomComponent(title="Lamplit Cave", indoor=False),
            LightComponent(level=0.8, natural=False),
        ],
    )

    await actor.tick(0.0)  # midnight -> night
    assert outdoor.get_component(LightComponent).level == 0.05  # dark outside
    assert indoor.get_component(LightComponent).level == 0.3  # unchanged indoors
    assert lamp.get_component(LightComponent).level == 0.8  # artificial light unaffected

    await actor.tick(12 * HOUR)  # noon -> day
    assert outdoor.get_component(LightComponent).level == 1.0


async def test_environment_fragment_describes_the_time():
    actor = _world()
    await actor.tick(19 * HOUR)  # dusk on day 1
    fragments = environment_fragments(actor.world, character=None)
    assert fragments and "dusk" in fragments[0]
    assert "day 1" in fragments[0]


def test_fragment_is_empty_before_first_tick():
    actor = _world()  # consequence has not run yet
    assert environment_fragments(actor.world, character=None) == []
