"""Core passive-simulation systems (spec sections 5.6, 6.2, 23.1).

These are Relics ``System`` subclasses run synchronously inside ``world.tick(delta)``,
where ``delta`` is elapsed *game* seconds. They mutate ECS state only; domain events are
emitted by the world actor, which orchestrates the tick. Components are replaced, never
mutated in place.
"""

from __future__ import annotations

from dataclasses import replace

from relics import Frequency, System

from .components import (
    ActionPointsComponent,
    FocusPointsComponent,
    WorldClockComponent,
)
from .ecs import replace_component

SECONDS_PER_HOUR = 3600.0


class WorldClockSystem(System):
    """Advance the world clock by the tick's game-seconds delta (spec 5.6 phase 2)."""

    def query(self):
        return self.q.with_all([WorldClockComponent])

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        for entity in entities:
            clock = entity.get_component(WorldClockComponent)
            advanced = int(delta * clock.time_scale)
            replace_component(
                entity,
                replace(
                    clock,
                    game_time_seconds=clock.game_time_seconds + advanced,
                    tick_index=clock.tick_index + 1,
                ),
            )


def _regen(current: float, maximum: float, overflow_maximum: float | None,
           regen_per_hour: float, delta_seconds: float) -> float:
    cap = overflow_maximum if overflow_maximum is not None else maximum
    gained = regen_per_hour * (delta_seconds / SECONDS_PER_HOUR)
    return min(cap, current + gained)


class ActionFocusRegenSystem(System):
    """Regenerate Action and Focus for *all* characters in real time (spec 6.2).

    Includes suspended characters: they regenerate but never spend, so they recharge
    fully. Spending is handled by command execution, not here.
    """

    def query(self):
        return self.q.with_any([ActionPointsComponent, FocusPointsComponent])

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        for entity in entities:
            if entity.has_component(ActionPointsComponent):
                ap = entity.get_component(ActionPointsComponent)
                new_current = _regen(
                    ap.current, ap.maximum, ap.overflow_maximum, ap.regen_per_hour, delta
                )
                if new_current != ap.current:
                    replace_component(entity, replace(ap, current=new_current))
            if entity.has_component(FocusPointsComponent):
                fp = entity.get_component(FocusPointsComponent)
                new_current = _regen(
                    fp.current, fp.maximum, fp.overflow_maximum, fp.regen_per_hour, delta
                )
                if new_current != fp.current:
                    replace_component(entity, replace(fp, current=new_current))


__all__ = ["ActionFocusRegenSystem", "WorldClockSystem"]
