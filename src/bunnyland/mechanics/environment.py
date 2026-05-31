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

from ..core.commands import SubmittedCommand
from ..core.components import (
    CharacterComponent,
    DeadComponent,
    HealthComponent,
    LightComponent,
    RoomComponent,
    SuspendedComponent,
    WorldClockComponent,
)
from ..core.ecs import container_of, parse_entity_id, reachable_ids, replace_component
from ..core.edges import Contains
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected

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
FIRE_DAMAGE_PER_HOUR = 8.0
FIRE_FUEL_PER_HOUR = 1.0


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


@pydantic_dataclass(frozen=True)
class FlammableComponent(Component):
    fuel: float = 4.0


@pydantic_dataclass(frozen=True)
class FireComponent(Component):
    intensity: float = 1.0
    fuel: float = 4.0
    last_updated_epoch: int = 0


class TimeOfDayChangedEvent(DomainEvent):
    phase: str
    hour: int
    day: int


class WeatherChangedEvent(DomainEvent):
    condition: str
    intensity: float


class FireStartedEvent(DomainEvent):
    target_id: str
    intensity: float


class FireSpreadEvent(DomainEvent):
    source_id: str
    target_id: str


class FireDamageEvent(DomainEvent):
    target_id: str
    damage: float
    health: float


class FireExtinguishedEvent(DomainEvent):
    target_id: str


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


