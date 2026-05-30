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

# Weather cycles deterministically by day so worlds stay reproducible and persist cleanly.
# Each condition dims outdoor daylight by a factor. Day 1 is clear (keeps the bright day).
_WEATHER_BY_DAY = ("clear", "clear", "cloudy", "overcast", "rain", "cloudy", "overcast")
_WEATHER_INTENSITY = {"clear": 0.0, "cloudy": 0.3, "overcast": 0.5, "rain": 0.7, "storm": 1.0}
_WEATHER_LIGHT = {"clear": 1.0, "cloudy": 0.85, "overcast": 0.65, "rain": 0.5, "storm": 0.3}


# -- components (spec 11.2, 11.13) ------------------------------------------------------


@pydantic_dataclass(frozen=True)
class CalendarComponent(Component):
    day: int = 1
    season: str = "spring"
    hour: int = 8


@pydantic_dataclass(frozen=True)
class TimeOfDayComponent(Component):
    phase: str = "day"


@pydantic_dataclass(frozen=True)
class WeatherComponent(Component):
    condition: str = "clear"
    intensity: float = 0.0


class TimeOfDayChangedEvent(DomainEvent):
    phase: str
    hour: int
    day: int


class WeatherChangedEvent(DomainEvent):
    condition: str
    intensity: float


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


def weather_for(day: int) -> tuple[str, float]:
    """Deterministic ``(condition, intensity)`` for a day number."""
    condition = _WEATHER_BY_DAY[(day - 1) % len(_WEATHER_BY_DAY)]
    return condition, _WEATHER_INTENSITY[condition]


def _event_base(epoch: int, **kwargs) -> dict:
    base = {
        "event_id": uuid4().hex,
        "world_epoch": epoch,
        "created_at": datetime.now(UTC),
        "visibility": EventVisibility.ROOM,
    }
    base.update(kwargs)
    return base


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
        condition, intensity = weather_for(day)

        previous_phase = (
            clock_entity.get_component(TimeOfDayComponent).phase
            if clock_entity.has_component(TimeOfDayComponent)
            else None
        )
        previous_weather = (
            clock_entity.get_component(WeatherComponent).condition
            if clock_entity.has_component(WeatherComponent)
            else None
        )
        replace_component(clock_entity, TimeOfDayComponent(phase=phase))
        replace_component(clock_entity, CalendarComponent(day=day, season=season, hour=hour))
        replace_component(clock_entity, WeatherComponent(condition=condition, intensity=intensity))

        # Outdoor daylight is the time-of-day level dimmed by the weather.
        level = round(_phase_and_light(hour)[1] * _WEATHER_LIGHT[condition], 3)
        self._light_outdoor_rooms(world, level)

        events: list[DomainEvent] = []
        if phase != previous_phase:
            events.append(
                TimeOfDayChangedEvent(
                    **_event_base(epoch, phase=phase, hour=hour, day=day)
                )
            )
        if condition != previous_weather:
            events.append(
                WeatherChangedEvent(
                    **_event_base(epoch, condition=condition, intensity=intensity)
                )
            )
        return events

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
    weather = (
        clock.get_component(WeatherComponent).condition
        if clock.has_component(WeatherComponent)
        else None
    )
    sky = f"{weather} {phase}" if weather and weather != "clear" else phase
    if calendar is None:
        return [f"It is {sky}."]
    return [f"It is {sky} (day {calendar.day}, {calendar.season})."]


def install_environment(actor: WorldActor) -> None:
    """Register the environment consequence on an actor."""
    actor.register_consequence(EnvironmentConsequence())


__all__ = [
    "CalendarComponent",
    "EnvironmentConsequence",
    "TimeOfDayChangedEvent",
    "TimeOfDayComponent",
    "WeatherChangedEvent",
    "WeatherComponent",
    "environment_fragments",
    "install_environment",
    "time_of_day",
    "weather_for",
]
