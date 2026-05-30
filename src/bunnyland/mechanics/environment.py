"""Time-of-day, calendar, and the day/night light cycle (spec 11.2, 11.13).

The world clock advances game-seconds every tick; this mechanic derives the human-facing
time from it — the day number, hour, season, and a coarse phase (night/dawn/day/dusk) — and
drives the natural light level of outdoor rooms so it gets dark at night. It runs as a
consequence (not a passive system) so it can emit a ``TimeOfDayChangedEvent`` when the phase
turns over, which the controller layer can relay ("dusk settles over the marsh").
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic.dataclasses import dataclass as pydantic_dataclass
from relics import Component, World

from ..core.components import LightComponent, RoomComponent, WorldClockComponent
from ..core.ecs import replace_component
from ..core.events import DomainEvent, EventVisibility

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor

SECONDS_PER_HOUR = 3600
HOURS_PER_DAY = 24
SECONDS_PER_DAY = SECONDS_PER_HOUR * HOURS_PER_DAY
DAYS_PER_SEASON = 28
SEASONS = ("spring", "summer", "autumn", "winter")

# (start_hour, phase, natural light level for outdoor rooms). Ordered, last match wins.
_PHASES = (
    (0, "night", 0.05),
    (5, "dawn", 0.4),
    (7, "day", 1.0),
    (18, "dusk", 0.4),
    (20, "night", 0.05),
)


# -- components (spec 11.2, 11.13) ------------------------------------------------------


@pydantic_dataclass(frozen=True)
class CalendarComponent(Component):
    day: int = 1
    season: str = "spring"
    hour: int = 8


@pydantic_dataclass(frozen=True)
class TimeOfDayComponent(Component):
    phase: str = "day"


class TimeOfDayChangedEvent(DomainEvent):
    phase: str
    hour: int
    day: int


# -- derivation -------------------------------------------------------------------------


def _phase_and_light(hour: int) -> tuple[str, float]:
    phase, light = _PHASES[0][1], _PHASES[0][2]
    for start, name, level in _PHASES:
        if hour >= start:
            phase, light = name, level
    return phase, light


def time_of_day(game_time_seconds: int) -> tuple[int, int, str, str]:
    """Return ``(day, hour, phase, season)`` for a game-clock reading."""
    day = game_time_seconds // SECONDS_PER_DAY + 1
    hour = (game_time_seconds % SECONDS_PER_DAY) // SECONDS_PER_HOUR
    phase, _light = _phase_and_light(hour)
    season = SEASONS[((day - 1) // DAYS_PER_SEASON) % len(SEASONS)]
    return day, hour, phase, season


# -- consequence ------------------------------------------------------------------------


@dataclass
class EnvironmentConsequence:
    """Update the calendar/time-of-day singletons and outdoor light each tick."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        clocks = list(world.query().with_all([WorldClockComponent]).execute_entities())
        if not clocks:
            return []
        clock_entity = clocks[0]
        seconds = clock_entity.get_component(WorldClockComponent).game_time_seconds
        day, hour, phase, season = time_of_day(seconds)
        _light = _phase_and_light(hour)[1]

        previous_phase = (
            clock_entity.get_component(TimeOfDayComponent).phase
            if clock_entity.has_component(TimeOfDayComponent)
            else None
        )
        replace_component(clock_entity, TimeOfDayComponent(phase=phase))
        replace_component(clock_entity, CalendarComponent(day=day, season=season, hour=hour))

        self._light_outdoor_rooms(world, _light)

        if phase == previous_phase:
            return []
        return [
            TimeOfDayChangedEvent(
                event_id=uuid4().hex,
                world_epoch=epoch,
                created_at=datetime.now(UTC),
                visibility=EventVisibility.ROOM,
                phase=phase,
                hour=hour,
                day=day,
            )
        ]

    @staticmethod
    def _light_outdoor_rooms(world: World, level: float) -> None:
        query = world.query().with_all([RoomComponent, LightComponent])
        for room in query.execute_entities():
            if room.get_component(RoomComponent).indoor:
                continue
            light = room.get_component(LightComponent)
            if not light.natural:
                continue  # artificial lighting is unaffected by the sky
            if light.level != level:
                replace_component(room, replace(light, level=level))


# -- prompt fragment (spec 16.3) --------------------------------------------------------


def environment_fragments(world: World, character) -> list[str]:
    """A status line describing the time of day, for the foundation prompt."""
    del character
    query = world.query().with_all([WorldClockComponent, TimeOfDayComponent])
    clocks = list(query.execute_entities())
    if not clocks:
        return []
    clock = clocks[0]
    calendar = (
        clock.get_component(CalendarComponent)
        if clock.has_component(CalendarComponent)
        else None
    )
    phase = clock.get_component(TimeOfDayComponent).phase
    if calendar is None:
        return [f"It is {phase}."]
    return [f"It is {phase} (day {calendar.day}, {calendar.season})."]


def install_environment(actor: WorldActor) -> None:
    """Register the environment consequence on an actor."""
    actor.register_consequence(EnvironmentConsequence())


__all__ = [
    "CalendarComponent",
    "EnvironmentConsequence",
    "TimeOfDayChangedEvent",
    "TimeOfDayComponent",
    "environment_fragments",
    "install_environment",
    "time_of_day",
]