@dataclass
class FireConsequence:
    """Advance burning entities, spread room fires, and apply direct fire damage."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        burning = list(world.query().with_all([FireComponent]).execute_entities())
        for entity in burning:
            fire = entity.get_component(FireComponent)
            elapsed = max(0, epoch - fire.last_updated_epoch)
            if elapsed <= 0:
                continue
            hours = elapsed / SECONDS_PER_HOUR
            room_id = (
                str(entity.id) if entity.has_component(RoomComponent) else container_of(entity)
            )
            target_ids = self._damage_targets(world, entity)
            for target in target_ids:
                events.extend(_damage_fire_target(world, epoch, entity.id, target, hours))
            if entity.has_component(RoomComponent):
                events.extend(_spread_room_fire(world, epoch, entity))
            fuel = fire.fuel - FIRE_FUEL_PER_HOUR * max(0.1, fire.intensity) * hours
            if fuel <= 0:
                entity.remove_component(FireComponent)
                events.append(
                    FireExtinguishedEvent(
                        **_event_base(
                            epoch,
                            room_id=str(room_id) if room_id is not None else None,
                            target_ids=(str(entity.id),),
                            target_id=str(entity.id),
                        )
                    )
                )
            else:
                replace_component(entity, replace(fire, fuel=fuel, last_updated_epoch=epoch))
        return events

    @staticmethod
    def _damage_targets(world: World, entity) -> list:
        if entity.has_component(HealthComponent):
            return [entity]
        if not entity.has_component(RoomComponent):
            return []
        targets = []
        for _edge, target_id in entity.get_relationships(Contains):
            if world.has_entity(target_id):
                targets.append(world.get_entity(target_id))
        return targets


def _damage_fire_target(
    world: World, epoch: int, source_id, target, hours: float
) -> list[DomainEvent]:
    if not target.has_component(CharacterComponent) or not target.has_component(HealthComponent):
        return []
    if target.has_component(DeadComponent) or target.has_component(SuspendedComponent):
        return []
    damage = FIRE_DAMAGE_PER_HOUR * hours
    health = target.get_component(HealthComponent)
    updated = replace(health, current=health.current - damage)
    replace_component(target, updated)
    room_id = container_of(target) or source_id
    return [
        FireDamageEvent(
            **_event_base(
                epoch,
                room_id=str(room_id),
                actor_id=str(source_id),
                target_ids=(str(target.id),),
                target_id=str(target.id),
                damage=damage,
                health=updated.current,
            )
        )
    ]


def _spread_room_fire(world: World, epoch: int, room) -> list[DomainEvent]:
    events: list[DomainEvent] = []
    for _edge, target_id in room.get_relationships(Contains):
        if not world.has_entity(target_id):
            continue
        target = world.get_entity(target_id)
        if target.has_component(FireComponent) or not target.has_component(FlammableComponent):
            continue
        fuel = target.get_component(FlammableComponent).fuel
        replace_component(target, FireComponent(fuel=fuel, last_updated_epoch=epoch))
        events.append(
            FireSpreadEvent(
                **_event_base(
                    epoch,
                    room_id=str(room.id),
                    actor_id=str(room.id),
                    target_ids=(str(target_id),),
                    source_id=str(room.id),
                    target_id=str(target_id),
                )
            )
        )
    return events


class IgniteHandler:
    command_type = "ignite"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None:
            return rejected("invalid character id")
        actor = ctx.entity(actor_id)
        if target_id is None:
            target_id = container_of(actor)
        if target_id is None or not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        if target_id not in reachable_ids(ctx.world, actor):
            return rejected("target is not reachable")
        target = ctx.entity(target_id)
        if target.has_component(FireComponent):
            return rejected("target is already burning")
        if not target.has_component(FlammableComponent):
            return rejected("target is not flammable")
        fuel = target.get_component(FlammableComponent).fuel
        intensity = float(command.payload.get("intensity", 1.0))
        if intensity <= 0:
            return rejected("fire intensity must be positive")
        replace_component(
            target,
            FireComponent(intensity=intensity, fuel=fuel, last_updated_epoch=ctx.epoch),
        )
        return ok(
            FireStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(actor)) if container_of(actor) else None,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    intensity=intensity,
                )
            )
        )


class ExtinguishHandler:
    command_type = "extinguish"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None:
            return rejected("invalid character id")
        actor = ctx.entity(actor_id)
        if target_id is None:
            target_id = container_of(actor)
        if target_id is None or not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        if target_id not in reachable_ids(ctx.world, actor):
            return rejected("target is not reachable")
        target = ctx.entity(target_id)
        if not target.has_component(FireComponent):
            return rejected("target is not burning")
        target.remove_component(FireComponent)
        return ok(
            FireExtinguishedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(container_of(actor)) if container_of(actor) else None,
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            )
        )


# -- prompt fragment (spec 16.3) --------------------------------------------------------


def environment_fragments(world: World, character) -> list[str]:
    """A status line describing the time of day, for the foundation prompt."""
    lines: list[str] = []
    query = world.query().with_all([WorldClockComponent, TimeOfDayComponent])
    clocks = list(query.execute_entities())
    if clocks:
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
            lines.append(f"It is {sky}.")
        else:
            lines.append(f"It is {sky} (day {calendar.day}, {calendar.season}).")
    if character is not None:
        room_id = container_of(character)
        if room_id is not None and world.has_entity(room_id):
            room = world.get_entity(room_id)
            if room.has_component(FireComponent):
                lines.append("There is a fire here.")
        if character.has_component(FireComponent):
            lines.append("You are on fire.")
    return lines


def install_environment(actor: WorldActor) -> None:
    """Register the environment consequence on an actor."""
    actor.register_consequence(EnvironmentConsequence())
    actor.register_consequence(FireConsequence())


__all__ = [
    "CalendarComponent",
    "EnvironmentConsequence",
    "ExtinguishHandler",
    "FireComponent",
    "FireConsequence",
    "FireDamageEvent",
    "FireExtinguishedEvent",
    "FireSpreadEvent",
    "FireStartedEvent",
    "FlammableComponent",
    "IgniteHandler",
    "TimeOfDayChangedEvent",
    "TimeOfDayComponent",
    "WeatherChangedEvent",
    "WeatherComponent",
    "environment_fragments",
    "install_environment",
    "time_of_day",
    "weather_for",
]
